# -*- coding: utf-8 -*-
"""自适应增强测试：同域目录过滤、目录分页合并、字体解密、实时进度。"""

import io

from ebookmaker.auto import (font_bytes_to_map, learn_font_map, pua_ratio)
from ebookmaker.cleaner import Cleaner
from ebookmaker.config import CleanerConfig
from ebookmaker.downloader import Progress
from ebookmaker.sites.base import (clean_author, clean_book_title, collect_series_pages,
                                   find_series_pages)
from ebookmaker.sites.generic import GenericSite
from ebookmaker.sites.regex_site import RegexSite


# ---------- 书名/作者通用噪声净化 ----------
def test_clean_book_title_strips_marketing_suffix():
    assert clean_book_title("大明：我真不是万寿帝君最新章节") == "大明：我真不是万寿帝君"
    assert clean_book_title("某某小说全文免费阅读无弹窗") == "某某小说"
    assert clean_book_title("某某小说最新章节_新笔趣阁") == "某某小说"
    # 干净书名不动；合法含下划线/结尾“目录”不误删
    assert clean_book_title("凡人修仙传") == "凡人修仙传"
    assert clean_book_title("小城大事目录") == "小城大事目录"
    assert clean_book_title("南方的底_色") == "南方的底_色"  # 无站点段时不切分隔符


def test_og_meta_prefers_clean_h1_over_polluted_og():
    html = """<html><head>
<meta property="og:novel:book_name" content="某某的江湖最新章节"/>
<meta property="og:novel:author" content="作者：张三"/>
</head><body><h1>某某的江湖</h1></body></html>"""
    meta = GenericSite().parse_meta(html, "https://a.site/b/1/")
    assert meta.title == "某某的江湖"
    assert meta.author == "张三"


def test_og_meta_meta_only_page_still_cleaned():
    html = '<html><head><meta property="og:novel:book_name" content="长夜难明无弹窗在线阅读"/></head><body></body></html>'
    meta = GenericSite().parse_meta(html, "https://a.site/b/1/")
    assert meta.title == "长夜难明"

MAIN = "https://www.bqg2.org"
BOOK_URL = MAIN + "/html/490/490651_5/"


# ---------- 描述符鲁棒性：容器/链接形态与回退 ----------
TOC_HTML = "<html><body><div id='wrapper'><dl>" + "\n".join(
    '<dd><a href="/{0}.html">第{0}章 x</a></dd>'.format(i) for i in range(1, 9)
) + "</dl></div></body></html>"


def test_descriptor_toc_accepts_container_selector():
    """历史学习产物存的容器选择器（如 '#wrapper'）仍须可用（本次故障回归）；
    容器内的分页导航/栏目链接不得进入目录。"""
    site = RegexSite({"name": "t1", "type": "site", "hosts": ["a.site"],
                      "toc": {"selector": "#wrapper"}, "content": {"selector": "#c"}})
    html = TOC_HTML.replace("</dl></div>", '<dd><a href="/html/490/490651_4/">上一页</a></dd>'
                           '<dd><a href="/html/490/490651_6/">下一页</a></dd>'
                           '<dd><a href="/sort/2/">历史小说</a></dd></dl></div>')
    toc = site.parse_toc(html, "https://a.site/book/1/")
    assert len(toc) == 8 and toc[0].title == "第1章 x"
    titles = [t.title for t in toc]
    assert "上一页" not in titles and "历史小说" not in titles


def test_descriptor_toc_accepts_link_selector():
    site = RegexSite({"name": "t2", "type": "site", "hosts": ["a.site"],
                      "toc": {"selector": "dl dd a"}, "content": {"selector": "#c"}})
    assert len(site.parse_toc(TOC_HTML, "https://a.site/book/1/")) == 8


