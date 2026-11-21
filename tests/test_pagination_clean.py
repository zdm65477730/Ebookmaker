# -*- coding: utf-8 -*-
"""分页章节三重锚定解析 + 序列探针 + verify 审核 测试。

模拟 bqg2 类站点：章节拆成 stem_2/_3/_4 多页，每页头部带
“第N章 标题（K/M）”行、尾部带“本章未完/本章已完成”与挂件块。
"""

import json
import re

from ebookmaker.cleaner import Cleaner
from ebookmaker.config import AppConfig, CleanerConfig
from ebookmaker.downloader import Crawler, Progress
from ebookmaker.http_client import FetchError
from ebookmaker.models import TocEntry
from ebookmaker.sites.generic import GenericSite
from ebookmaker.store import BookStore
from ebookmaker import cli

BOOK = "https://novel.fake.cn/book/999/"
TITLE = "第2章 没有路引可不行！"

# 每页正文唯一且总量过质量闸（合成数据段落完全相同会被重复守护当循环页）
PAGE_CONTENT = [
    ["第2章 没有路引可不行！（1/4）",
     "陆辰脸色微变，不过很快就恢复了正常，心里却在飞速盘算着眼前的局面，究竟是谁走漏了风声。",
     "自己身上有什么东西，陆辰再清楚不过了，一身粗布旧衣，除了贴身内袋里的那点碎银，实在身无长物。",
     "本章未完，请翻下一页继续阅读.........",
     "神豪从打赏主播两亿开始", "夺嫡在嘉靖朝", "先婚后爱"],
    ["第2章 没有路引可不行！（2/4）",
     "两名劫匪对视一眼，缓缓抽出了短刀，眼中露出凶光，刀身在烛光下泛着寒意。",
     "陆辰后退半步，目光扫过窗棂与门槛之间的距离，心里迅速有了计较，若真动手该往哪个方向避。",
     "本章未完，请翻下一页继续阅读........."],
    ["第2章 没有路引可不行！（3/4）",
     "巷子里传来更鼓声，夜色重新安静下来，只剩风声穿过屋檐，吹得窗纸哗啦作响。",
     "他收起银票，心中盘算着明日的安排，握紧了拳头，这件事必须赶在天亮前找到应对的法子。",
     "本章未完，请翻下一页继续阅读........."],
    ["第2章 没有路引可不行！（4/4）",
     "天亮后还得去衙门报备，眼下先回住处从长计议，把今晚的每一个细节都先理清楚。",
     "这一夜无话，次日清晨陆辰便被急促的敲门声惊醒，披衣开门时，门外站着一位不速之客。",
     "本章已完成！"],
]


def _page_body(paras):
    return '<div class="showtxt">' + "".join("<p>" + p + "</p>" for p in paras) + "</div>"


def make_site(pageno, total):
    """当前页 HTML：正文 + 相邻页链接（首页同时渲染 _3，排前诱导跳页，模拟真实模板）。"""
    links = ['<a href="3.html">下一章</a>']
    if pageno < total:
        links.append('<a href="2_{}.html">下一页</a>'.format(pageno + 1))
        if pageno == 1:
            links.insert(0, '<a href="2_3.html">3</a>')
    if pageno > 1:
        links.append('<a href="2_{}.html">上一页</a>'.format(pageno - 1))
    return ("<html><head><title>{}（{}/{}）</title></head><body>".format(TITLE, pageno, total)
            + _page_body(PAGE_CONTENT[pageno - 1])
            + '<div class="readpage">' + "".join(links) + "</div>"
            + "</body></html>")


