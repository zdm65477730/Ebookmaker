# -*- coding: utf-8 -*-
"""HTTP 客户端：会话复用、UA 轮换、指数退避重试、编码探测、反爬识别。

反爬手段（对应方案）：
- 完整浏览器请求头指纹 + User-Agent 池轮换
- Referer / Cookie 按站点注入
- 域名级令牌桶限速 + 每请求随机抖动
- 403/429/503 与验证码页识别 => 域名冷却 + 代理轮换
- 代理池接入（可关闭，source=none 时直连）
- 编码自动探测（HTTP 头 / meta charset / charset-normalizer / apparent）
"""

import random
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Optional

import requests
import urllib3

from .config import FetchConfig
from .log import get_logger
from .ratelimit import DomainLimiter, BLOCK_STATUS, url_host

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = get_logger(__name__)

# 现代浏览器 UA 池（旧工程里全是上古 UA，反而更容易被识别）
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
]

META_CHARSET_RE = re.compile(rb"<meta[^>]+charset=[\"']?([a-zA-Z0-9_\-]+)", re.I)

BASE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "upgrade-insecure-requests": "1",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
}


class FetchError(Exception):
    """重试耗尽后抛出。"""


@dataclass
class HttpResponse:
    url: str
    status: int
    content: bytes
    text: str
    content_type: str = ""