def test_descriptor_falls_back_when_selectors_stale():
    """描述符选择器失效时自动回退通用定位/抽取，不硬失败。"""
    site = RegexSite({"name": "t3", "type": "site", "hosts": ["a.site"],
                      "toc": {"selector": "#gone"}, "content": {"selector": "#gone"}})
    assert len(site.parse_toc(TOC_HTML, "https://a.site/book/1/")) == 8
    chapter = ('<html><body><div class="chapter-body">'
               + "夜色下的皇城格外安静，只有更鼓声远远传来。" * 10 + "</div></body></html>")
    lines = site.parse_chapter(chapter, "https://a.site/book/1/2.html")
    assert "更鼓声" in "".join(lines)


# ---------- 同域目录过滤 ----------
def test_toc_filters_cross_domain_mirrors():
    rows = "\n".join(
        '<dd><a href="/html/490/{}_.html">第{}章 x</a></dd>'.format(1000 + i, i)
        for i in range(1, 9))
    html = "<html><body><dl>" + rows \
        + '<dd><a href="https://www.b2c9.net/422/422786/">某镜像章节</a></dd>' \
        + '<dd><a href="https://www.zz55.org/350/350270/">另一镜像章节</a></dd>' \
        + "</dl></body></html>"
    toc = GenericSite().parse_toc(html, BOOK_URL)
    assert len(toc) == 8
    assert all("b2c9" not in t.href and "zz55" not in t.href for t in toc)


def test_toc_kept_when_all_external():
    # 章节全部托管在外域时不应误删整本书
    rows = "\n".join(
        '<dd><a href="https://cdn.chap.host/{0}.html">第{0}章 x</a></dd>'.format(i)
        for i in range(1, 9))
    html = "<html><body><dl>" + rows + "</dl></body></html>"
    toc = GenericSite().parse_toc(html, BOOK_URL)
    assert len(toc) == 8


# ---------- 目录分页兄弟页 ----------
def test_find_series_pages():
    # 真实站点（如 bqg2）目录分页链接为根相对形式
    html = """
    <a href="/html/490/490651_4/">上一页</a>
    <a href="/html/490/490651_5/">5</a>
    <a href="/html/490/490651_6/">下一页</a>
    <a href="/html/490/490651_2/">2</a>
    <a href="/html/490/4906511.html">第1章</a>
    <a href="https://other.site/html/490/490651_7/">镜像</a>
    """
    urls = find_series_pages(html, BOOK_URL)
    assert set(urls) == {MAIN + "/html/490/490651_2/",
                         MAIN + "/html/490/490651_4/",
                         MAIN + "/html/490/490651_6/"}


def test_find_series_pages_reads_select_options():
    # 真实 bqg2 目录页：页码列表是 <select> 的 option value，<a> 只有“下一页”
    html = """
    <select onchange="location.href=this.value">
    <option value="/html/490/490651_2/" >第101-200章</option>
    <option value="/html/490/490651_3/" selected>第201-300章</option>
    <option value="/html/490/490651/999.html">非分页</option>
    </select>
    <a href="/html/490/490651/1.html">第1章</a>
    <a href="https://m.bqg2.org/html/490/490651_9/">镜像站</a>
    """
    urls = find_series_pages(html, MAIN + "/html/490/490651")
    assert set(urls) == {MAIN + "/html/490/490651_2/", MAIN + "/html/490/490651_3/"}


def _neighbor_page(n, total):
    """只渲染相邻页链接的目录页（上一页/下一页）。"""
    links = []
    if n > 1:
        links.append('<a href="/html/490/490651_{0}/">上一页</a>'.format(n - 1))
    if n < total:
        links.append('<a href="/html/490/490651_{0}/">下一页</a>'.format(n + 1))
    links.append('<a href="/html/490/490651/{0}.html">第{0}章</a>'.format(n))
    return "".join(links)


