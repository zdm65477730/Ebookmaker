# -*- coding: utf-8 -*-
"""代理池：多来源采集、并发校验、成功率评分、失效自动拉黑与补充。

source:
- none   直连（不使用代理）
- list   从公开免费代理列表页采集（内置 kuaidaili / jiangxianli / 89ip 源）
- api    自定义接口，返回纯文本 ip:port 列表
- file   本地文件，每行一个 ip:port
"""

import re
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import requests

from .config import ProxyConfig
from .log import get_logger

log = get_logger(__name__)

IP_PORT_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})")

# 免费代理列表源（内置通用特征，沿用旧版 daili_* 配置验证过的三个站点）
LIST_PROVIDERS: Dict[str, dict] = {
    "kuaidaili": {
        "url": "https://www.kuaidaili.com/free/inha/{page}/",
        "host": "www.kuaidaili.com",
        "pattern": r"<td data-title=\"IP\">(\d+\.\d+\.\d+\.\d+)</td>[\s\S]*?<td data-title=\"PORT\">(\d+)</td>",
    },
    "jiangxianli": {
        "url": "https://ip.jiangxianli.com/?page={page}",
        "host": "ip.jiangxianli.com",
        "pattern": r"data-url=\"http://(\d+\.\d+\.\d+\.\d+):(\d+)\"",
    },
    "89ip": {
        "url": "https://www.89ip.cn/index_{page}.html",
        "host": "www.89ip.cn",
        "pattern": r"<td>[\s]+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})[\s]+</td>[\s]+<td>[\s]+(\d{2,5})[\s]+</td>",
    },
}