class FakeHttp:
    """支持序列分页（2 / 2_2..2_4）与无链接翻页章节（3.html 纯文本提示翻页）。"""

    def get(self, url, referer=None, **kw):
        class R:
            def __init__(self, text):
                self.text = text

        path = url.split(BOOK)[-1] if url.startswith(BOOK) else url
        m = re.fullmatch(r"2(?:_(\d))?\.html", path)
        if m:
            k = int(m.group(1) or 1)
            if 1 <= k <= 4:
                return R(make_site(k, 4))
            raise FetchError("404 " + url)
        if path == "3.html":   # 有下一页但页面不提供链接，只能靠序列探针
            return R('<html><head><title>第3章 这身份能用！</title></head><body>'
                     + _page_body(["这身份能用，陆辰在心里反复咀嚼着这几个字，连他自己都觉得有些不可思议，这路引上的名字分明与他毫无关系，可笔迹印鉴却做不得假。",
                                   "可正当他准备出门时，院门突然被推开了，来人站在晨光里看不真切面孔，只消一袭青衫落在他的眼里，站定了却没有说话。",
                                   "本章未完，请翻下一页继续阅读........."]) + "</body></html>")
        if path == "3_2.html":
            return R('<html><head><title>第3章 这身份能用！(2)</title></head><body>'
                     + _page_body(["第3章 这身份能用！（2/2）",
                                   "来人是他前世在锦衣卫的旧识，此番专程来报信，神色间满是急切，连寒暄都顾不上了。",
                                   "对方压低声音说了一件让他脊背发凉的事，此事牵连之广远超他的想象，一个不小心便是灭顶之灾。",
                                   "本章已完成！"]) + "</body></html>")
        if path == "4.html":   # 单页章：探针 _2 命中“软404 返回首页”（混入即被断言捕获）
            return R('<html><head><title>第4章 独一章</title></head><body>'
                     + _page_body(["独一章的内容，正常结束于此处，前后两代的恩怨至此总算有了个交代。",
                                   "陆辰推窗远眺，城外的田野一片金黄，今年的秋收看来是不差的。",
                                   "本章已完成！"])
                     + "</body></html>")
        if path == "4_2.html":
            return R('<html><head><title>新書推薦</title></head><body>'
                     + _page_body(["新書推薦",
                                   "随机推荐内容，并不是第4章的一部分，它读起来像是一段完全不同的故事开头。",
                                   "倘若这段文字出现在成品里，说明探针把软404页面的文字误并进了正文，属于归属校验失效。",
                                   "本段存在的意义就是让误并后的字数超过质量闸与断言阈值，从而被测试捕获。"]) + "</body></html>")
        raise FetchError("404 " + url)


def make_crawler(tmp_path, cfg=None):
    cfg = cfg or AppConfig()
    cfg.fetch.jitter_min = cfg.fetch.jitter_max = 0.0
    store = BookStore(str(tmp_path / "书"))
    crawler = Crawler(cfg, store, GenericSite(), FakeHttp(), Cleaner(cfg.cleaner))
    crawler.progress = Progress(1)
    return crawler, store


# ---------- clean_page 三重锚定 ----------
def test_clean_page_cuts_at_marker_and_drops_junk():
    c = Cleaner(CleanerConfig())
    out, needs = c.clean_page(PAGE_CONTENT[0], title=TITLE)
    assert needs is True
    assert not any("本章未完" in p for p in out)
    assert "神豪从打赏主播两亿开始" not in out  # 页尾标记之后的挂件随截断一并丢弃
    assert out[0].startswith("陆辰脸色微变")


def test_clean_page_end_marker_no_continuation():
    c = Cleaner(CleanerConfig())
    out, needs = c.clean_page(PAGE_CONTENT[3], title=TITLE)
    assert needs is False
    assert not any("本章已完成" in p for p in out)
    assert any("敲门声" in p for p in out)


# ---------- 序列探针 URL 形态 ----------
def test_probe_url_forms():
    assert Crawler._probe_url("https://x.com/a/2.html", 3) == "https://x.com/a/2_3.html"
    assert Crawler._probe_url("https://x.com/a/2_1.html", 3) == "https://x.com/a/2_3.html"
    assert Crawler._probe_url("https://x.com/a/2-1.html", 2) == "https://x.com/a/2_2.html"
    assert Crawler._probe_url("https://x.com/a/31/4/", 2) == "https://x.com/a/31/4/2/"
    assert Crawler._probe_url("https://x.com/a/31/4_2/", 3) == "https://x.com/a/31/4/3/"


def test_page_num():
    assert Crawler._page_num("https://x/a/2.html", "https://x/a/2.html") == 1
    assert Crawler._page_num("https://x/a/2_3.html", "https://x/a/2.html") == 3
    assert Crawler._page_num("https://x/a/4/2/", "https://x/a/4/") == 2


