# -*- coding: utf-8 -*-
"""通用/generic 解析与注册表测试（离线夹具，内置适配器已移除）。"""

import os

from ebookmaker.sites.generic import GenericSite
from ebookmaker.sites.registry import all_adapters, get_adapter

BOOK_URL = "https://www.xbiquge.la/66/66747/"


def test_generic_meta(fixture_html):
    html = fixture_html("raw/xbiquge_toc.html")
    meta = GenericSite().parse_meta(html, BOOK_URL)
    assert meta.title == "测试书籍"
    assert meta.author == "测试作者"
    assert meta.category == "玄幻"
    assert meta.update_time == "2026-01-01 08:00:00"
    assert meta.cover_url.startswith("https://www.xbiquge.la/")
    assert "测试" in meta.description


def test_generic_toc_sorted_deduped(fixture_html):
    html = fixture_html("raw/xbiquge_toc.html")
    toc = GenericSite().parse_toc(html, BOOK_URL)
    titles = [t.title for t in toc]
    # “返回书页”非章节链接被过滤
    assert "返回书页" not in titles
    # 重复的第2章只保留一个
    assert titles.count("第2章 觉醒") == 1
    # 前 8 条按章号升序
    nums = [t.number for t in toc[:8]]
    assert nums == list(range(1, 9))
    # 无“第N章”的前言按 URL 尾号排在最后
    assert toc[-1].title == "前言致谢"


def test_generic_toc_relative_href(fixture_html):
    html = fixture_html("raw/ptwxz_toc.html")
    site = GenericSite()
    toc = site.parse_toc(html, "https://www.yexiashuge.com/book/4160/")
    nums = [t.number for t in toc]
    assert nums == list(range(1, 8))
    url = site.chapter_url("https://www.yexiashuge.com/book/4160/", toc[0].href)
    assert url == "https://www.yexiashuge.com/book/4160/chapter/4576742.html"


def test_generic_chapter_raw_lines(fixture_html):
    html = fixture_html("raw/xbiquge_chapter.html")
    lines = GenericSite().parse_chapter(html, BOOK_URL)
    joined = "\n".join(lines)
    # 原始行仍包含广告/水印（净化由 cleaner 负责）
    assert "笔趣阁" in joined
    assert "嗡！" in joined


def test_generic_chapter_density_fallback():
    chapter = """
    <html><body>
    <div class="bar">广告位</div>
    <div class="chapter-content">
    &nbsp;&nbsp;深夜的皇城安静而肃穆，宫墙之内灯火稀疏，唯有御书房中还亮着灯。
    <br />
    &nbsp;&nbsp;“陛下，边关八百里加急！”太监尖细的声音在殿外响起，随即是急促的脚步声。
    <br />
    &nbsp;&nbsp;皇帝放下朱笔，接过奏报，脸色骤变。这一夜，注定无人安眠。
    </div>
    </body></html>"""
    lines = GenericSite().parse_chapter(chapter, "https://novel.example.org/book/1/5.html")
    assert "边关八百里加急" in "".join(lines)


# ---------- 注册表 ----------
def test_registry_no_adapters_falls_back_to_generic():
    # 包内不再有内置适配器/描述符
    assert all_adapters() == []
    site = get_adapter("https://any.site/book/1/")
    assert isinstance(site, GenericSite)


def test_registry_uses_user_descriptor(tmp_path):
    yaml_text = """
name: mysite
type: site
hosts: [novel.mysite.cn]
content:
  selector: "#txt"
"""
    rules_dir = str(tmp_path)
    with open(os.path.join(rules_dir, "mysite.yaml"), "w", encoding="utf-8") as fp:
        fp.write(yaml_text)
    site = get_adapter("https://novel.mysite.cn/b/1/", extra_rules_dirs=[rules_dir])
    assert site.name == "mysite"
    # host 未命中仍回 generic
    assert isinstance(get_adapter("https://other.cn/", extra_rules_dirs=[rules_dir]),
                      GenericSite)


def _toc(entries):
    from ebookmaker.models import TocEntry
    from ebookmaker.sites.base import normalize_toc
    return normalize_toc([TocEntry(href=h, title=t) for h, t in entries])


def test_normalize_toc_duplicate_and_typo_rescue():
    # 真实场景：bqg2 “最新章节”模块跨页重复 5 次（同 href）；
    # 336.html 标题笔误写成“第366章”，挤掉了真的 366.html
    base = "/html/490/490651/"
    entries = []
    for n in range(1, 367):           # 1..366 正常；336 的标题被写错成 366
        title = "第366章 明知是陷阱" if n == 336 else "第%d章 正文" % n
        entries.append((base + "%d.html" % n, title))
    entries.append((base + "366.html", "第366章 情况完全不同"))
    # 真正的 366 在列表里排在笔误条目之后
    entries = entries[:335] + [entries[335]] + entries[336:]
    entries = sorted(entries, key=lambda e: int(e[0].rsplit("/", 1)[1].split(".")[0]))
    entries[335] = (base + "336.html", "第366章 明知是陷阱")   # 笔误
    entries[365] = (base + "366.html", "第366章 情况完全不同")
    # 重复展示：最后 9 章整段再来一遍（同 href）
    entries += [e for e in entries if int(e[0].rsplit("/", 1)[1].split(".")[0]) > 357]
    toc = _toc(entries)
    hrefs = [e.href for e in toc]
    assert len(toc) == 366                      # 不多不少：336 与 366 都在
    assert base + "336.html" in hrefs and base + "366.html" in hrefs
    n366 = [e for e in toc if e.href.endswith("366.html")]
    assert n366[0].title == "第366章 情况完全不同"  # 真 366 不被笔误条目顶掉
    assert len(hrefs) == len(set(hrefs))        # 重复展示已消除


def test_normalize_toc_random_url_ids_unaffected():
    # woyaodu 形态：URL 尾号是随机长号，章节顺序全凭标题序号，不受救援影响
    entries = [("/xiaoshuo/842/842172/%d.html" % (182801290 + i), "第%d章 x" % i)
               for i in range(1, 6)]
    toc = _toc(entries)
    assert [e.title for e in toc] == ["第%d章 x" % i for i in range(1, 6)]
