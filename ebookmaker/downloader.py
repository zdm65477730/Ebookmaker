# -*- coding: utf-8 -*-
"""章节下载调度：ThreadPoolExecutor + 断点续爬 + 失败补爬 + 质量检查。

对应方案：
- 不再“每章一个线程”（5000+ 章会创建 5000+ 线程），改为固定线程池
- 已存在且 status=ok 的章节缓存直接跳过（断点续爬）
- 首轮失败/可疑章节进入重试队列，多轮低速率补爬
- 全部完成后执行跨章节广告行统计（cleaner.find_junk_lines）并落盘 junk_lines.json
"""

import sys
import re
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


def _pua_ratio(lines) -> float:
    """文本中 PUA 码位占比（字体加密站判定，此类页面不可用 trafilatura 对比）。"""
    from .cleaner import PUA_RE
    text = "".join(lines)
    if not text:
        return 0.0
    return len(PUA_RE.findall(text)) / len(text)


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
        # 目录结构变更守护：源站更新/解析规则调整后章节数或题名变化会使
        # 旧缓存的 index 错位，章名不符的缓存一律作废重抓，杜绝“章名A正文B”
        stale = 0
        for i, entry in enumerate(toc, start=1):
            ch = self.store.load_chapter(i)
            if ch is not None and ch.title.strip() != entry.title.strip():
                self.store.delete_chapter(i)
                stale += 1
        if stale:
            log.info("目录结构变更：%d 个旧章节缓存章名不再匹配，已作废重抓", stale)
        # 孤儿缓存（超出目录长度：目录变短/插洞 shift 残留）一并清理，
        # 否则 build 按文件扫描会多出重复章
        orphan = self.store.delete_chapters_beyond(len(toc))
        if orphan:
            log.info("清理 %d 个超出目录长度的孤儿章节缓存", orphan)
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

    # ---------- 跨源补全 ----------
    def repair_from_sources(self, toc: List[TocEntry], book_url: str,
                            alt_sources: List[str]) -> int:
        """用同书其他源补齐缺章/可疑章/过短章，返回补全成功的章数。

        不合格判定：无缓存、status!=ok、或字数 < max(100, 全书中位数*0.3)。
        对齐：两源章节数相同按位置，否则按归一章名匹配（bookindex.norm_title）。
        采纳：补全章 status=ok、>=100 字，且比现状多 20% 以上（原为缺/坏则直接采纳）；
        否则回写原版本，主源成果不被劣化。复用 _fetch_one 全套质量链路
        （分页拼接/双抽取/置信闸门），仅站点换成候选源。
        """
        old = {}
        bad = []
        ok_lens = []
        for i in range(1, len(toc) + 1):
            ch = self.store.load_chapter(i)
            old[i] = ch
            if ch is None or ch.status != "ok":
                bad.append(i)
            else:
                ok_lens.append(ch.text_length())
        if not bad and not ok_lens:
            return 0
        med = sorted(ok_lens)[len(ok_lens) // 2] if ok_lens else 0
        floor = max(100, int(med * 0.3))
        bad = sorted(set(bad) | {i for i, c in old.items()
                                 if c is not None and c.status == "ok"
                                 and c.text_length() < floor})
        if bad:
            log.info("待跨源补全章节 %d 个（空/可疑/<%d 字），候选源 %d 个",
                     len(bad), floor, len(alt_sources))
        # bad 为空时不提前返回：仍用书目索引的缓存目录检查“主源目录缺编号章”
        # （源站缺页），零联网成本；在线拉目录只在有坏章时进行。

        repaired = 0
        done = set()
        from . import bookindex
        from .sites.base import _title_number, _href_number
        # 主源已占编号集：标题序号与 URL 尾号**双取**——笔误救援条目
        # （336.html 标题写“第366章”）按尾号占位，若只取标题序号会把
        # 真编号当成空洞重复插入
        tnums: set = set()
        for e in toc:
            n1 = _title_number(e.title)
            n2 = _href_number(e.href)
            if n1 is not None:
                tnums.add(n1)
            if n2 is not None and n2 < 100000:   # 随机长 ID 不算章号
                tnums.add(n2)
        toc_grew = False
        for alt_url in alt_sources:
            todo = [i for i in bad if i not in done]
            try:
                alt_site = self._resolve_alt_site(alt_url)

                def _online_toc():
                    h = self.http.get(alt_url).text
                    t = alt_site.parse_toc(h, alt_url)
                    # 补全源同样需要目录分页合并（否则多页目录的源只能对齐首页章节）
                    if t:
                        from .sites.base import (collect_series_pages,
                                                 normalize_toc)
                        try:
                            extra = collect_series_pages(
                                h, alt_url,
                                lambda pu: self.http.get(pu, referer=alt_url).text)
                        except Exception:  # noqa: BLE001
                            extra = []
                        if extra:
                            ents = list(t)
                            for _, ph in extra:
                                ents.extend(alt_site.parse_toc(ph, alt_url))
                            t = normalize_toc(ents)
                    return t

                alt_toc = None
                if todo:
                    alt_toc = _online_toc()
                else:
                    # 无坏章：优先用书目索引的缓存目录零联网查漏洞；
                    # 显式新源（--source 首次）则在线拉一次并登记，后续复用
                    alt_toc = bookindex.source_toc(self.cfg.workdir, alt_url)
                    if not alt_toc:
                        alt_toc = _online_toc()
                        if alt_toc:
                            m = self.store.load_meta()
                            if m and m.title:
                                bookindex.record(self.cfg.workdir, m.title,
                                                 alt_url, alt_toc)
                if not alt_toc:
                    if todo:
                        log.warning("补全源无章节目录: %s", alt_url)
                    continue
                mapping = _align_toc(toc, alt_toc) if todo else {}
                if todo and not mapping:
                    log.warning("补全源目录与本书无法对齐: %s", alt_url)
                    continue
                if todo:
                    log.info("尝试补全源 %s（目录 %d 章，可对齐 %d 章）",
                             alt_url, len(alt_toc), len(mapping))
                sub = Crawler(self.cfg, self.store, alt_site, self.http,
                              Cleaner(self.cfg.cleaner), self.proxy_pool,
                              self.limiter)
                for i in todo:
                    entry = mapping.get(i)
                    if entry is None:
                        continue
                    try:
                        sub._fetch_one(i, entry, alt_url)
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:  # noqa: BLE001
                        log.warning("  第%d章补全失败: %s", i, e)
                        continue
                    new = self.store.load_chapter(i)
                    prev = old[i]
                    prev_len = prev.text_length() if prev else 0
                    new_len = new.text_length() if new else 0
                    better = (new is not None and new.status == "ok"
                              and new_len >= 100
                              and (prev is None or prev.status != "ok"
                                   or new_len > prev_len * 1.2))
                    if better:
                        done.add(i)
                        repaired += 1
                        log.info("  第%d章已从其他源补齐: %d字 -> %d字 (%s)",
                                 i, prev_len, new_len, alt_site.name)
                    elif prev is not None:
                        # 未采纳则无条件恢复主源版本（_fetch_one 可能已覆盖落盘）
                        self.store.save_chapter(prev)

                # 编号空洞补抓：候选源有、主源目录缺的章号（源站缺页）
                # → 按编号顺序插入目录并从候选源抓取，缓存平移不错位
                gaps = []
                have_hrefs = {x.href for x in toc}
                for e2 in alt_toc:
                    n2 = _title_number(e2.title)
                    if n2 is not None and n2 not in tnums and e2.href not in have_hrefs:
                        gaps.append((n2, e2))
                for n2, e2 in sorted(gaps, reverse=True):
                    if n2 in tnums:
                        continue          # 同章号多个候选时只插第一个成功的
                    pos = next((idx for idx, te in enumerate(toc)
                                if (_title_number(te.title) or n2 + 1) > n2),
                               len(toc))  # 0 基插入位置
                    self.store.shift_chapters(pos + 1, 1)
                    ins = TocEntry(href=e2.href, title=e2.title)
                    toc.insert(pos, ins)
                    try:
                        sub._fetch_one(pos + 1, ins, alt_url)
                    except KeyboardInterrupt:
                        raise
                    except Exception:  # noqa: BLE001
                        pass
                    got = self.store.load_chapter(pos + 1)
                    if got is not None and got.status == "ok":
                        tnums.add(n2)
                        toc_grew = True
                        repaired += 1
                        log.info("  第%d章主源目录缺失，已从其他源补插入（总目录 %d 章）",
                                 n2, len(toc))
                    else:
                        # 补抓失败：回滚插入，恢复原状
                        if got is not None:
                            self.store.delete_chapter(pos + 1)
                        self.store.shift_chapters(pos + 2, -1)
                        toc.pop(pos)
                if gaps:
                    log.info("候选源 %s 存在 %d 个主源缺失的编号章", alt_url, len(gaps))
            except KeyboardInterrupt:
                raise
            except Exception as e:  # noqa: BLE001 - 补全是增益，任何失败不影响主流程
                log.warning("补全源不可用 %s: %s", alt_url, e)
        if repaired:
            log.info("跨源补全完成：%d 章", repaired)
        if toc_grew:
            self.store.save_toc(toc)   # 持久化插洞后的目录
        return repaired

    def _resolve_alt_site(self, url: str) -> SiteAdapter:
        """补全源的站点解析：与主流程同源（规则/已学习描述符/generic 兜底）。"""
        from .auto import auto_dir_for, load_learned_site
        from .sites.generic import GenericSite
        from .sites.registry import get_adapter
        site = get_adapter(url, "", extra_rules_dirs=[])
        if self.cfg.auto.enabled and isinstance(site, GenericSite):
            learned = load_learned_site(
                auto_dir_for(self.cfg.workdir, self.cfg.auto.save_dir), url)
            if learned is not None:
                site = learned
        return site

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
        raw_lines, agree, notes = self._extract_full_chapter(
            html, ch_url, book_url, title=entry.title)
        # 真正的封禁/改版信号：HTTP 200 但抽不出正文（验证码长页几乎不存在，
        # 而正文抽取为空一定是异常）——此时才对域名冷却并排入补爬
        if not raw_lines or sum(len(l) for l in raw_lines) < 30:
            log.warning("章节正文抽取为空 [%d] %s，疑似反爬/改版，冷却后补爬", index, entry.title)
            if self.limiter:
                self.limiter.penalize(ch_url)
            # 页面取得到却抽不出正文（源站缺章/锁定）：落盘空章占位，
            # 补爬轮成功会覆盖；避免章节从成品中静默消失
            self.store.save_chapter(ChapterData(index=index, title=entry.title, url=ch_url,
                                                paragraphs=[], status="suspicious",
                                                problems=["正文抽取为空"], confidence=0.0))
            self._bump()
            return False
        paragraphs = self.cleaner.clean_paragraphs(raw_lines, chapter_index=index, title=entry.title)
        status, problems = self.cleaner.check_quality(paragraphs)
        conf, cproblems = self.cleaner.chapter_confidence(paragraphs, title=entry.title)
        problems = problems + [p for p in cproblems if p not in problems]
        # 页级复审残留噪声：封顶临界值以下，驱动补抓重试
        for n in notes:
            if n not in problems:
                problems.append(n)
        if notes:
            conf = min(conf, 0.45)
        # 双抽取器分歧计入置信度（只罚不奖）
        if agree < 0.5:
            conf = min(conf, 0.45)
            problems.append("抽取器分歧({:.0%})".format(agree))
        conf = round(conf, 3)
        if status == "ok" and conf < self.cfg.cleaner.min_confidence:
            status = "suspicious"
            problems.append("低置信({:.2f}<{})".format(conf, self.cfg.cleaner.min_confidence))
        chapter = ChapterData(index=index, title=entry.title, url=ch_url,
                              paragraphs=paragraphs, status=status, problems=problems,
                              confidence=conf)
        if status != "ok":
            log.warning("章节质量可疑 [%d] %s: %s（稍后补爬）", index, entry.title, "; ".join(problems))
            # 同样落盘（suspicious）：补爬轮成功会覆盖；若始终不达标，
            # 成品经 build 占位机制透明呈现而非静默缺章
            self.store.save_chapter(chapter)
            self._bump()
            return False
        self.store.save_chapter(chapter)
        self._bump()
        return True

    def _bump(self):
        if self.progress is not None:
            self.progress.bump()

    def _extract_full_chapter(self, html: str, ch_url: str, book_url: str,
                              title: str = "") -> Tuple[List[str], float, List[str]]:
        """抽取完整章节：逐页定位清洗后拼接，返回 (正文行, 双抽取器一致度, 页审备注)。

        分页发现：序列探针优先 + 同系列链接探测回退；
        一致度 = min(站点路径字数, trafilatura 标尺字数)/max(...)，每页取平均；
        标尺不可用（未装/空白）时记 1.0（中性），只惩罚分歧、不奖励一致；
        页审备注 = 清洗后复审仍 severe 的页 findings（驱动置信闸门与补抓）。"""
        lines: List[str] = []
        notes: List[str] = []
        visited = {ch_url}
        max_pages = max(1, self.cfg.fetch.max_next_pages)
        page_html, page_url = html, ch_url
        prev_html = html
        agree_sum, agree_n = 0.0, 0
        used_oracle_pages = 0
        from .sites.generic import content_oracle_lines
        for _ in range(max_pages):
            site_lines = list(self.site.parse_chapter(page_html, page_url))
            # 双抽取器择优（trafilatura 作标尺，成熟库通用正文抽取）：容器选偏时取更完整一路；
            # 站点路径不显著落后则保留（页尾标记/锚点信息更丰富，交给 clean_page 精修）
            lines_in = site_lines
            try:
                oracle = content_oracle_lines(page_html)
            except Exception:
                oracle = []
            so = sum(len(l) for l in site_lines)
            oo = sum(len(l) for l in oracle)
            # 标尺自身先过审：trafilatura favor_recall 偶尔把侧栏推荐区一并抽出
            # （字数翻倍）——此时切标尺会引噪、计分歧会误杀好章，一律不采
            oracle_ok = bool(oracle) and not self.cleaner.review_page(
                oracle, title=title).severe
            if oracle_ok and so * self.cfg.cleaner.dual_extractor_margin < oo < so * 3 \
                    and _pua_ratio(site_lines) < 0.02:
                lines_in = oracle
            if oracle_ok and site_lines and so and oo:
                agree_sum += min(so, oo) / max(so, oo)
                agree_n += 1
            more, needs_next = self.cleaner.clean_page(lines_in, title=title)
            if not more:
                # 该页无可用正文：已累积内容则判为 JS 渲染页（再探只能抓到侧栏），停止
                if lines:
                    break
            else:
                # 清洗后复审：仍有结构性噪声的页记入页审备注（驱动补抓）
                post = self.cleaner.review_page(more, title)
                if post.severe:
                    notes.append("复审残留: %s" % ";".join(post.findings[:3]))
                # 重复守护（行级精确匹配 + 2-gram 覆盖双重）：
                # 软404 重复页侧栏变化会稀释行级匹配率，2-gram 覆盖能补捕
                tail_set = set(lines[-50:])
                dup_line = sum(1 for l in more[:30] if l in tail_set)
                exist_text = "".join(lines[-50:])
                exist_bigrams = {exist_text[i:i + 2] for i in range(max(0, len(exist_text) - 1))}
                new_text = "".join(more)
                new_bigrams = [new_text[i:i + 2] for i in range(max(0, len(new_text) - 1))]
                dup_gram = (sum(1 for b in new_bigrams if b in exist_bigrams) /
                            max(1, len(new_bigrams))) if new_bigrams else 0.0
                if dup_line > len(more[:30]) * 0.5 or dup_gram > 0.65:
                    break
                lines.extend(more)
            # 分页发现：序列探针优先（严格递增不漏页，需通过归属/幂等校验），
            # 探针断链时回退同系列“下一页”链接探测（兼容任意分页命名形态）
            probed = False
            nxt = None
            if needs_next:
                k = self._page_num(page_url, ch_url) + 1
                cand = self._probe_url(ch_url, k)
                if cand and cand not in visited:
                    nxt, probed = cand, True
                else:
                    link = find_next_page_url(page_html, page_url)
                    if link and link not in visited:
                        nxt = link
            if not nxt:
                break
            try:
                page_html = self.http.get(nxt, referer=page_url).text
            except FetchError:
                if not probed:
                    break
                # 探针 404：用当前页（prev_html）的同系列链接探测再试一次
                link = find_next_page_url(prev_html, page_url)
                if not link or link in visited:
                    break
                try:
                    page_html = self.http.get(link, referer=page_url).text
                except FetchError:
                    break
                nxt = link
                probed = False
            visited.add(nxt)
            if probed and not self._page_belongs(page_html, page_url, title):
                # 探针候选不像本章续页（软404/首页等）：回退同系列链接探测再试
                link = find_next_page_url(prev_html, page_url)
                if not link or link in visited:
                    break
                try:
                    page_html = self.http.get(link, referer=page_url).text
                except FetchError:
                    break
                nxt = link
            page_url = nxt
        agree = (agree_sum / agree_n) if agree_n else 1.0
        return lines, agree, notes

    def _page_belongs(self, page_html: str, page_url: str, title: str) -> bool:
        """探针候选页归属校验（不强求续页重复章名，真实站只在首页带标题）：

        1) 候选页正文行中有剥（N/M）后缀后等于章名的标题行 → 属本章；
        2) 否则看候选页的同系列分页链接（下一页）是否仍在本章文档上：
           软404/首页渲染的目录链接指向其它文档 → 拒；无分页链接 → 接受。
        """
        norm = self.cleaner._normalize(title) if title else ""
        try:
            lines = self.site.parse_chapter(page_html, page_url)
        except Exception:
            lines = []
        if norm:
            for line in lines[:8]:
                if self.cleaner._is_title_line(line, norm):
                    return True
        stem = self._doc_stem(page_url)
        if not stem:
            return True
        for m in re.finditer(r'<a[^>]+href="([^"<>]{1,300})"', page_html):
            absu = urljoin(page_url, m.group(1).strip())
            if absu == page_url:
                continue
            other = self._doc_stem(absu)
            if other and re.search(r"[_\-]?\d*$", other) and other.rstrip("_-") == stem.rstrip("_-") \
                    and other != stem:
                return True            # 候选页分页链仍在本章文档上
        nxt = find_next_page_url(page_html, page_url)
        if nxt is None:
            # 无标题/无链接信号：描述符站点看正文容器存在性（软404目录页会被拒）；
            # 纯启发式站点无法进一步区分，宽容接受，由重复守护/页数上限兜底。
            from .sites.regex_site import RegexSite
            if isinstance(self.site, RegexSite):
                return self.site.has_content_container(page_html)
            return True
        return self._doc_stem(nxt).rstrip("_-") == stem.rstrip("_-")

    @staticmethod
    def _doc_stem(url: str) -> str:
        """章节文档主干（去分页后缀）：/a/2_3.html 与 /a/2.html → /a/2.html。"""
        from urllib.parse import urlsplit, urlunsplit
        p = urlsplit(url)
        path = p.path
        m = re.match(r"^(.*?)\.(html?|htm)$", path, re.I)
        if m:
            path = m.group(1)
        path = re.sub(r"[_\-]\d+$", "", path)          # xxx_2 -> xxx（目录式尾段是文档ID，不剥）
        return urlunsplit((p.scheme, p.netloc, path, "", ""))

    @staticmethod
    def _page_num(url: str, base_url: str) -> int:
        """当前页在章节内的序号（base=1，xxx_3.html=3，/base/3/=3）。"""
        import re
        from urllib.parse import urlparse
        bp = urlparse(base_url).path.rstrip("/")
        up = urlparse(url).path.rstrip("/")
        if up == bp:
            return 1
        m = re.search(r"[_\-](\d+)\.?h?t?m?l?$", up)
        if m:
            return int(m.group(1))
        if up.startswith(bp + "/"):
            m = re.search(r"/(\d+)$", up[len(bp):])
            if m:
                return int(m.group(1))
        return 1

    @staticmethod
    def _probe_url(url: str, k: int) -> Optional[str]:
        """生成第 k 页候选 URL：xxx.html→xxx_k.html；/base/→/base/k/；/base/2/→/base/k/。"""
        import re
        from urllib.parse import urlsplit, urlunsplit
        p = urlsplit(url)
        path = p.path
        if path.endswith(".html") or path.endswith(".htm"):
            stem = re.sub(r"[_\-]\d+$", "", path[:-5] if path.endswith(".html") else path[:-4])
            ext = ".html" if path.endswith(".html") else ".htm"
            path = "{}_{}{}".format(stem, k, ext)
        elif path.endswith("/"):
            base = path[:-1]                      # 去尾斜杠
            base = re.sub(r"[_\-]\d+$", "", base)  # 只剥 _N/-N 页号；裸尾段可能是文档ID不敢剥
            path = base + "/{}/".format(k)         # /4/ -> /4/2/；/4_2/ -> /4/3/
        else:
            return None
        return urlunsplit((p.scheme, p.netloc, path, "", ""))

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


def _align_toc(toc: List[TocEntry],
               alt_toc: List[TocEntry]) -> dict:
    """主源 1 起索引 -> 候选源条目。章节数相同按位置对齐，否则按归一章名。"""
    from . import bookindex
    if len(alt_toc) == len(toc):
        return {i + 1: alt_toc[i] for i in range(len(toc))}
    by_title = {}
    for e in alt_toc:
        by_title.setdefault(bookindex.norm_title(e.title), e)
    out = {}
    for i, e in enumerate(toc):
        m = by_title.get(bookindex.norm_title(e.title))
        if m is not None:
            out[i + 1] = m
    return out
