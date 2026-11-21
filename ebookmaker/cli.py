# -*- coding: utf-8 -*-
"""命令行入口：run / crawl / build / convert。"""

import argparse
import os
import shutil
import sys
from typing import List, Optional

from .builders.convert import convert_epub
from .builders.epub import build_epub
from .auto import (auto_dir_for, learn_font_map, learn_site, load_learned_site,
                   pua_ratio, save_descriptor)
from . import bookindex
from .cleaner import Cleaner
from .config import AppConfig, load_config
from .downloader import Crawler
from .http_client import CloudflareChallengeError, FetchError, HttpClient
from .log import get_logger, setup_logging
from .proxy import ProxyPool
from .ratelimit import DomainLimiter
from .sites.base import SiteAdapter, collect_series_pages, find_next_page_url, normalize_toc
from .sites.generic import GenericSite
from .sites.regex_site import RegexSite
from .sites.registry import get_adapter, list_adapter_names
from .store import BookStore, safe_dirname

log = get_logger(__name__)


def _split_formats(text: str) -> List[str]:
    return [f.strip().lower() for f in text.split(",") if f.strip()]


_SUBCOMMANDS = {"crawl", "run", "build", "convert", "clean", "verify"}


def normalize_argv(argv: List[str]) -> List[str]:
    """一步式用法糖：首个参数直接是书籍 URL 时，等价于 `run --url <URL>`。

    其余写法（显式子命令/全局选项开头）保持不变，单步命令不受影响。
    """
    argv = list(argv)
    if (argv and argv[0] not in _SUBCOMMANDS and not argv[0].startswith("-")
            and "://" in argv[0]):
        return ["run", "--url", argv[0]] + argv[1:]
    return argv


def _apply_overrides(cfg: AppConfig, args) -> AppConfig:
    if getattr(args, "threads", None):
        cfg.fetch.threads = args.threads
    if getattr(args, "cookie", None):
        cfg.fetch.cookie = args.cookie
    if getattr(args, "workdir", None):
        cfg.workdir = args.workdir
    if getattr(args, "formats", None):
        cfg.formats = _split_formats(args.formats)
    src = getattr(args, "proxy_source", None)
    if src:
        cfg.proxy.source = src
    if getattr(args, "proxy_api", None):
        cfg.proxy.source = "api"
        cfg.proxy.api_url = args.proxy_api
    if getattr(args, "proxy_file", None):
        cfg.proxy.source = "file"
        cfg.proxy.file_path = args.proxy_file
    return cfg


def _make_limiter(cfg: AppConfig) -> DomainLimiter:
    return DomainLimiter(cfg.rate.rate_per_sec, cfg.rate.burst, cfg.rate.cooldown_on_block)


def _make_cleaner(cfg: AppConfig, font_map: dict = None) -> Cleaner:
    """净化器无规则文件输入；font_map 仅来自字体自动解密产物。"""
    return Cleaner(cfg.cleaner, font_map=font_map or {})


def _wire_runtime(cfg: AppConfig, limiter: DomainLimiter):
    """构造代理池与主 HTTP 客户端。"""
    proxy_pool = None
    picker = fail_cb = None
    if cfg.proxy.source != "none":
        bootstrap = HttpClient(cfg.fetch, limiter=None)  # 抓代理列表用直连
        proxy_pool = ProxyPool(cfg.proxy, bootstrap_get=lambda u: bootstrap.get(u).text)
        picker = proxy_pool.pick
        fail_cb = proxy_pool.report_fail
    http = HttpClient(cfg.fetch, limiter, picker, fail_cb)
    return proxy_pool, http


def _book_workspace(cfg: AppConfig, title: str) -> BookStore:
    return BookStore(os.path.join(cfg.workdir, safe_dirname(title)))


