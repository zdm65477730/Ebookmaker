# -*- coding: utf-8 -*-
"""域名级限速与反爬冷却。

- 每域名令牌桶，控制请求速率
- 命中封禁特征（HTTP 403/429/503 或验证码页）时对该域名全局冷却
"""

import re
import threading
import time
from urllib.parse import urlparse

from .log import get_logger

log = get_logger(__name__)

# 常见反爬/验证页面特征。注意：只在“短页”时才用这些关键词判封——
# 真实验证页通常只有几百到几千字节，而笔趣阁系章节页内嵌的防抓 JS/文案
# 会命中同样关键词（长正文），对长页命中属误报。
BLOCK_PATTERNS = re.compile(
    r"人机验证|安全验证|访问验证|滑动验证|点击按钮进行验证|请输入验证码|"
    r"检查浏览器|Just a moment|cloudflare|Access Denied|403 Forbidden|百度安全验证",
    re.I,
)
# 页体超过此长度基本可判定为正常内容页（验证码/拦截页不会这么长）
BLOCK_PAGE_MAX_LEN = 4096
BLOCK_STATUS = (403, 407, 425, 429, 503)


def url_host(url: str) -> str:
    return urlparse(url).netloc.lower()


class DomainLimiter:
    """令牌桶 + 冷却 + **AIMD 自适应速率**（拥塞控制思路，开源爬虫限速器通用做法）：

    - 命中封禁（429/403/验证页/正文为空）：当前速率乘性减半，冷却时长按连续命中次数
      递增（首次短、屡犯加长，上限 cooldown_on_block×2）；
    - 正常成功：每累计 succeed_after 个成功请求，速率加性回升 30%，直至配置上限。
    这样默认就可以激进（高并发高上限），超限时自动收敛，不需要手动调 rate。
    所有方法线程安全。
    """

    def __init__(self, rate_per_sec: float = 5.0, burst: int = 5,
                 cooldown_on_block: float = 20.0, min_rate: float = 0.3,
                 succeed_after: int = 16):
        self.max_rate = max(0.05, float(rate_per_sec))
        self.min_rate = min(float(min_rate), self.max_rate)
        self.rate = self.max_rate          # 当前自适应速率
        # 安全上限：每次撞墙后压到“撞墙前速率×0.9”，回升不再越过已证明不安全的区域
        self.capacity = self.max_rate
        self.burst = max(1, int(burst))
        self.cooldown = float(cooldown_on_block)
        self.succeed_after = max(4, int(succeed_after))
        self._lock = threading.Lock()
        # host -> [tokens, last_refill_ts, cooldown_deadline, strikes]
        self._buckets = {}
        self._ok_count = 0

    def _bucket(self, host):
        b = self._buckets.get(host)
        if b is None:
            b = [float(self.burst), time.monotonic(), 0.0, 0]
            self._buckets[host] = b
        return b

    def acquire(self, url: str):
        """阻塞直到允许向 url 所属域名发起下一次请求。"""
        host = url_host(url)
        while True:
            with self._lock:
                now = time.monotonic()
                b = self._bucket(host)
                # 冷却期
                if b[2] > now:
                    wait = b[2] - now
                else:
                    b[0] = min(self.burst, b[0] + (now - b[1]) * self.rate)
                    b[1] = now
                    if b[0] >= 1.0:
                        b[0] -= 1.0
                        return
                    wait = (1.0 - b[0]) / self.rate
            time.sleep(min(wait, 1.0))  # 细粒度轮询，冷却/补词后及时恢复

    def penalize(self, url: str, seconds: float = None):
        """命中封禁：降速（乘性）+ 递增冷却；seconds 显式给定（如 Retry-After）时优先。

        去重：冷却窗口内的重复命中不叠加降速（一次 429 风暴多线程同时撞回，
        速率只应减半一次）；显式 Retry-After 也参与去重，只用于延长窗口。
        降速与递增冷却只发生在窗口过期后的首次独立惩罚。"""
        host = url_host(url)
        now = time.monotonic()
        with self._lock:
            b = self._bucket(host)
            if b[2] > now:
                # 同一惩罚窗口内的重复命中：不叠加乘性降速/strikes
                if seconds is not None and now + seconds > b[2]:
                    b[2] = now + seconds      # 仅按站点要求延长冷却
                return
            b[3] += 1
            strikes = b[3]
            pre = self.rate
            # 记住本次撞墙的位置：后续回升天花板压到其 90%
            self.capacity = max(self.min_rate, min(self.capacity, pre * 0.9))
            self.rate = max(self.min_rate, self.rate / 2.0)
            if seconds is None:
                seconds = min(self.cooldown * 2, 2.0 * (2 ** (strikes - 1)))
            deadline = now + seconds
            if deadline > b[2]:
                b[2] = deadline
            rate_now = self.rate
        log.warning("域名 %s 触发反爬（第%d次），自适应降速至 %.1f 请求/秒，冷却 %.0fs",
                    host, strikes, rate_now, seconds)

    def succeed(self, url: str):
        """一次正常成功：每累计 succeed_after 次成功回升速率 30% 并清空连犯计数。

        注意：连犯计数（strikes）不随单次成功清零，否则冷却递增机制失效（永远停在首次的短冷却）。"""
        host = url_host(url)
        with self._lock:
            self._ok_count += 1
            if self._ok_count % self.succeed_after == 0:
                b = self._buckets.get(host)
                if b is not None:
                    b[3] = 0
                # 回升受安全上限约束，不再反复越限撞墙
                if self.rate < self.capacity:
                    self.rate = min(self.capacity, self.rate * 1.3)

    @staticmethod
    def is_blocked_body(html_text: str) -> bool:
        """空页或“短页 + 验证特征”才判定被封；长正文命中关键词视为页面内嵌防抓文案，不误判。"""
        if not html_text:
            return True
        if len(html_text) > BLOCK_PAGE_MAX_LEN:
            return False
        return bool(BLOCK_PATTERNS.search(html_text))