def test_collect_series_pages_follows_neighbor_only_chain():
    total = 5
    fetched = []

    def get_html(url):
        n = int(url.rstrip("/").rsplit("_", 1)[1])
        fetched.append(n)
        return _neighbor_page(n, total)

    pages = collect_series_pages(_neighbor_page(1, total), MAIN + "/html/490/490651", get_html)
    assert [u for u, _ in pages] == [MAIN + "/html/490/490651_{}/".format(i)
                                     for i in range(2, total + 1)]
    assert sorted(fetched) == [2, 3, 4, 5]


def _paged_list_page(n, total):
    """首页就列齐全部页码的目录页。"""
    opts = "".join('<option value="/html/490/490651_{0}/">第{0}页</option>'.format(i)
                   for i in range(2, total + 1))
    return '<select onchange="location.href=this.value">{0}</select>' \
           '<a href="/html/490/490651/{1}.html">第{1}章</a>'.format(opts, n)


def test_collect_series_pages_survives_page_failure():
    def get_html(url):
        if url.endswith("_3/"):
            raise RuntimeError("boom")
        return _neighbor_page(int(url.rstrip("/").rsplit("_", 1)[1]), 4)

    pages = collect_series_pages(_paged_list_page(1, 4), MAIN + "/html/490/490651", get_html)
    assert [u for u, _ in pages] == [MAIN + "/html/490/490651_2/",
                                     MAIN + "/html/490/490651_4/"]


def test_collect_series_pages_respects_page_cap():
    def get_html(url):
        n = int(url.rstrip("/").rsplit("_", 1)[1])
        return _neighbor_page(n, 999)

    pages = collect_series_pages(_neighbor_page(1, 999), MAIN + "/html/490/490651",
                                 get_html, max_pages=3)
    assert len(pages) == 3


# ---------- 字体加密检测与解密 ----------
def build_test_font() -> bytes:
    from fontTools.fontBuilder import FontBuilder
    from fontTools.ttLib.tables._g_l_y_f import Glyph
    fb = FontBuilder(1000, isTTF=True)
    glyphs = [".notdef", "uni4E2D", "uni6587", "g5"]
    fb.setupGlyphOrder(glyphs)
    fb.setupCharacterMap({0xE800: "uni4E2D", 0xE801: "uni6587", 0xE802: "g5"})
    fb.setupGlyf({g: Glyph() for g in glyphs})
    fb.setupHorizontalMetrics({g: (500, 0) for g in glyphs})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "t", "styleName": "t"})
    fb.setupOS2()
    fb.setupPost()
    buf = io.BytesIO()
    fb.save(buf)
    return buf.getvalue()


def test_font_bytes_to_map():
    m = font_bytes_to_map(build_test_font())
    # uni 命名可解；g5 类命名无法映射应跳过；非 PUA 不收录
    assert m == {"\ue800": "中", "\ue801": "文"}


def test_pua_ratio():
    assert pua_ratio("\ue800\ue800\ue800普通") > 0.5
    assert pua_ratio("纯正常中文") == 0.0


class FontHttp:
    def __init__(self, font_bytes):
        self.font_bytes = font_bytes

    def get(self, url, **kw):
        class R:
            def __init__(self, c):
                self.content = c
        return R(self.font_bytes)


def test_learn_font_map_extracts_font_face_url():
    html = """<style>@font-face{font-family:'zku';src:url('/files/font/d957e.woff') format('woff');}</style>"""
    m = learn_font_map(FontHttp(build_test_font()), html, "https://x/book/1.html")
    assert m == {"\ue800": "中", "\ue801": "文"}


def test_cleaner_applies_font_map():
    c = Cleaner(CleanerConfig(), font_map={"\ue800": "中", "\ue801": "文"})
    out = c.clean_paragraphs(["\ue800\ue800\ue801\ue801，测试。"], chapter_index=1)
    assert out == ["中中文文，测试。"]


# ---------- 反爬判定 ----------
from ebookmaker.ratelimit import DomainLimiter