def _log_book_info(meta, chapter_count: int, cover_ok: bool):
    """抓取书籍信息后输出摘要。"""
    log.info("=============== 书籍信息 ===============")
    log.info("书名：%s", meta.title)
    log.info("作者：%s", meta.author)
    log.info("分类：%s", meta.category or "其他")
    log.info("最后更新：%s", meta.update_time or "未知")
    log.info("章节数：%d", chapter_count)
    log.info("封面：%s", "已下载" if cover_ok else "未获取（将用默认封面）")
    desc = (meta.description or "").strip()
    if desc:
        if len(desc) > 160:
            desc = desc[:160] + "…"
        log.info("简介：%s", desc)
    log.info("========================================")


def cmd_crawl(cfg: AppConfig, url: str, site_name: str, rules_dirs: List[str],
              force: bool,
              sources: Optional[List[str]] = None) -> Optional[BookStore]:
    limiter = _make_limiter(cfg)
    proxy_pool, http = _wire_runtime(cfg, limiter)
    auto_dir = auto_dir_for(cfg.workdir, cfg.auto.save_dir) if cfg.auto.enabled else ""
    site = get_adapter(url, site_name, extra_rules_dirs=list(rules_dirs))

    # 自动适配：未命中任何规则时，优先复用已学习的站点规则
    if cfg.auto.enabled and not site_name and isinstance(site, GenericSite):
        learned = load_learned_site(auto_dir, url) if auto_dir else None
        if learned is not None:
            site = learned

    log.info("抓取书籍信息: %s", url)
    html = http.get(url).text
    probe_meta = site.parse_meta(html, url)
    store = _book_workspace(cfg, probe_meta.title)
    # 续跑：若已有同 URL 的 meta，保留缓存目录
    existing = store.load_meta()
    if existing and existing.source_url and existing.source_url.rstrip("/") == url.rstrip("/") and not force:
        log.info("检测到已有工作区（断点续爬）: %s", store.root)
    toc = site.parse_toc(html, url)

    # 目录分页自动合并（如 /490/651_5/ 的 _1.._N 兄弟页，每页只含部分章节）
    if toc:
        extra = collect_series_pages(html, url, lambda pu: http.get(pu, referer=url).text)
        if extra:
            log.info("检测到目录分页（共 %d 页），合并全部章节...", len(extra) + 1)
            entries = list(toc)
            for _, ph in extra:
                entries.extend(site.parse_toc(ph, url))
            toc = normalize_toc(entries)

    if not toc:
        log.error("目录解析为空，请检查站点适配（可用: %s）", ", ".join(list_adapter_names()))
        return None

    # 自动适配：仍走 generic 时，采样章节学习站点结构并落盘复用
    if cfg.auto.enabled and isinstance(site, GenericSite):
        descriptor = learn_site(http, url, toc, Cleaner(cfg.cleaner), cfg.auto)
        if descriptor:
            try:
                save_descriptor(descriptor, auto_dir)
            except OSError as e:
                log.warning("学习规则保存失败（不影响本次爬取）: %s", e)
            site = RegexSite(descriptor)
        else:
            log.info("未能自动学习站点规则，本次及后续将使用通用启发式抽取")

    meta = probe_meta
    meta.source_url = url
    meta.publisher = cfg.epub.publisher
    meta.rights = cfg.epub.rights
    meta.language = cfg.epub.language
    meta.site = site.name
    store.save_meta(meta)
    store.save_toc(toc)
    meta.cover_url = meta.cover_url or ""
    if meta.cover_url and not store.cover_path():
        _fetch_cover(store, http, meta, url)
    if not store.cover_path():
        _cover_from_other_sources(cfg, store, http, meta, url,
                                  list(sources or []), rules_dirs)

    # 字体加密探测与自动解密（用首章页面），解密表随工作区沉淀
    font_map = _probe_and_decode_font(http, site, url, toc)
    if font_map:
        store.save_font_map(font_map)
    cleaner = _make_cleaner(cfg, font_map)
    crawler = Crawler(cfg, store, site, http, cleaner, proxy_pool, limiter)

    _log_book_info(meta, len(toc), bool(store.cover_path()))
    failed = crawler.crawl_chapters(toc, url, force=force)

    # 跨源补全：空/可疑/过短章从同书其他源（--source + 书目索引）修复
    try:
        alt_urls = list(dict.fromkeys(
            list(sources or [])
            + bookindex.other_sources(cfg.workdir, meta.title, url)))
        if alt_urls:
            n = crawler.repair_from_sources(toc, url, alt_urls)
            if n:
                failed = [i for i in failed
                          if (c := store.load_chapter(i)) is None
                          or c.status != "ok"]
    except KeyboardInterrupt:
        raise
    except Exception as e:  # noqa: BLE001 - 补全是增益，失败不影响已完成的爬取
        log.warning("跨源补全阶段失败（跳过）: %s", e)

    # 登记书目索引：本书这个源从此可供同书其他源的跨源补全使用
    try:
        bookindex.record(cfg.workdir, meta.title, url, toc)
    except Exception as e:  # noqa: BLE001
        log.debug("书目索引登记失败（不影响主流程）: %s", e)

    if failed:
        log.warning("仍有 %d 章未完成，可重新运行 crawl 续跑。", len(failed))
    return store


