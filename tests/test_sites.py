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