def test_blocked_body_requires_short_page():
    # 真实验证码页：短 + 命中特征
    assert DomainLimiter.is_blocked_body("<html>请进行人机验证</html>") is True
    # 长正文里内嵌防抓文案/JS：不得误判（旧实现即在此误报冷却）
    long_page = "<title>第1章</title><div>" + "正常章节正文，提到安全验证等字样。" * 300 + "</div>"
    assert DomainLimiter.is_blocked_body(long_page) is False
    assert DomainLimiter.is_blocked_body("") is True


# ---------- AIMD 自适应速率 ----------
def test_limiter_aimd_backoff_dedup_and_recover():
    lim = DomainLimiter(rate_per_sec=4.0, burst=2, cooldown_on_block=20.0,
                        min_rate=0.25, succeed_after=4)
    url = "https://site.test/1.html"
    host = "site.test"
    lim.penalize(url)                       # 乘性减 4→2
    assert abs(lim.rate - 2.0) < 1e-6
    lim.penalize(url)                       # 同一冷却窗口内重复命中 → 去重不叠加
    assert abs(lim.rate - 2.0) < 1e-6
    lim._bucket(host)[2] = 0.0              # 冷却窗口过期
    lim.penalize(url)                       # 第二次独立惩罚 → 再减半 2→1
    assert abs(lim.rate - 1.0) < 1e-6
    # strikes 递增使冷却变长（第2次 4s，而非首次 2s）
    import time
    deadline = lim._bucket(host)[2]
    assert 3.0 <= deadline - time.monotonic() <= 5.5
    # 窗口内的显式 Retry-After 命中：不叠加降速（旧 bug），只延长冷却窗口
    lim._bucket(host)[2] = time.monotonic() + 1.0   # 把窗口重置为还剩 1s
    before_rate = lim.rate
    lim.penalize(url, seconds=6.0)
    assert abs(lim.rate - before_rate) < 1e-6
    assert lim._bucket(host)[2] - time.monotonic() > 5.0   # 窗口被 Retry-After 延长
    # 单次成功不清 strikes，回升步进才清
    for _ in range(3):
        lim.succeed(url)
    assert lim._bucket(host)[3] == 2
    lim.succeed(url)
    assert lim._bucket(host)[3] == 0
    assert lim.rate > 1.0                   # 回升 +30%


def test_limiter_succeed_recovers_rate():
    lim = DomainLimiter(rate_per_sec=5.0, succeed_after=4)
    lim.penalize("https://site.test/a")
    assert lim.rate < 5.0
    for _ in range(4):
        lim.succeed("https://site.test/a")  # succeed_after=4 → 一次回升
    assert lim.rate > 2.5                   # 2.5 * 1.3
    for _ in range(40):
        lim.succeed("https://site.test/a")
    assert lim.rate <= 5.0 + 1e-9           # 不超过配置上限


def test_limiter_explicit_seconds_priority():
    lim = DomainLimiter(rate_per_sec=4.0, cooldown_on_block=20.0)
    lim.penalize("https://site.test/a", seconds=1.0)
    import time
    deadline = lim._bucket("site.test")[2]
    assert 0 < deadline - time.monotonic() <= 1.5   # 尊重 Retry-After 小值


def test_limiter_capacity_convergence():
    """撞墙后记住天花板：回升不越过已证不安全区域，反复惩罚后 capacity 单调收敛。"""
    lim = DomainLimiter(rate_per_sec=5.0, burst=2, cooldown_on_block=20.0,
                        min_rate=0.3, succeed_after=4)
    url = "https://s.test/1"
    prev_cap = lim.capacity
    for _ in range(3):
        lim._bucket("s.test")[2] = 0.0        # 惩罚窗口过期（独立命中）
        lim.penalize(url)
        assert lim.rate <= lim.capacity
        for _ in range(40):                    # 充分回升
            lim.succeed(url)
        assert lim.rate <= lim.capacity + 1e-9  # 天花板锁死，不再越限撞墙
        assert lim.capacity < prev_cap          # 每次撞墙天花板下收
        prev_cap = lim.capacity
    # 三轮后：5→4.5→4.05→3.645 收敛在阈值下方
    assert 3.4 < lim.capacity < 4.6