def _cover_from_other_sources(cfg: AppConfig, store: BookStore, http: HttpClient,
                              meta, book_url: str, extra: List[str],
                              rules_dirs: List[str]):
    """跨源封面兜底：主源书页没封面时，从书目索引/--source 的同书其他源找。

    注意：无法自动判定“封面图内容与书名不符”（源站图片错位是站方数据问题），
    那种情况需人工替换工作区 cover.jpg 后重新 build。
    """
    try:
        alts = list(dict.fromkeys(
            [u for u in extra if "://" in u]
            + bookindex.other_sources(cfg.workdir, meta.title, book_url)))
        for alt in alts:
            try:
                alt_site = get_adapter(alt, "", extra_rules_dirs=list(rules_dirs))
                a_meta = alt_site.parse_meta(http.get(alt).text, alt)
                if not a_meta.cover_url:
                    continue
                _fetch_cover(store, http, a_meta, alt)
                if store.cover_path():
                    log.info("本源无封面，已从同书其他源获取: %s", alt)
                    return
            except Exception:  # noqa: BLE001 - 兜底路径，单源失败继续下一个
                continue
    except Exception as e:  # noqa: BLE001
        log.debug("跨源封面兜底失败（不阻塞）: %s", e)


def _probe_and_decode_font(http: HttpClient, site, book_url: str, toc) -> dict:
    """用首章页面探测 PUA 字体加密，命中则自动下载字体构建解密表。"""
    if not toc:
        return {}
    ch_url = SiteAdapter.chapter_url(book_url, toc[0].href)
    try:
        html = http.get(ch_url, referer=book_url).text
        lines = site.parse_chapter(html, ch_url)
        if pua_ratio("".join(lines)) <= 0.02:
            return {}
        log.info("检测到疑似字体加密（正文为 PUA 码位），尝试自动解密...")
        mapping = learn_font_map(http, html, ch_url)
        if mapping:
            log.info("字体解密成功：%d 个字符映射已保存，后续章节自动还原", len(mapping))
        else:
            log.warning("字体解密失败（glyph 命名无原始码位映射，或需安装 fonttools/brotli）；"
                        "正文将保留原码位")
        return mapping
    except Exception as e:
        log.debug("字体探测失败（不阻塞主流程）: %s", e)
        return {}


def _fetch_cover(store: BookStore, http: HttpClient, meta, book_url: str):
    from urllib.parse import urljoin
    url = urljoin(book_url, meta.cover_url) if meta.cover_url.startswith("/") else meta.cover_url
    try:
        resp = http.get(url, referer=book_url, stream=True, as_text=False)
        ext = "png" if "png" in (resp.content_type or "") else "jpg"
        store.save_cover(resp.content, ext)
        log.info("封面已保存")
    except Exception as e:
        log.warning("封面下载失败: %s", e)


# ---------- 成品审核（verify） ----------
def _verify_read_epub(epub_path: str):
    """从成品 EPUB 提取各章正文段落（审核面向交付物而非工作区缓存）。"""
    import re as _re
    import zipfile
    out = {}
    with zipfile.ZipFile(epub_path) as zf:
        for name in zf.namelist():
            m = _re.fullmatch(r"OEBPS/chapter(\d+)\.xhtml", name)
            if not m:
                continue
            x = zf.read(name).decode("utf-8", "ignore")
            out[int(m.group(1))] = _re.findall(r'<p class="indent">(.*?)</p>', x)
    return out


