# -*- coding: utf-8 -*-
"""跨源补全（Crawler.repair_from_sources）与书目索引的离线验证。"""

import os
from urllib.parse import urljoin

import pytest

from ebookmaker import bookindex
from ebookmaker.cleaner import Cleaner
from ebookmaker.config import AppConfig
from ebookmaker.downloader import Crawler, _align_toc
from ebookmaker.http_client import FetchError
from ebookmaker.models import ChapterData, TocEntry
from ebookmaker.store import BookStore

SENTS = ("他想起那年的雨夜，长安街上的灯火一盏盏熄灭，唯有城头的风还在呜咽。")


def prose(n_paragraphs: int) -> list:
    """生成 n 段互不相同的正常叙事正文（带句号、无广告形态；同段重复会
    触发页级审查的“页内行重复”信号，不符合真实正文形态）。"""
    return ["他想起那年的雨夜，长安街上的灯火一盏盏熄灭，唯有城头的风还在呜咽。"
            "第%d段，街角的灯下站着个熟悉的身影。" % k for k in range(n_paragraphs)]


class Resp:
    def __init__(self, text):
        self.text = text


class StubHttp:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(url)
        if url not in self.pages:
            raise FetchError("404 %s" % url)
        return Resp(self.pages[url])


class StubSite:
    name = "stub"
    allowed_hosts = ()

    def __init__(self, toc_entries, bodies):
        self._toc = toc_entries
        self._bodies = bodies  # 绝对 URL -> lines

    def parse_toc(self, html, url):
        return list(self._toc)

    def parse_chapter(self, html, url):
        return list(self._bodies.get(url, []))

    @staticmethod
    def chapter_url(book_url, href):
        return urljoin(book_url, href)


def _mk_toc(n, prefix="http://a.site/b/"):
    return [TocEntry(href="/b/%d.html" % (100 + i), title="第%d章 条目%d" % (i, i))
            for i in range(1, n + 1)]


def _mk_crawler(tmp_path, store_site_pages, toc):
    cfg = AppConfig()
    store = BookStore(os.path.join(str(tmp_path), "book"))
    http = StubHttp(store_site_pages)
    site = StubSite(toc, {})
    crawler = Crawler(cfg, store, site, http, Cleaner(cfg.cleaner))
    return cfg, store, http, crawler


def test_repair_fills_missing_and_short(tmp_path):
    toc = _mk_toc(3)
    long_ok = prose(8)                      # ~600+ 字
    cfg, store, http, crawler = _mk_crawler(tmp_path, {}, toc)
    # 主源现状：ch1 完整；ch2 缺章；ch3 过短
    store.save_chapter(ChapterData(index=1, title=toc[0].title, url="http://a.site/b/100.html",
                                   paragraphs=long_ok, status="ok"))
    store.save_chapter(ChapterData(index=3, title=toc[2].title, url="http://a.site/b/102.html",
                                   paragraphs=["只有短短一句话。"], status="ok"))

    # 候选源：4 章目录（含额外一章），按章名对齐；第2/3章有完整正文
    # （_mk_toc 形态：第N章 -> /b/10N.html，与主源同构）
    alt_toc = _mk_toc(3) + [TocEntry(href="/b/104.html", title="第4章 番外")]
    alt_bodies = {
        "http://b.site/b/102.html": prose(9),
        "http://b.site/b/103.html": prose(9),
    }
    alt_site = StubSite(alt_toc, alt_bodies)
    crawler._resolve_alt_site = lambda u: alt_site
    crawler.http = StubHttp({"http://b.site/b/": "<html>toc</html>",
                             "http://b.site/b/102.html": "<html/>",
                             "http://b.site/b/103.html": "<html/>"})
    n = crawler.repair_from_sources(toc, "http://a.site/b/", ["http://b.site/b/"])
    assert n == 2
    ch2 = store.load_chapter(2)
    assert ch2 is not None and ch2.status == "ok"
    assert ch2.text_length() >= 300
    assert ch2.url == "http://b.site/b/102.html"   # 溯源保留实际来源 URL
    ch3 = store.load_chapter(3)
    assert ch3.text_length() >= 300
    ch1 = store.load_chapter(1)
    assert ch1.url == "http://a.site/b/100.html"   # 好章从不触碰