# ---------- http_client 接 Retry-After / succeed ----------
class _FakeResp:
    def __init__(self, status, headers=None, content=b"ok body"):
        self.status_code = status
        self.headers = headers or {}
        self.content = content
        self.encoding = "utf-8"

    @property
    def apparent_encoding(self):
        return "utf-8"


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)

    def get(self, url, **kw):
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def close(self):
        pass


class _RecordingLimiter:
    def __init__(self):
        self.penalized = []
        self.succeeded = 0

    def acquire(self, url):
        pass

    def penalize(self, url, seconds=None):
        self.penalized.append(seconds)

    def succeed(self, url):
        self.succeeded += 1


def test_http_client_respects_retry_after_and_reports_success():
    from ebookmaker.config import FetchConfig
    from ebookmaker.http_client import HttpClient

    cfg = FetchConfig()
    cfg.jitter_min = cfg.jitter_max = 0.0
    cfg.backoff_base = 0.01
    client = HttpClient(cfg, limiter=None)
    limiter = _RecordingLimiter()
    client.limiter = limiter
    fake = _FakeSession([_FakeResp(429, {"retry-after": "0.5"}), _FakeResp(200)])
    client._session = lambda: fake
    resp = client.get("https://site.test/ch/1.html")
    assert resp.status == 200
    assert limiter.penalized == [0.5]     # Retry-After 被解析并传给 penalize
    assert limiter.succeeded == 1         # 成功后回报升速


# ---------- 日志与进度条共存 ----------
def _attach_handler(logger, stream):
    """把进度感知 handler 绑到指定 logger（输出到我们捕获的 stream）。"""
    import logging
    from ebookmaker.log import _ProgressAwareHandler
    handler = _ProgressAwareHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return handler


def test_log_handler_calls_hooks():
    import logging
    from ebookmaker.log import set_progress_hooks
    calls = {"clear": 0, "redraw": 0}
    set_progress_hooks(lambda: calls.__setitem__("clear", calls["clear"] + 1),
                       lambda: calls.__setitem__("redraw", calls["redraw"] + 1))
    try:
        stream = io.StringIO()
        logger = logging.getLogger("ebookmaker.test.hooks")
        _attach_handler(logger, stream)
        logger.warning("一条日志")
        assert calls["clear"] == 1 and calls["redraw"] == 1
        assert "一条日志" in stream.getvalue()
    finally:
        set_progress_hooks(clear=None, redraw=None)


def test_progress_single_line_with_logs(monkeypatch):
    """TTY 下日志不会把进度条顶成多行：日志前擦行、后重绘，最终只有一行进度。"""
    import logging
    import sys as _sys
    from ebookmaker.downloader import Progress
    from ebookmaker.log import set_progress_hooks

    class FakeTTY(io.StringIO):
        def isatty(self):
            return True
    stream = FakeTTY()
    monkeypatch.setattr(_sys, "stdout", stream)
    p = Progress(10)  # 自动注册 clear/redraw 钩子

    logger = logging.getLogger("ebookmaker.t")
    _attach_handler(logger, stream)
    p.bump(3)
    logger.warning("触发反爬，冷却 20s")
    import time as _t
    _t.sleep(0.22)          # 越过绘制节流窗口，模拟真实下载节奏
    p.bump(4)
    p.finish()
    out = stream.getvalue()
    assert "触发反爬" in out
    # 日志行自带换行 + finish 换行 == 2 个 \n；若旧实现（日志插在 \r 行后）会产生错位长行
    assert out.count("\n") == 2
    assert "70.0%" in out          # 节流窗口后的重绘到了 7/10
    assert out.rstrip("\n").splitlines()[-1].lstrip().startswith("下载")  # 进度始终独占一行
    set_progress_hooks(clear=None, redraw=None)