def cmd_verify(cfg: AppConfig, book_dir: str, url: str = "", samples: int = 5) -> int:
    """审核成品质量：本地结构检查 +（给定 --url 时）源站实时抽样对照。

    检查项：缺章 / 空章 / 质量可疑标记 / 重复章名行 / 导航块残留 /
    推荐块残留 / 页尾续读标记残留；实时项：分页页数覆盖 / 字数覆盖比。
    退出码：0=PASS，1=WARN，2=FAIL。
    """
    import random
    import re
    from .cleaner import Cleaner, CHAPTER_TITLE_RE
    store = BookStore(os.path.abspath(book_dir))
    meta = store.load_meta()
    if meta is None:
        log.error("工作区缺少 meta.json: %s", store.root)
        return 2
    toc = store.load_toc()
    chapters = {c.index: c for c in store.iter_chapters()}
    problems = []   # (级别, 描述)

    missing = [i for i in range(1, len(toc) + 1) if i not in chapters]
    if missing:
        problems.append(("FAIL", "缺章 %d 个: %s" % (len(missing), missing[:10])))
    empty = [i for i, c in chapters.items() if not c.paragraphs]
    src_missing = [i for i in empty
                   if "正文抽取为空" in (getattr(chapters[i], "problems", None) or [])]
    other_empty = sorted(set(empty) - set(src_missing))
    if src_missing:
        problems.append(("WARN", "源站无正文 %d 章（成品已插占位说明）: %s"
                         % (len(src_missing), src_missing[:10])))
    if other_empty:
        problems.append(("FAIL", "空章 %d 个: %s" % (len(other_empty), other_empty[:10])))
    susp = [c.index for c in chapters.values() if getattr(c, "status", "ok") != "ok"]
    if susp:
        problems.append(("WARN", "质量可疑章 %d 个: %s" % (len(susp), susp[:10])))

    n_title = re.sub(r"\s+", "", meta.title) if meta.title else ""
    # 残留检查面向成品 EPUB（build 层还有 junk 行二次过滤与尾块截断，工作区缓存非最终形态）
    epub_path = os.path.join(os.path.dirname(store.root), safe_dirname(meta.title) + ".epub")
    chap_paras = _verify_read_epub(epub_path) if os.path.isfile(epub_path) else \
        {i: c.paragraphs for i, c in chapters.items()}
    if os.path.isfile(epub_path):
        log.info("残留检查基于成品: %s", epub_path)
    else:
        log.warning("未找到成品 epub，残留检查退回工作区缓存（可能有 build 层差异）")
    nav_bad, rec_bad, tail_bad = [], [], []
    for i, ps in sorted(chap_paras.items()):
        if not ps:
            continue
        if any(len(CHAPTER_TITLE_RE.findall(p)) >= 3 for p in ps):
            nav_bad.append(i)
        run = 0
        for p in reversed(ps):     # 只统计章尾连续短行（与 cleaner 尾块规则同口径，
            if len(p) <= 24 and "。" not in p:   # 章内对话高潮短行不算残留）
                run += 1
            else:
                break
        if run >= 4:
            rec_bad.append(i)
        last = ps[-1]
        if (Cleaner._page_break_signal(last) or Cleaner._page_end_signal(last)) \
                and "源站暂无正文" not in last:
            tail_bad.append(i)
    if nav_bad:
        problems.append(("FAIL", "导航块残留 %d 章: %s" % (len(nav_bad), nav_bad[:10])))
    if rec_bad:
        problems.append(("FAIL", "推荐块残留 %d 章: %s" % (len(rec_bad), rec_bad[:10])))
    if tail_bad:
        problems.append(("FAIL", "章尾残留页尾标记 %d 章（分页可能未拼全）: %s"
                         % (len(tail_bad), tail_bad[:10])))

    if url:
        limiter = DomainLimiter(rate_per_sec=cfg.rate.rate_per_sec,
                                burst=cfg.rate.burst,
                                cooldown_on_block=cfg.rate.cooldown_on_block)
        _, http = _wire_runtime(cfg, limiter)
        auto_dir = auto_dir_for(cfg.workdir, cfg.auto.save_dir) if cfg.auto.enabled else ""
        site = get_adapter(url, "", extra_rules_dirs=[auto_dir] if auto_dir else [])
        from .downloader import Crawler
        from .sites.generic import content_oracle_lines
        probe = Crawler(cfg, store, site, http, _make_cleaner(cfg))
        entries = [(i, e) for i, e in enumerate(toc, 1) if i in chapters and chapters[i].paragraphs]
        picks = random.sample(entries, min(max(1, samples), len(entries))) if entries else []
        covered, depth_bad, thin_bad = 0, [], []
        for i, e in picks:
            try:
                ch_url = site.chapter_url(url, e.get("href") if isinstance(e, dict) else e.href)
                ctitle = e.get("title") if isinstance(e, dict) else e.title
                html = http.get(ch_url).text
                # 标尺：首页 trafilatura 抽取量 vs 成品全章字数（成品≥首页标尺即证明至少拿到一页，
                # 分页越多富余越大；分页丢失/容器选偏都会跌破阈值）
                oracle_chars = sum(len(l) for l in content_oracle_lines(html))
                # 探测源站真实页数（链接 + 序列探针，带归属校验）
                depth = 1
                cur_html, cur_url = html, ch_url
                while depth < cfg.fetch.max_next_pages:
                    nxt = find_next_page_url(cur_html, cur_url)
                    p2 = probe._probe_url(ch_url, depth + 1)
                    cand = nxt if (nxt and nxt not in (cur_url, ch_url)) else p2
                    if not cand or cand == cur_url:
                        break
                    try:
                        cur_html = http.get(cand, referer=cur_url).text
                    except FetchError:
                        break
                    if not probe._page_belongs(cur_html, cand, ctitle):
                        break
                    cur_url, depth = cand, depth + 1
                covered += 1
                stored_chars = sum(len(p) for p in chapters[i].paragraphs)
                if oracle_chars and oracle_chars >= 200 and stored_chars < oracle_chars * 0.65:
                    thin_bad.append((i, depth, stored_chars, oracle_chars))
            except FetchError as ex:
                log.warning("实时对照第 %d 章取页失败（跳过）: %s", i, ex)
        if thin_bad:
            problems.append(("FAIL", "实时对照字数覆盖不足（疑分页未拼全）%d 章: %s"
                             % (len(thin_bad), thin_bad[:5])))
        log.info("实时对照: 抽样 %d/%d 章可用", covered, len(picks))

    fails = [p for lv, p in problems if lv == "FAIL"]
    warns = [p for lv, p in problems if lv == "WARN"]
    # 置信度分布报告（缓存中的成品形态值）
    confs = [(c.index, getattr(c, "confidence", 1.0)) for c in chapters.values()]
    if confs:
        vals = sorted(v for _, v in confs)
        median = vals[len(vals) // 2]
        low = sorted((i for i, v in confs if v < cfg.cleaner.min_confidence),
                     key=lambda i: dict(confs)[i])
        log.info("=============== 审核结果 ===============")
        log.info("章节: %d/%d（目录 %d）| 重复章名/挂件残留: %d 章 | 置信度中位 %.2f",
                 len(chapters), len(toc), len(toc), len(nav_bad) + len(rec_bad) + len(tail_bad), median)
        if low:
            problems.append(("WARN", "低置信章 %d 个（建议降速重抓或人工抽检）: %s"
                             % (len(low), low[:10])))
            warns = [p for lv, p in problems if lv == "WARN"]
    else:
        log.info("=============== 审核结果 ===============")
        log.info("章节: %d/%d（目录 %d）| 重复章名/挂件残留: %d 章",
                 len(chapters), len(toc), len(toc), len(nav_bad) + len(rec_bad) + len(tail_bad))
    for msg in fails:
        log.error("FAIL %s", msg)
    for msg in warns:
        log.warning("WARN %s", msg)
    if not problems:
        log.info("PASS 全部检查通过（分页覆盖/无残留/无空章/无缺章）")
        return 0
    return 2 if fails else 1


def cmd_build(cfg: AppConfig, store: BookStore, formats: List[str]) -> int:
    meta = store.load_meta()
    if meta is None:
        log.error("工作区缺少 meta.json: %s", store.root)
        return 1
    auto_dir = auto_dir_for(cfg.workdir, cfg.auto.save_dir) if cfg.auto.enabled else ""
    extra = [auto_dir] if auto_dir else []
    try:
        site = get_adapter(meta.source_url or "", meta.site or "", extra_rules_dirs=extra)
    except ValueError:
        # 学习规则文件可能已被清理，退回 host 匹配/generic
        site = get_adapter(meta.source_url or "", "", extra_rules_dirs=extra)
    cleaner = _make_cleaner(cfg, store.load_font_map())
    out_dir = os.path.dirname(store.root)
    epub_path = os.path.join(out_dir, safe_dirname(meta.title) + ".epub")
    build_epub(store, epub_path, cleaner)

    rc = 0
    want = [f for f in formats if f in ("mobi", "azw3")]
    if want:
        # 不再传原始小封面作为 --cover（会覆盖 EPUB 内已归一化的封面）；
        # 由 --prefer-metadata-cover 从 EPUB 的 cover-image 读取高清封面
        outputs = convert_epub(epub_path, want, cfg.convert, meta.language)
        missing = set(want) - {os.path.splitext(o)[1].lstrip(".") for o in outputs}
        if missing:
            log.warning("以下格式未生成: %s", ",".join(sorted(missing)))
            rc = 2
    return rc


def _path_size(path: str) -> int:
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


def cmd_clean(cfg: AppConfig, targets: List[str], everything: bool = False,
              dry_run: bool = False) -> int:
    """清理输出目录（books）。

    不带参数：清除 workdir 内全部缓存（书籍工作区目录、成品书以外的杂项文件），
    保留成品书 .epub/.mobi/.azw3。
    --all：删除所有内容，包括成品书；workdir 清空后连目录本身一并删除（下次出书重建）。
    指定 targets：只清对应工作区；加 --all 时连带其成品书。
    工程根 sites/ 学习规则不在 workdir 内，不受影响。
    """
    if not os.path.isdir(cfg.workdir):
        log.info("输出目录不存在，无需清理：%s", cfg.workdir)
        return 0
    book_exts = (".epub", ".mobi", ".azw3")

    paths: List[str] = []
    if targets:
        for t in targets:
            p = os.path.abspath(t)
            if os.path.isdir(p):
                paths.append(p)
                if everything:  # 连带该工作区的成品书
                    meta = _readonly_store(p).load_meta()
                    names = {safe_dirname(meta.title)} if meta else set()
                    names.add(os.path.basename(p.rstrip("/")))
                    for nm in names:
                        base = os.path.join(cfg.workdir, nm)
                        paths.extend(base + e for e in book_exts
                                     if os.path.isfile(base + e))
            elif os.path.isfile(p):
                paths.append(p)
            else:
                log.warning("路径不存在，跳过: %s", p)
        remove_workdir = False
    else:
        for n in sorted(os.listdir(cfg.workdir)):
            p = os.path.join(cfg.workdir, n)
            if os.path.isdir(p):
                paths.append(p)                                   # 工作区 = 缓存
            elif everything or os.path.splitext(n)[1].lower() not in book_exts:
                paths.append(p)                                   # --all 连成品一起删
        remove_workdir = everything

    if not paths:
        log.info("没有需要清理的内容")
        return 0

    freed = sum(_path_size(p) for p in paths)
    if dry_run:
        for p in paths:
            log.info("[预演] 将删除 %s（%.1f MB）", p, _path_size(p) / 1048576.0)
        log.info("[预演] 共 %d 项，预计释放 %.1f MB，未删除任何文件",
                 len(paths), freed / 1048576.0)
        return 0

    for p in paths:
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            log.info("已删除 %s", p)
        except OSError as e:
            log.warning("删除失败 %s: %s", p, e)

    if remove_workdir and os.path.isdir(cfg.workdir) and not os.listdir(cfg.workdir):
        try:
            os.rmdir(cfg.workdir)
            log.info("输出目录已移除：%s（下次出书自动重建）", cfg.workdir)
        except OSError:
            pass
    log.info("清理完成：%d 项，释放 %.1f MB", len(paths), freed / 1048576.0)
    return 0


def _readonly_store(root: str) -> BookStore:
    """构造不建目录的只读 BookStore 句柄（供 clean 扫描用）。"""
    store = BookStore.__new__(BookStore)
    store.root = root
    store.chapters_dir = os.path.join(root, "chapters")
    return store


def _auto_clean(cfg: AppConfig, store: BookStore):
    """run/build --clean：产出后删除该书工作区缓存，保留成品（与裸 clean 一致）。"""
    freed = _path_size(store.root)
    if os.path.isdir(store.root):
        shutil.rmtree(store.root)
    log.info("已清理工作区缓存：%s（释放 %.1f MB，成品已保留）",
             store.root, freed / 1048576.0)


def main(argv: Optional[List[str]] = None) -> int:
    argv_in = normalize_argv(sys.argv[1:] if argv is None else list(argv))
    parser = argparse.ArgumentParser(
        prog="ebookmaker",
        description="小说站点爬取 -> 内容净化 -> EPUB/MOBI/AZW3 生成")
    parser.add_argument("-c", "--config", help="全局配置文件（YAML），默认 ./config.yaml")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="详细日志")
    parser.add_argument("-q", "--quiet", action="store_true", help="仅警告日志")
    parser.epilog = ("一步式用法：python3 -m ebookmaker <书籍目录页URL> "
                     "（等价于 run --url，直接产出 epub/mobi/azw3）")
    sub = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--threads", type=int, help="下载线程数（默认 8）")
    common.add_argument("--cookie", help="站点 Cookie")
    common.add_argument("--workdir", help="书籍工作区根目录（默认 books）")
    common.add_argument("--rules-dir", action="append", default=[],
                        help="额外站点描述符目录（高级，仅影响页面结构适配；净化规则均为内建通用逻辑）")
    common.add_argument("--proxy-source", choices=["none", "list", "api", "file"],
                        help="代理来源（默认 none 直连）")
    common.add_argument("--proxy-api", help="api 代理源 URL")
    common.add_argument("--proxy-file", help="file 代理源路径（每行 ip:port）")

    p_crawl = sub.add_parser("crawl", parents=[common], help="仅爬取+净化落盘（可反复续跑）")
    p_crawl.add_argument("--url", required=True, help="书籍目录页 URL")
    p_crawl.add_argument("--site", default="", help="强制指定站点适配器名")
    p_crawl.add_argument("--force", action="store_true", help="忽略缓存全部重爬")
    p_crawl.add_argument("--source", action="append", default=None, metavar="URL",
                         help="同一本书的其他源目录页（可重复），用于补齐空章/过短章")

    p_run = sub.add_parser("run", parents=[common], help="全流程：爬取→净化→制书→转换")
    p_run.add_argument("--url", required=True, help="书籍目录页 URL")
    p_run.add_argument("--site", default="", help="强制指定站点适配器名")
    p_run.add_argument("--force", action="store_true", help="忽略缓存全部重爬")
    p_run.add_argument("--source", action="append", default=None, metavar="URL",
                       help="同一本书的其他源目录页（可重复），用于补齐空章/过短章")
    p_run.add_argument("--formats", default="", help="输出格式，如 epub,mobi,azw3（默认取配置）")
    p_run.add_argument("--clean", action="store_true", help="成品产出后自动清理工作区中间文件")

    p_build = sub.add_parser("build", parents=[common], help="仅从本地工作区生成电子书（不联网）")
    p_build.add_argument("book_dir", help="书籍工作区目录（books/<书名>）")
    p_build.add_argument("--formats", default="", help="输出格式，如 epub,mobi,azw3")
    p_build.add_argument("--clean", action="store_true", help="成品产出后自动清理工作区中间文件")

    p_conv = sub.add_parser("convert", help="仅格式转换（epub -> mobi/azw3）")
    p_conv.add_argument("epub", help="epub 文件路径")
    p_conv.add_argument("--formats", default="mobi,azw3")

    p_clean = sub.add_parser("clean", parents=[common],
                             help="清理输出目录：不带参数清缓存留成品；--all 全删（含成品书）")
    p_clean.add_argument("targets", nargs="*",
                         help="指定要清理的工作区目录/文件，缺省为 workdir 全部内容")
    p_clean.add_argument("--all", dest="everything", action="store_true",
                         help="删除所有内容，包括成品书与输出目录本身")
    p_clean.add_argument("--dry-run", action="store_true", help="只展示将清理的内容，不删除")

    p_verify = sub.add_parser("verify", parents=[common],
                              help="审核成品质量：分页完整性/残留垃圾/空章；加 --url 做源站实时对照")
    p_verify.add_argument("book_dir", help="书籍工作区目录（books/<书名>）")
    p_verify.add_argument("--url", default="", help="书籍目录页 URL（启用实时抽样对照）")
    p_verify.add_argument("--samples", type=int, default=5, help="实时对照抽样章数（默认 5）")

    if not argv_in:
        parser.print_help()
        return 1

    args = parser.parse_args(argv_in)
    if not args.command:
        parser.print_help()
        return 1
    setup_logging(0 if args.quiet else args.verbose)
    cfg = _apply_overrides(load_config(args.config), args)

    try:
        return _dispatch(args, cfg)
    except KeyboardInterrupt:
        log.warning("已中断；crawl/run 重新执行同一命令即可断点续跑")
        return 130
    except CloudflareChallengeError as e:
        log.error("被 Cloudflare 拦截: %s", e)
        log.error("该站启用了浏览器人机验证，纯 HTTP 爬虫无法通过；请改用未开此防护的镜像站/源站")
        return 3
    except FetchError as e:
        log.error("网络获取失败: %s", e)
        log.error("可稍后重试，或用 --proxy-source list/api/file 启用代理后重跑同一命令")
        return 2


