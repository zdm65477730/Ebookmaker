# -*- coding: utf-8 -*-
"""章节下载调度：ThreadPoolExecutor + 断点续爬 + 失败补爬 + 质量检查。

对应方案：
- 不再“每章一个线程”（5000+ 章会创建 5000+ 线程），改为固定线程池
- 已存在且 status=ok 的章节缓存直接跳过（断点续爬）
- 首轮失败/可疑章节进入重试队列，多轮低速率补爬
- 全部完成后执行跨章节广告行统计（cleaner.find_junk_lines）并落盘 junk_lines.json
"""

import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from .cleaner import Cleaner
from .config import AppConfig
from .http_client import FetchError, HttpClient
from .log import get_logger, set_progress_hooks
from .models import ChapterData, TocEntry
from .proxy import ProxyPool
from .ratelimit import DomainLimiter
from .sites.base import SiteAdapter, find_next_page_url
from .store import BookStore

log = get_logger(__name__)


def _fmt_eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return "{}:{:02d}".format(seconds // 60, seconds % 60)


class Progress:
    """实时进度：TTY 下单行进度条（含速率/ETA），非 TTY 退回定期日志。

    与日志共存：向 log 模块注册 clear/redraw 钩子，每条日志输出前擦除
    进度行、输出后重绘（tqdm 同类做法），保证进度条永远只占最后一行；
    所有 stdout 写入由单锁串行，避免多线程交错撕裂输出。"""

    WIDTH = 28
    LINE_LEN = 96  # 擦行宽度（覆盖进度行最大长度）

    def __init__(self, total: int):
        self._counter_lock = threading.Lock()
        self._io_lock = threading.Lock()
        self.reset(total)
        set_progress_hooks(self.clear_line, self.redraw)

    def reset(self, total: int):
        self.total = max(1, int(total))
        self.done = 0
        self.t0 = time.monotonic()
        self._last_draw = 0.0
        self._tty = getattr(sys.stdout, "isatty", lambda: False)()

    def bump(self, n: int = 1):
        # 多线程并发计数，加锁避免 done += n 非原子导致丢更新
        with self._counter_lock:
            self.done += n
            current = self.done
        if not self._tty:
            if current % 50 == 0 or current >= self.total:
                log.info("进度: %d/%d (%.1f%%)", current, self.total,
                         100.0 * current / self.total)
            return
        now = time.monotonic()
        if now - self._last_draw >= 0.2 or current >= self.total:
            # 完成时必须落画，不受节流影响
            self._draw(now, current, force=current >= self.total)

    def _format_line(self, now: float, done: int) -> str:
        elapsed = max(1e-6, now - self.t0)
        rate = done / elapsed
        eta = (self.total - done) / rate if rate > 0 else 0
        filled = int(self.WIDTH * min(done, self.total) / self.total)
        bar = "█" * filled + "░" * (self.WIDTH - filled)
        return "下载 {} {:>5.1f}% {:>4}/{:<4} {:.1f}章/秒 ETA {}".format(
            bar, 100.0 * done / self.total, done, self.total, rate, _fmt_eta(eta))

    def _draw(self, now: float, done: int, force: bool = False):
        with self._io_lock:
            if not force and now - self._last_draw < 0.05:
                return
            self._last_draw = now
            sys.stdout.write("\r" + self._format_line(now, done))
            sys.stdout.flush()

    def clear_line(self):
        """日志前钩子：擦掉当前进度行。"""
        if not self._tty:
            return
        with self._io_lock:
            sys.stdout.write("\r" + " " * self.LINE_LEN + "\r")
            sys.stdout.flush()

    def redraw(self):
        """日志后钩子：重绘进度行。"""
        if not self._tty:
            return
        with self._counter_lock:
            done = self.done
        self._draw(time.monotonic(), done, force=True)

    def finish(self):
        if not self._tty:
            return
        set_progress_hooks(clear=None, redraw=None)
        with self._io_lock:
            sys.stdout.write("\n")
            sys.stdout.flush()


class Crawler:
    def __init__(self, cfg: AppConfig, store: BookStore, site: SiteAdapter,
                 http: HttpClient, cleaner: Cleaner,
                 proxy_pool: Optional[ProxyPool] = None,
                 limiter: Optional[DomainLimiter] = None):
        self.cfg = cfg
        self.store = store
        self.site = site
        self.http = http
        self.cleaner = cleaner
        self.proxy_pool = proxy_pool
        self.limiter = limiter
        self._done_lock = threading.Lock()
        self.progress = None

    # ---------- 书籍信息 ----------
    def fetch_book_info(self, book_url: str) -> Tuple["MetaAndToc", bool]:
        """抓取目录页，落盘 meta/toc，并下载封面。"""
        html = self.http.get(book_url).text
        meta = self.site.parse_meta(html, book_url)
        toc = self.site.parse_toc(html, book_url)
        ok = bool(toc)
        if not ok:
            log.error("目录解析结果为空，请检查站点适配器是否匹配该站点: %s", book_url)
        meta.source_url = book_url
        meta.publisher = self.cfg.epub.publisher
        meta.rights = self.cfg.epub.rights
        meta.language = self.cfg.epub.language
        self.store.save_meta(meta)
        self.store.save_toc(toc)
        if ok and meta.cover_url:
            self._fetch_cover(meta, book_url)
        return MetaAndToc(meta, toc), ok

    def _fetch_cover(self, meta, book_url: str):
        url = urljoin(book_url, meta.cover_url) if meta.cover_url.startswith("/") else meta.cover_url
        try:
            resp = self.http.get(url, referer=book_url, stream=True, as_text=False)
        except FetchError as e:
            log.warning("封面下载失败: %s", e)
            return
        ext = "png" if "png" in (resp.content_type or "") else "jpg"
        path = self.store.save_cover(resp.content, ext)
        log.info("封面已保存: %s", path)

    # ---------- 章节 ----------
    def crawl_chapters(self, toc: List[TocEntry], book_url: str, force: bool = False) -> List[int]:
        """并发抓取全部章节，返回最终仍失败/可疑的目录索引（1 起）。"""
        pending = []
        for i, entry in enumerate(toc, start=1):
            if not force and self.store.has_valid_chapter(i):
                continue
            pending.append((i, entry))
        log.info("共 %d 章，待抓取 %d 章（线程数 %d，代理 %s）",
                 len(toc), len(pending), self.cfg.fetch.threads,
                 "开启" if (self.proxy_pool and self.proxy_pool.enabled()) else "关闭")
        self.progress = Progress(len(toc))
        self.progress.bump(len(toc) - len(pending))  # 已缓存章节直接计入进度

        failed = self._run_pass(pending, book_url, workers=self.cfg.fetch.threads)
        self.progress.finish()

        retry_round = 0
        while failed and retry_round < 3:
            retry_round += 1
            log.info("第 %d 轮补爬 %d 章...", retry_round, len(failed))
            time.sleep(min(30, 5 * retry_round))
            self.progress = Progress(len(failed))
            retry_items = [(i, toc[i - 1]) for i in failed]
            failed = self._run_pass(retry_items, book_url,
                                    workers=max(1, self.cfg.fetch.threads // (2 ** retry_round)))
            self.progress.finish()

        if failed:
            log.warning("仍有 %d 章获取失败/可疑: %s", len(failed), failed[:20])
        else:
            log.info("全部章节抓取完成")

        # 全局广告行统计（两阶段清洗的第一阶段产物）
        self.scan_junk_lines()
        return failed

    def _run_pass(self, items: List[Tuple[int, TocEntry]], book_url: str, workers: int) -> List[int]:
        """执行一轮抓取，返回失败的章节 index 列表。"""
        failed: List[int] = []
        if not items:
            return failed
        max_inflight = workers * 2
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dl") as ex:
            futures = {}
            it = iter(items)
            for idx, entry in it:
                futures[ex.submit(self._fetch_one, idx, entry, book_url)] = idx
                if len(futures) >= max_inflight:
                    break
            while futures:
                finished, _ = wait(list(futures), return_when=FIRST_COMPLETED)
                for fu in finished:
                    idx = futures.pop(fu)
                    try:
                        if not fu.result():
                            failed.append(idx)
                    except Exception as e:  # 防御：任务内已捕获，此处作最后兜底
                        log.error("章节 %d 任务异常: %s", idx, e)
                        failed.append(idx)
                    nxt = next(it, None)
                    if nxt is not None:
                        nidx, nentry = nxt
                        futures[ex.submit(self._fetch_one, nidx, nentry, book_url)] = nidx
        failed.sort()
        return failed

    def _fetch_one(self, index: int, entry: TocEntry, book_url: str) -> bool:
        """抓取+净化+落盘单章。成功(含可疑落盘)返回 True。"""
        ch_url = self.site.chapter_url(book_url, entry.href)
        try:
            html = self.http.get(ch_url, referer=book_url).text
        except FetchError as e:
            log.warning("章节抓取失败 [%d] %s: %s", index, entry.title, e)
            self._bump()
            return False
        raw_lines = self._extract_full_chapter(html, ch_url, book_url)
        # 真正的封禁/改版信号：HTTP 200 但抽不出正文（验证码长页几乎不存在，
        # 而正文抽取为空一定是异常）——此时才对域名冷却并排入补爬
        if not raw_lines or sum(len(l) for l in raw_lines) < 30:
            log.warning("章节正文抽取为空 [%d] %s，疑似反爬/改版，冷却后补爬", index, entry.title)
            if self.limiter:
                self.limiter.penalize(ch_url)
            self._bump()
            return False
        paragraphs = self.cleaner.clean_paragraphs(raw_lines, chapter_index=index, title=entry.title)
        status, problems = self.cleaner.check_quality(paragraphs)
        chapter = ChapterData(index=index, title=entry.title, url=ch_url,
                              paragraphs=paragraphs, status=status, problems=problems)
        if status != "ok":
            log.warning("章节质量可疑 [%d] %s: %s（稍后补爬）", index, entry.title, "; ".join(problems))
            self._bump()
            return False
        self.store.save_chapter(chapter)
        self._bump()
        return True

    def _bump(self):
        if self.progress is not None:
            self.progress.bump()

    def _extract_full_chapter(self, html: str, ch_url: str, book_url: str) -> List[str]:
        """抽取单章正文；自动探测并拼接同章节分页（xxx_2.html 等），
        带重复内容守护与页数上限。"""
        lines = list(self.site.parse_chapter(html, ch_url))
        visited = {ch_url}
        max_pages = max(1, self.cfg.fetch.max_next_pages)
        page_html = html
        page_url = ch_url
        for _ in range(max_pages - 1):
            nxt = find_next_page_url(page_html, page_url)
            if not nxt or nxt in visited:
                break
            try:
                page_html = self.http.get(nxt, referer=page_url).text
            except FetchError:
                break
            visited.add(nxt)
            page_url = nxt
            more = self.site.parse_chapter(page_html, nxt)
            if not more:
                break
            # 重复守护：新一页与已有尾部大量重合则判定循环/串章，停止拼接
            tail_set = set(lines[-30:])
            dup = sum(1 for l in more[:30] if l.strip() in tail_set)
            if dup > len(more[:30]) * 0.5:
                break
            lines.extend(more)
        return lines

    # ---------- 全局广告行扫描 ----------
    def scan_junk_lines(self) -> List[str]:
        chapters = [(ch.index, ch.paragraphs) for ch in self.store.iter_chapters()]
        junk = self.cleaner.find_junk_lines(chapters)
        if junk:
            self.store.save_junk_lines(sorted(junk))
        return sorted(junk)


class MetaAndToc:
    def __init__(self, meta, toc):
        self.meta = meta
        self.toc = toc