class ProxyPool:
    """线程安全的代理池。pick() 返回 requests 风格 proxies dict 或 None。"""

    def __init__(self, cfg: ProxyConfig, bootstrap_get=None):
        self.cfg = cfg
        # bootstrap_get(url) -> text：用于抓列表页的无代理取回器，由上层注入
        self._bootstrap_get = bootstrap_get
        self._lock = threading.Lock()
        # "ip:port" -> {"fails": int, "oks": int, "banned": bool}
        self._entries: Dict[str, dict] = {}
        self._last_refill = 0.0

    # ---------- 对外接口 ----------
    def enabled(self) -> bool:
        return self.cfg.source != "none"

    def pick(self) -> Optional[dict]:
        """按成功率加权随机取一个可用代理；池空或全部拉黑时返回 None（直连降级）。"""
        if not self.enabled():
            return None
        self.maybe_refill()
        with self._lock:
            alive = [ip for ip, e in self._entries.items() if not e["banned"]]
        if not alive:
            return None
        weights = []
        with self._lock:
            for ip in alive:
                e = self._entries[ip]
                total = e["oks"] + e["fails"]
                score = (e["oks"] + 1) / (total + 2)  # Laplace 平滑
                weights.append(max(0.05, score))
        chosen = random.choices(alive, weights=weights, k=1)[0]
        return {"http": "http://" + chosen, "https": "http://" + chosen}

    def report_ok(self, proxy: Optional[dict]):
        ip = self._ip_of(proxy)
        if not ip:
            return
        with self._lock:
            e = self._entries.get(ip)
            if e:
                e["oks"] += 1
                e["fails"] = 0

    def report_fail(self, proxy: Optional[dict]):
        ip = self._ip_of(proxy)
        if not ip:
            return
        with self._lock:
            e = self._entries.get(ip)
            if e:
                e["fails"] += 1
                if e["fails"] >= self.cfg.fail_limit:
                    e["banned"] = True
                    log.debug("代理 %s 连续失败，已拉黑", ip)

    @staticmethod
    def _ip_of(proxy: Optional[dict]) -> Optional[str]:
        if not proxy:
            return None
        url = proxy.get("http") or proxy.get("https") or ""
        return url.partition("://")[2] or None

    def size(self) -> int:
        with self._lock:
            return sum(1 for e in self._entries.values() if not e["banned"])

    # ---------- 采集与校验 ----------
    def maybe_refill(self):
        """存活数低于水位时自动补充（带节流，避免频繁抓列表站）。"""
        if not self.enabled():
            return
        now = time.monotonic()
        with self._lock:
            alive = sum(1 for e in self._entries.values() if not e["banned"])
            need = alive < self.cfg.min_alive or (self._last_refill and now - self._last_refill > 600 and alive < self.cfg.max_proxy)
        if need and now - self._last_refill > 30:
            with self._lock:
                self._last_refill = now
            self.refill()

    def refill(self):
        log.info("补充代理池（当前存活 %d）...", self.size())
        candidates = self._collect()
        if not candidates:
            log.warning("未采集到任何代理候选")
            return
        good = self._validate(candidates)
        with self._lock:
            for ip in good:
                if ip not in self._entries:
                    self._entries[ip] = {"fails": 0, "oks": 0, "banned": False}
            # 控制池规模
            alive = [ip for ip, e in self._entries.items() if not e["banned"]]
            if len(alive) > self.cfg.max_proxy:
                for ip in alive[self.cfg.max_proxy:]:
                    del self._entries[ip]
        log.info("代理池补充完成，存活 %d", self.size())

    def _collect(self) -> List[str]:
        source = self.cfg.source
        found = set()
        try:
            if source == "list":
                found.update(self._collect_list())
            elif source == "api" and self.cfg.api_url:
                text = self._fetch_plain(self.cfg.api_url)
                found.update(self._parse_ip_ports(text))
            elif source == "file" and self.cfg.file_path:
                with open(self.cfg.file_path, "r", encoding="utf-8", errors="ignore") as fp:
                    found.update(self._parse_ip_ports(fp.read()))
        except Exception as e:  # 采集失败不致命，退回现有池
            log.warning("代理采集失败: %s", e)
        return sorted(found)

    def _collect_list(self) -> List[str]:
        found = set()
        for name in self.cfg.list_providers:
            provider = LIST_PROVIDERS.get(name)
            if not provider:
                log.warning("未知代理列表源: %s", name)
                continue
            for page in range(1, max(1, self.cfg.list_pages) + 1):
                url = provider["url"].format(page=page)
                try:
                    text = self._fetch_plain(url)
                except Exception as e:
                    log.debug("抓取代理列表页失败 %s: %s", url, e)
                    break
                for m in re.findall(provider["pattern"], text):
                    ip, port = m if isinstance(m, (tuple, list)) else (m, "")
                    if port:
                        found.add("{}:{}".format(ip, port))
                time.sleep(random.uniform(0.5, 1.5))
        return sorted(found)

    def _fetch_plain(self, url: str) -> str:
        if self._bootstrap_get is None:
            resp = requests.get(url, timeout=(10, 15), verify=False)
            resp.raise_for_status()
            return resp.text
        return self._bootstrap_get(url)

    @staticmethod
    def _parse_ip_ports(text: str) -> List[str]:
        return ["{}:{}".format(ip, port) for ip, port in IP_PORT_RE.findall(text)]

    def _validate(self, candidates: List[str]) -> List[str]:
        """并发校验代理可用性（能匿名访问 check_url）。"""
        good = []
        if not candidates:
            return good
        check_url = self.cfg.check_url

        def _check(ip: str) -> Optional[str]:
            proxies = {"http": "http://" + ip, "https": "http://" + ip}
            try:
                r = requests.get(check_url, proxies=proxies,
                                 timeout=(self.cfg.check_timeout, self.cfg.check_timeout),
                                 headers={"user-agent": "curl/8.0"})
                if r.status_code == 200:
                    return ip
            except requests.RequestException:
                pass
            return None

        workers = min(32, max(4, len(candidates)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="proxycheck") as ex:
            futures = [ex.submit(_check, ip) for ip in candidates]
            for fu in as_completed(futures):
                ip = fu.result()
                if ip:
                    good.append(ip)
        log.info("代理校验：%d/%d 可用", len(good), len(candidates))
        return good