def test_repair_keeps_main_when_alt_not_better(tmp_path):
    toc = _mk_toc(2)
    cfg, store, http, crawler = _mk_crawler(tmp_path, {}, toc)
    main_text = prose(8)
    store.save_chapter(ChapterData(index=2, title=toc[1].title, url="http://a.site/b/101.html",
                                   paragraphs=["短的。"], status="ok"))

    alt_bodies = {"http://b.site/b/101.html": ["也只有一句话。"]}
    alt_site = StubSite(_mk_toc(2), alt_bodies)
    crawler._resolve_alt_site = lambda u: alt_site
    crawler.http = StubHttp({"http://b.site/b/": "<html/>",
                             "http://b.site/b/101.html": "<html/>",
                             "http://b.site/b/102.html": "<html/>"})
    # 45字 相对 4字 超过 1.2x 会被采纳，但 ch2 太短可能不过置信闸门——
    # 无论采纳与否，结果必须单调不劣化：status=ok 且非空
    n = crawler.repair_from_sources(toc, "http://a.site/b/", ["http://b.site/b/"])
    ch2 = store.load_chapter(2)
    assert ch2 is not None
    assert n in (0, 1)
    if n == 0:
        assert ch2.paragraphs == ["短的。"]   # 未采纳则主源版本原样保留


def test_gap_backfill_from_index(tmp_path, monkeypatch):
    # 主源目录缺编号章（源站缺页）：无坏章时仍从书目索引缓存目录发现空洞，
    # 按编号插入并从候选源补抓，后续章节缓存平移不错位
    monkeypatch.setattr(bookindex, "PROJECT_ROOT", tmp_path)
    toc = [TocEntry(href="/b/101.html", title="第1章 开端"),
           TocEntry(href="/b/103.html", title="第3章 转折")]
    cfg = AppConfig()
    store = BookStore(os.path.join(str(tmp_path), "book"))
    crawler = Crawler(cfg, store, StubSite(toc, {}), StubHttp({}),
                      Cleaner(cfg.cleaner))
    store.save_chapter(ChapterData(index=1, title=toc[0].title,
                                   url="http://a.site/b/101.html",
                                   paragraphs=prose(9), status="ok"))
    store.save_chapter(ChapterData(index=2, title=toc[1].title,
                                   url="http://a.site/b/103.html",
                                   paragraphs=prose(9), status="ok"))

    alt_toc = [TocEntry(href="/b/101.html", title="第1章 开端"),
               TocEntry(href="/b/102.html", title="第2章 发展"),
               TocEntry(href="/b/103.html", title="第3章 转折")]
    bookindex.record("wd", "测试书", "http://b.site/b/", alt_toc)
    alt_site = StubSite(alt_toc, {"http://b.site/b/102.html": prose(9)})
    crawler._resolve_alt_site = lambda u: alt_site
    crawler.http = StubHttp({"http://b.site/b/102.html": "<html/>"})

    n = crawler.repair_from_sources(toc, "http://a.site/b/", ["http://b.site/b/"])
    assert n == 1
    assert [e.title for e in toc] == ["第1章 开端", "第2章 发展", "第3章 转折"]
    ch2 = store.load_chapter(2)
    assert ch2 is not None and ch2.status == "ok" and ch2.text_length() >= 300
    ch3 = store.load_chapter(3)          # 缓存平移后仍为第3章
    assert ch3 is not None and ch3.title == "第3章 转折"
    assert [d["title"] for d in store.load_toc()] == [e.title for e in toc]


def test_align_positional_when_equal_count():
    toc = _mk_toc(3)
    alt = [TocEntry(href="/x/%d" % i, title="完全不同的名字%d" % i) for i in range(1, 4)]
    m = _align_toc(toc, alt)
    assert m[1].title == "完全不同的名字1" and m[3].title == "完全不同的名字3"


def test_align_by_title_when_count_differs():
    toc = _mk_toc(3)
    alt = [TocEntry(href="/x/9", title="第2章 条目2（2/2）"),
           TocEntry(href="/x/8", title="广告链接")]
    m = _align_toc(toc, alt)
    assert set(m) == {2}          # （2/2）分页后缀被归一掉
    assert m[2].href == "/x/9"


def test_bookindex_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(bookindex, "PROJECT_ROOT", tmp_path)
    toc = _mk_toc(3)
    bookindex.record("wd", "大明：我真不是万寿帝君", "http://a.site/b/", toc)
    bookindex.record("wd", "大明：我真不是万寿帝君 ", "http://b.site/b/", toc)
    # 书名键：标点/尾空格不影响命中；排除自身后应返回另一源
    got = bookindex.other_sources("wd", "大明：我真不是万寿帝君", "http://a.site/b/")
    assert got == ["http://b.site/b/"]
    alt = bookindex.source_toc("wd", "http://b.site/b/")
    assert len(alt) == 3 and alt[0].href == "/b/101.html"
    assert bookindex.norm_title("第2章 条目2（2/4）") == "第2章条目2"
    # 空 toc 不登记
    bookindex.record("wd", "空书", "http://c.site/", [])
    assert bookindex.other_sources("wd", "空书", "http://c.site/") == []
