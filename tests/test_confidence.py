# -*- coding: utf-8 -*-
"""章节级置信闸门 + 双抽取器一致度 测试。"""

import json

from ebookmaker.cleaner import Cleaner
from ebookmaker.config import AppConfig, CleanerConfig
from ebookmaker.downloader import Crawler, Progress
from ebookmaker.http_client import FetchError
from ebookmaker.models import TocEntry
from ebookmaker.sites.generic import GenericSite
from ebookmaker.store import BookStore

PROSE = ["洛一宁把笔搁下，指尖还沾着未干的墨。窗外的雪不知何时停了，廊下传来\n"
         "轻微的踩踏声，像是有人刻意放轻了脚步。"] * 2
PROSE = [p for p in PROSE]
LONG_PROSE = [
    "洛一宁把笔搁下，指尖还沾着未干的墨，窗外的雪不知何时才停下来的。",
    "廊下传来轻微的踩踏声，像是有人刻意放轻了脚步，在阶前站了片刻。",
    "他没有抬头，只将画稿上最后一道山脊的轮廓描完，才缓缓吐出白气。",
    "门被推开半尺，冷气卷着雪沫扑进来，烛火晃了晃，映得墙上影子摇摆不定。",
    "来人在门口跺了跺脚上的雪，抖开大氅，眉眼间还带着城外冻出来的红。",
    "事情办妥了，那人压低声音，只是对方似乎起了疑心，后头怕是有得麻烦。",
    "洛一宁听完并未立刻答话，而是将笔洗净悬好，才慢慢转过身来。",
    "他沉吟片刻，此事需从长计议，仓促应对只会把线索彻底断送干净。",
    "窗外天色将明未明，院中积雪映出微光，两人低声计议了许久。",
    "最终他一拍桌案，就这么办，迟则生变的道理，对方应该比他更清楚。",
]
RECS = ["神豪从打赏主播两亿开始", "夺嫡在嘉靖朝", "先婚后爱", "丧尸专列", "万古第一神"]


def make_cleaner():
    return Cleaner(CleanerConfig())


def test_confidence_high_for_clean_prose():
    conf, problems = make_cleaner().chapter_confidence(LONG_PROSE, title="第9章 雪夜来客")
    assert conf >= 0.7, (conf, problems)


def test_confidence_penalizes_rec_blocks_and_ads():
    dirty = LONG_PROSE + RECS + ["本站牢记地址 www.bqg2xx.com 每日更新最新章节"]
    clean_conf, _ = make_cleaner().chapter_confidence(LONG_PROSE)
    dirty_conf, problems = make_cleaner().chapter_confidence(dirty)
    assert dirty_conf < clean_conf
    assert any("噪声" in p for p in problems)


def test_confidence_zero_when_empty():
    conf, problems = make_cleaner().chapter_confidence([])
    assert conf == 0.0 and problems == ["无正文"]


def test_dialogue_heavy_not_falsely_flagged():
    # 对话体：引号内句号使自然密度仍达标，不应被判低置信
    dial = [
        "“你去还是我去？”他问。",
        "“我不去，”她冷笑，“去了也是送死。”",
        "“那便由我去。”他抓起长刀，头也不回地走了出去。",
        "“小心！”她的声音被风撕碎，只余雪地上的脚印延伸向城外。",
        "他当然听见了，只是脚下的步子并没有因此停下来半分而已。",
        "夜色浓重如墨，前方的官道上空无一人，唯有马蹄声急促如鼓点。",
        "他不敢停下，也不敢回头，怀里的密信仿佛烧红的铁一般烫。",
        "城外的破庙是他和同伴约定的汇合之处，尽管谁都知道多半是陷阱。",
        "“陷阱也得闯。”他低声自语，语气里带着连自己都不信的轻松。",
        "庙门虚掩，香案上的烛火竟然还亮着，说明先前有人来过此处。",
    ]
    conf, problems = make_cleaner().chapter_confidence(dial, title="第3章 雪夜行")
    assert conf >= 0.6, (conf, problems)


# ---------- 双抽取器一致度 & 低置信自动补抓 ----------
class OnePageHttp:
    def __init__(self, chapter_html):
        self.chapter_html = chapter_html

    def get(self, url, referer=None, **kw):
        class R:
            def __init__(self, text):
                self.text = text
        if url.endswith("1.html"):
            return R(self.chapter_html)
        raise FetchError("404 " + url)


def _html_in(paras):
    return ('<html><body><div class="showtxt">'
            + "".join("<p>{}</p>".format(p) for p in paras) + "</div></body></html>")


def _make(tmp_path, http):
    cfg = AppConfig()
    cfg.fetch.jitter_min = cfg.fetch.jitter_max = 0.0
    store = BookStore(str(tmp_path / "书"))
    crawler = Crawler(cfg, store, GenericSite(), http, Cleaner(cfg.cleaner))
    crawler.progress = Progress(1)
    return crawler, store


def test_garbage_page_rejected_by_gate(tmp_path):
    # 清洗也救不回的页面（乱码/过短/无叙事特征）：置信闸门应拦截，不落盘，进补爬队列
    garbage = ["错误页面\ue800\ue801" * 3, "\ue802\ue803加载失败\ue804\ue805", "\ue806重试\ue807\ue808"]
    crawler, store = _make(tmp_path, OnePageHttp(_html_in(garbage)))
    ok = crawler._fetch_one(1, TocEntry(href="1.html", title="第1章 起风了"), "https://x.b/1.html")
    assert ok is False
    assert not store.has_valid_chapter(1)   # 未存为有效章，下轮会重抓


def test_clean_prose_passes_gate(tmp_path):
    # 清洗链已把挂件删净的正常章：闸门放行且置信高
    dirty = LONG_PROSE + RECS * 8 + ["记住本站 www.bqg2xx.com 每日更新最新章节"]
    crawler, store = _make(tmp_path, OnePageHttp(_html_in(dirty)))
    ok = crawler._fetch_one(1, TocEntry(href="1.html", title="第1章 雪夜来客"), "https://x.b/1.html")
    assert ok is True
    saved = json.load(open(store.chapter_path(1), encoding="utf-8"))
    assert saved["confidence"] >= 0.6
    assert not any("神豪" in p for p in saved["paragraphs"])  # 挂件已被清洗链删除


def test_good_chapter_saved_with_high_confidence(tmp_path):
    crawler, store = _make(tmp_path, OnePageHttp(_html_in(LONG_PROSE)))
    ok = crawler._fetch_one(1, TocEntry(href="1.html", title="第1章 雪夜来客"), "https://x.b/1.html")
    assert ok is True
    saved = json.load(open(store.chapter_path(1), encoding="utf-8"))
    assert saved["confidence"] >= 0.6


def test_agreement_returned_by_extract(tmp_path):
    crawler, _ = _make(tmp_path, OnePageHttp(_html_in(LONG_PROSE)))
    lines, agree = crawler._extract_full_chapter(
        _html_in(LONG_PROSE), "https://x.b/1.html", "https://x.b/", title="第1章")
    assert lines and 0.0 <= agree <= 1.0