def _dispatch(args, cfg: AppConfig) -> int:
    if args.command == "crawl":
        store = cmd_crawl(cfg, args.url, args.site, args.rules_dir, args.force,
                          args.source)
        return 0 if store else 1

    if args.command == "run":
        store = cmd_crawl(cfg, args.url, args.site, args.rules_dir, args.force,
                          args.source)
        if store is None:
            return 1
        formats = _split_formats(args.formats) if args.formats else cfg.formats
        if "epub" not in formats:
            formats = ["epub"] + formats  # epub 是转换母格式，必出
        rc = cmd_build(cfg, store, formats)
        if (args.clean or cfg.cleanup.auto) and rc in (0, 2):
            _auto_clean(cfg, store)
        return rc

    if args.command == "build":
        store = BookStore(os.path.abspath(args.book_dir))
        formats = _split_formats(args.formats) if args.formats else cfg.formats
        if "epub" not in formats:
            formats = ["epub"] + formats
        rc = cmd_build(cfg, store, formats)
        if (args.clean or cfg.cleanup.auto) and rc in (0, 2):
            _auto_clean(cfg, store)
        return rc

    if args.command == "clean":
        return cmd_clean(cfg, args.targets, args.everything, args.dry_run)

    if args.command == "verify":
        return cmd_verify(cfg, args.book_dir, args.url, args.samples)

    if args.command == "convert":
        epub = os.path.abspath(args.epub)
        if not os.path.isfile(epub):
            log.error("文件不存在: %s", epub)
            return 1
        outputs = convert_epub(epub, _split_formats(args.formats), cfg.convert)
        return 0 if outputs else 2

    # 上方 main 已保证 command 合法，此处仅防御
    log.error("未知命令: %s", args.command)
    return 1


if __name__ == "__main__":
    sys.exit(main())