# ---------- 进度对象 ----------
def test_progress_non_tty_no_crash():
    p = Progress(100)
    p._tty = False
    for _ in range(100):
        p.bump()
    p.finish()
    assert p.done == 100


def test_progress_tty_draws_bar(monkeypatch):
    import sys
    class FakeTTY(io.StringIO):
        def isatty(self):
            return True
    stream = FakeTTY()
    monkeypatch.setattr(sys, "stdout", stream)
    p = Progress(4)
    for _ in range(4):
        p.bump()
    p.finish()
    out = stream.getvalue()
    assert "\r" in out and "100.0%" in out and "章/秒" in out


# ---------- onclick 跳转式目录 + 数字目录分页（woyaodu 实测形态） ----------
def _wyd_dir_page(base="/xiaoshuo/842/842172"):
    """目录分页页：章节链接是 <a onclick=location.href>，页码在 select option。"""
    chs = "".join(
        '<dd><a onclick="location.href=\'{}/{}.html\'">第{}章 标题{}</a></dd>'.format(base, 182801292 + i, i, i)
        for i in range(1, 41))
    opts = "".join('<option value="{}/{}">{}</option>'.format(base, i, i) for i in range(1, 13))
    nxt = '<a href="javascript:;" onclick="location.href=\'{}/2/\'">下一页</a>'.format(base)
    return '<html><body><dl class="panel-chapterlist">{}</dl><select>{}</select>{}</body></html>'.format(
        chs, opts, nxt)


def test_parse_toc_reads_onclick_chapter_links():
    site = GenericSite()
    toc = site.parse_toc(_wyd_dir_page(), "https://w.test/xiaoshuo/842/842172/1/")
    assert len(toc) == 40
    assert toc[0].href.endswith("182801293.html")


def test_series_pages_numeric_dir_with_numeric_labels():
    urls = find_series_pages(_wyd_dir_page(), "https://w.test/xiaoshuo/842/842172/1/")
    # 兄弟页 /2/ ../ /12/ 全部发现，/1/ 自指排除
    assert len(urls) == 11
    assert "https://w.test/xiaoshuo/842/842172/2/" in urls
    assert "https://w.test/xiaoshuo/842/842172/1/" not in urls


def test_numeric_dir_page_not_confused_with_chapter_docs():
    # 正文页里的 /base/12345.html 章节链接与裸 /base/99999/（非数字短标签）不能误当分页
    html = ('<a href="/xiaoshuo/842/842172/182801293.html">第1章 开头</a>'
            '<a href="/xiaoshuo/842/842172/99999/">这是一章正文链接的标题文字</a>')
    urls = find_series_pages(html, "https://w.test/xiaoshuo/842/842172/")
    assert urls == []


def test_collect_series_pages_walks_numeric_dir_pagination():
    base = "/xiaoshuo/842/842172"

    def get_html(url):
        n = int(url.rstrip("/").rsplit("/", 1)[1])
        opts = "".join('<option value="{}">{}</option>'.format(base + "/" + str(i), i)
                       for i in range(1, 13)) if n == 1 else \
               '<option value="{}">{}</option>'.format(base + "/" + str(n - 1), n - 1)
        chs = "".join('<a onclick="location.href=\'{}\'">第{}章 x</a>'.format(
            base + "/{}.html".format(n * 100 + k), n * 100 + k) for k in range(1, 6))
        return "<html><body><dl>{}</dl><select>{}</select></body></html>".format(chs, opts)

    pages = collect_series_pages(get_html(base + "/1/"), "https://w.test" + base + "/",
                                 get_html)
    got = [u for u, _ in pages]
    assert "https://w.test" + base + "/2/" in got
    assert len(got) >= 2   # 首页→/1/ 种子→逐页展开
