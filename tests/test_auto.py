# -*- coding: utf-8 -*-
"""站点自动适配（学习/复用/分页拼接）测试。"""

import os

from ebookmaker.auto import (css_selector, learn_site, load_learned_site,
                             save_descriptor)
from ebookmaker.cleaner import Cleaner
from ebookmaker.config import AppConfig, AutoConfig, CleanerConfig
from ebookmaker.downloader import Crawler, Progress
from ebookmaker.models import TocEntry
from ebookmaker.sites.base import find_next_page_url
from ebookmaker.sites.generic import GenericSite
from ebookmaker.sites.regex_site import RegexSite
from ebookmaker.store import BookStore

BOOK_URL = "https://novel.fake.cn/book/999/"
BODY = "".join("夜色下的皇城格外安静，只有更鼓声远远传来。" for _ in range(12))
BODY2 = "".join("而城头的黑影一动不动，仿佛早已等候多时。" for _ in range(12))


def chapter_page(doc_id, paged=False):
    """doc_id 为章节文档名（如 102）；paged=True 时带同系列分页链接。"""
    pages = ""
    if paged:
        pages = ('<div class="pages"><a href="{0}_2/">下一页</a>'
                 '<a href="{1}.html">下一章</a></div>').format(doc_id, doc_id + 1)
    return ("<html><head><title>章节</title></head><body>"
            '<div class="wrap"><div class="side"><a href="/top">热门推荐</a></div>'
            '<div id="readbox">' + BODY + '</div>'
            + pages + "</div></body></html>")


def chapter_page2(doc_id):
    return ("<html><body><div class=\"wrap\">"
            '<div id="readbox">' + BODY2 + "</div>"
            '<div class="pages"><a href="{0}.html">下一章</a></div>'
            "</div></body></html>".format(doc_id + 1))


def toc_page(n=30):
    links = "\n".join('<dd><a href="{}.html">第{}章 测试</a></dd>'.format(100 + i, i + 1)
                      for i in range(n))
    return ("<html><body><dl>" + links + "</dl></body></html>")


class FakeHttp:
    """按 URL 返回合成页面。文档编号 = 章节号 + 99。"""

    def __init__(self, paged=False):
        self.paged = paged
        self.calls = []

    def get(self, url, referer=None, **kw):
        self.calls.append(url)

        class R:
            def __init__(self, text):
                self.text = text

        if url.rstrip("/") == BOOK_URL.rstrip("/"):
            return R(toc_page())
        base = url.rstrip("/").split("/")[-1].replace(".html", "")
        doc_id = int(base.split("_")[0])
        if "_2" in base:                       # 第二页
            return R(chapter_page2(doc_id))
        paged = self.paged and doc_id % 3 == 0  # 每3章有一章分两页
        return R(chapter_page(doc_id, paged=paged))


# ---------- 分页链接探测 ----------
def test_find_next_page_url_series_only():
    html = '<a href="12345_2.html">下一页</a><a href="12346.html">下一章</a>'
    nxt = find_next_page_url(html, "https://x.com/b/12345.html")
    assert nxt == "https://x.com/b/12345_2.html"

    # 指向另一章编号的“下一页”不算分页
    html2 = '<a href="12346.html">下一页</a>'
    assert find_next_page_url(html2, "https://x.com/b/12345.html") is None

    # 目录式路径 /12345/2/ 视为分页
    html3 = '<a href="/b/12345/2/">下一页</a>'
    assert find_next_page_url(html3, "https://x.com/b/12345.html") == "https://x.com/b/12345/2/"


# ---------- CSS 选择器生成 ----------
def test_css_selector_prefers_id():
    from ebookmaker.sites.base import make_soup
    soup = make_soup('<div id="a"><p>x</p></div><div class="b"><p>y</p></div>')
    node = soup.find("div", id="a")
    assert css_selector(node, soup) == "#a"


# ---------- 站点学习 ----------
def make_toc(n=30):
    return [TocEntry(href="{}.html".format(100 + i), title="第{}章 测试".format(i + 1))
            for i in range(n)]


def test_learn_site_finds_readbox():
    http = FakeHttp()
    cfg = AutoConfig(samples=5)
    descriptor = learn_site(http, BOOK_URL, make_toc(), Cleaner(CleanerConfig()), cfg)
    assert descriptor is not None
    assert descriptor["type"] == "site"
    assert descriptor["hosts"] == ["novel.fake.cn"]
    assert descriptor["content"]["selector"] == "#readbox"
    # 目录选择器为链接形态（容器 + a）
    assert descriptor["toc"]["selector"] == "dl a"
    site = RegexSite(descriptor)
    assert len(site.parse_toc(toc_page(), BOOK_URL)) == 30
    lines = site.parse_chapter(chapter_page(100), BOOK_URL + "100.html")
    assert "夜色下的皇城" in "".join(lines)


def test_save_and_reuse_descriptor(tmp_path):
    descriptor = {"name": "auto-novel.fake.cn", "type": "site",
                  "hosts": ["novel.fake.cn"], "content": {"selector": "#readbox"}}
    d = str(tmp_path / "auto")
    save_descriptor(descriptor, d)
    site = load_learned_site(d, BOOK_URL)
    assert site is not None and site.name == "auto-novel.fake.cn"
    assert "#readbox" in site._content_selector
    # 其他 host 不会误复用
    assert load_learned_site(d, "https://other.site/x/") is None


# ---------- 分页自动拼接（走完整 Crawler 单章流程） ----------
def test_crawler_joins_paginated_chapter(tmp_path):
    cfg = AppConfig()
    cfg.fetch.jitter_min = cfg.fetch.jitter_max = 0.0
    http = FakeHttp(paged=True)
    store = BookStore(str(tmp_path / "书"))
    crawler = Crawler(cfg, store, GenericSite(), http, Cleaner(CleanerConfig()))
    crawler.progress = Progress(1)
    toc = make_toc()
    # toc[2] => 102.html（文档号 102 为 3 的倍数，分页）
    assert crawler._fetch_one(3, toc[2], BOOK_URL) is True
    ch = store.load_chapter(3)
    assert ch is not None and ch.status == "ok"
    joined = "".join(ch.paragraphs)
    assert "夜色下的皇城" in joined      # 第一页
    assert "城头的黑影" in joined        # 第二页被拼接
    # 未分页章节不应请求第二页
    assert crawler._fetch_one(1, toc[0], BOOK_URL) is True   # 100.html 不分页
    ch1 = store.load_chapter(1)
    assert "城头的黑影" not in "".join(ch1.paragraphs)