# ---------- 跳页链接链：序列探针补齐被跳过的页 ----------
def test_pagination_merges_all_four_pages_no_gap(tmp_path):
    crawler, store = make_crawler(tmp_path)
    toc = [TocEntry(href="2.html", title=TITLE)]
    assert crawler._fetch_one(1, toc[0], BOOK) is True
    ch = store.load_chapter(1)
    joined = "".join(ch.paragraphs)
    for frag in ["陆辰脸色微变", "两名劫匪", "更鼓声", "敲门声"]:
        assert frag in joined
    assert joined.index("陆辰脸色微变") < joined.index("两名劫匪") \
        < joined.index("更鼓声") < joined.index("敲门声")
    assert "本章未完" not in joined and "本章已完成" not in joined
    assert "神豪从打赏" not in joined
    assert "没有路引可不行" not in joined


# ---------- 无链接翻页：纯文本提示 + 探针 ----------
def test_pagination_probe_without_links(tmp_path):
    crawler, store = make_crawler(tmp_path)
    toc = [TocEntry(href="3.html", title="第3章 这身份能用！")]
    assert crawler._fetch_one(1, toc[0], BOOK) is True
    joined = "".join(store.load_chapter(1).paragraphs)
    assert "脊背发凉" in joined      # 第二页靠序列探针拼上
    assert "旧识" in joined
    assert "本章未完" not in joined


# ---------- 软404首页陷阱：归属校验防误并 ----------
def test_probe_rejects_soft404_foreign_page(tmp_path):
    cfg = AppConfig()
    cfg.fetch.jitter_min = cfg.fetch.jitter_max = 0.0
    cfg.cleaner.min_chapter_len = 10   # 本章源站本就只有一小段，降低关卡以隔离归属校验断言
    crawler, store = make_crawler(tmp_path, cfg)
    toc = [TocEntry(href="4.html", title="第4章 独一章")]
    assert crawler._fetch_one(1, toc[0], BOOK) is True
    joined = "".join(store.load_chapter(1).paragraphs)
    assert "正常结束于此处" in joined
    assert "随机推荐内容" not in joined   # 探针候选未通过归属校验，不混入


# ---------- verify 审核 ----------
def _write_workspace(tmp_path, chapters):
    root = tmp_path / "书"
    (root / "chapters").mkdir(parents=True)
    (root / "meta.json").write_text(json.dumps({
        "title": "测试书", "author": "作者", "source_url": BOOK,
        "publisher": "p", "category": "c", "description": "", "rights": "",
        "update_time": "", "cover_url": "", "site": ""}), encoding="utf-8")
    (root / "toc.json").write_text(json.dumps(
        [{"href": "{}.html".format(i), "title": "第{}章".format(i)} for i in chapters]),
        encoding="utf-8")
    for idx, paras in chapters.items():
        (root / "chapters" / "{:05d}.json".format(idx)).write_text(json.dumps({
            "index": idx, "title": "第{}章".format(idx), "url": BOOK + "{}.html".format(idx),
            "paragraphs": paras, "status": "ok", "problems": []}), encoding="utf-8")
    return str(root)


GOOD = ["正常的叙事段落，内容足够长以通过检查，细节描写也比较充分。" * 2,
        "另一段情节，同样带句号结尾，叙述平稳推进没有异常。" * 2]


def test_verify_pass(tmp_path):
    root = _write_workspace(tmp_path, {1: GOOD, 2: GOOD, 3: GOOD})
    assert cli.cmd_verify(AppConfig(), root) == 0


def test_verify_detects_residue_and_empty(tmp_path):
    root = _write_workspace(tmp_path, {
        1: GOOD,
        2: GOOD + ["神豪从打赏主播两亿开始", "夺嫡在嘉靖朝", "先婚后爱", "丧尸专列"],  # 推荐块
        3: [],                                                # 空章
        4: GOOD + ["本章未完，请翻下一页继续阅读........."],      # 页尾标记残留
    })
    rc = cli.cmd_verify(AppConfig(), root)
    assert rc == 2   # FAIL