class HttpClient:
    """线程安全的取回器。

    proxy_picker: 无参函数，返回 requests 的 proxies dict 或 None（直连）。
    on_proxy_error: 通知代理池某代理失败。
    """

    def __init__(self, fetch_cfg: FetchConfig, limiter: Optional[DomainLimiter] = None,
                 proxy_picker: Optional[Callable[[], Optional[dict]]] = None,
                 on_proxy_error: Optional[Callable[[dict], None]] = None):
        self.cfg = fetch_cfg
        self.limiter = limiter
        self._pick_proxy = proxy_picker
        self._on_proxy_error = on_proxy_error
        self._local = threading.local()
        # 连接层连续失败计数（host -> 次数）：触发 reset/超时的风暴时主动冷却
        self._conn_fails = defaultdict(int)
        self._conn_lock = threading.Lock()

    # ---- session 按线程复用 ----
    def _session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            self._local.session = s
        return s

    def _headers(self, referer: Optional[str], cookie: Optional[str]) -> dict:
        h = dict(BASE_HEADERS)
        h["user-agent"] = random.choice(UA_POOL)
        if referer:
            h["referer"] = referer
            h["sec-fetch-site"] = "same-origin"
        ck = cookie or self.cfg.cookie
        if ck:
            h["cookie"] = ck
        return h

    def backoff(self, attempt: int) -> float:
        base = min(self.cfg.backoff_max, self.cfg.backoff_base * (2 ** attempt))
        return base * (0.5 + random.random())  # 退避 + 抖动

    def _reset_session(self):
        """连接被重置/死掉 keep-alive 后重建本线程会话（新 TCP+TLS）。"""
        old = getattr(self._local, "session", None)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self._local.session = None

    def _note_conn_failure(self, url: str) -> bool:
        """累计同 host 连接层失败；连续≥3次则冷却域名并返回 True。"""
        host = url_host(url)
        with self._conn_lock:
            self._conn_fails[host] += 1
            n = self._conn_fails[host]
        if n >= 3:
            with self._conn_lock:
                self._conn_fails[host] = 0
            if self.limiter:
                self.limiter.penalize(url, seconds=min(60, 5 * n))
            return True
        return False

    def _clear_conn_failure(self, url: str):
        host = url_host(url)
        with self._conn_lock:
            if host in self._conn_fails:
                del self._conn_fails[host]

    @staticmethod
    def _retry_after(resp) -> Optional[float]:
        """解析 Retry-After 头（仅支持秒数形式，429/503 常见）。"""
        val = resp.headers.get("retry-after") if resp.headers else None
        if not val:
            return None
        try:
            secs = float(re.match(r"\s*([\d.]+)", str(val)).group(1))
            return min(120.0, max(0.5, secs))
        except (TypeError, ValueError, AttributeError):
            return None

    def get(self, url: str, referer: Optional[str] = None, cookie: Optional[str] = None,
            stream: bool = False, as_text: bool = True, timeout: Optional[float] = None) -> HttpResponse:
        """抓取 URL，带重试/退避/反爬处理。失败抛 FetchError。"""
        last_error = None
        attempts = max(1, self.cfg.retry_count)
        force_close = False
        for attempt in range(attempts):
            if self.limiter:
                self.limiter.acquire(url)
            time.sleep(random.uniform(self.cfg.jitter_min, self.cfg.jitter_max))
            proxy = self._pick_proxy() if self._pick_proxy else None
            headers = self._headers(referer, cookie)
            if force_close:
                # 连接重置后下一次尝试禁用 keep-alive，避免复用死连接
                headers["Connection"] = "close"
            try:
                resp = self._session().get(
                    url,
                    headers=headers,
                    proxies=proxy,
                    verify=self.cfg.verify_ssl,
                    timeout=(self.cfg.timeout_connect, timeout or self.cfg.timeout_read),
                    stream=stream,
                )
                self._clear_conn_failure(url)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                # reset by peer / 握手超时：典型 keep-alive 复用或限流特征
                last_error = "连接异常: {}".format(e.__class__.__name__)
                self._reset_session()
                force_close = True
                if proxy is not None and self._on_proxy_error:
                    self._on_proxy_error(proxy)
                cooled = self._note_conn_failure(url)
                log.debug("%s 连接失败(%s, 冷却=%s)，重建会话重试", url, e.__class__.__name__, cooled)
                time.sleep(self.backoff(attempt + (2 if cooled else 0)))
                continue
            except requests.RequestException as e:
                last_error = "请求异常: {}".format(e)
                if proxy is not None and self._on_proxy_error:
                    self._on_proxy_error(proxy)
                log.debug("%s [%s] 第%d次失败: %s", url, proxy and list(proxy.values())[0], attempt + 1, last_error)
                time.sleep(self.backoff(attempt))
                continue

            if resp.status_code in BLOCK_STATUS:
                last_error = "HTTP {}".format(resp.status_code)
                if proxy is not None and self._on_proxy_error:
                    self._on_proxy_error(proxy)
                # 429/503 通常是速率超限：尊重站点 Retry-After，limiter 内部自适应降速
                ra = self._retry_after(resp)
                if self.limiter:
                    self.limiter.penalize(url, seconds=ra)
                log.debug("%s 被封 (%s)，退避重试", url, last_error)
                if ra is not None:
                    time.sleep(ra + random.uniform(0.2, 1.0))
                else:
                    time.sleep(self.backoff(attempt))
                continue

            if resp.status_code >= 400:
                raise FetchError("{} 返回 HTTP {}".format(url, resp.status_code))

            content = resp.content
            if not as_text:
                if self.limiter:
                    self.limiter.succeed(url)
                return HttpResponse(url, resp.status_code, content, "", resp.headers.get("content-type", ""))

            text = self.decode(resp, content)
            # 验证码/人机验证页：等同被封
            if not stream and self.limiter and DomainLimiter.is_blocked_body(text):
                last_error = "命中反爬页面特征"
                if proxy is not None and self._on_proxy_error:
                    self._on_proxy_error(proxy)
                self.limiter.penalize(url)
                time.sleep(self.backoff(attempt))
                continue
            if self.limiter:
                self.limiter.succeed(url)
            return HttpResponse(url, resp.status_code, content, text, resp.headers.get("content-type", ""))

        raise FetchError("{} 重试 {} 次后仍失败: {}".format(url, attempts, last_error))

    # ---- 编码探测：等价重写旧 loadData 的修正逻辑 ----
    @staticmethod
    def decode(resp: requests.Response, content: bytes) -> str:
        encoding = (resp.encoding or "").lower()
        if encoding in ("", "iso-8859-1"):
            m = META_CHARSET_RE.search(content[:4096])
            if m:
                encoding = m.group(1).decode("ascii", "ignore").lower()
            else:
                try:
                    from charset_normalizer import from_bytes
                    guess = from_bytes(content[:65536]).best()
                    encoding = guess.encoding if guess else "utf-8"
                except ImportError:
                    encoding = resp.apparent_encoding or "utf-8"
        if encoding in ("gb2312", "GBK", "gbk") :
            encoding = "gbk"
        try:
            return content.decode(encoding, "ignore")
        except (LookupError, TypeError):
            return content.decode("utf-8", "ignore")
