# -*- coding: utf-8 -*-
"""EPUB 生成结构校验。"""

import os
import zipfile
from xml.dom import minidom

from ebookmaker.builders.epub import book_uuid, build_epub
from ebookmaker.cleaner import Cleaner
from ebookmaker.config import CleanerConfig
from ebookmaker.models import BookMeta, ChapterData
from ebookmaker.store import BookStore

BOOK_TEXT = ("夜色如墨，秦尘盘膝而坐。" * 30).replace("”", '"')  # 含需转义字符


def make_store(tmp_path):
    store = BookStore(str(tmp_path / "books" / "测试书"))
    meta = BookMeta(title="测试书", author="张三 & 李四", description="一本<tricky>的书",
                    source_url="http://a/", language="zh-CN")
    store.save_meta(meta)
    store.save_toc([])
    store.save_chapter(ChapterData(index=1, title='第1章 "开端"', url="http://a/1",
                                   paragraphs=[BOOK_TEXT, '他低声道：“今天&明天<见。”',
                                               "本站牢记地址，每天更新！"]))
    store.save_chapter(ChapterData(index=2, title="第2章 转折", url="http://a/2",
                                   paragraphs=[BOOK_TEXT, "本站牢记地址，每天更新！"]))
    return store


def test_epub_structure(tmp_path):
    store = make_store(tmp_path)
    store.save_junk_lines(["本站牢记地址，每天更新！"])
    out = str(tmp_path / "out.epub")
    build_epub(store, out, Cleaner(CleanerConfig()))

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        # 规范：mimetype 必须为首个条目且 STORED
        assert names[0] == "mimetype"
        assert zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"

        expected = ["META-INF/container.xml", "OEBPS/content.opf", "OEBPS/toc.ncx",
                    "OEBPS/nav.xhtml", "OEBPS/style.css",
                    "OEBPS/cover.jpg", "OEBPS/title.xhtml",
                    "OEBPS/book-toc.xhtml", "OEBPS/chapter00001.xhtml",
                    "OEBPS/chapter00002.xhtml"]
        for name in expected:
            assert name in names, "缺少 " + name
        # 封面不再自带 cover.xhtml 页（交由 Kindle/Calibre 从 cover-image 生成唯一全屏封面）
        assert "OEBPS/cover.xhtml" not in names

        # XML 良构
        for name in ["OEBPS/content.opf", "OEBPS/toc.ncx", "OEBPS/nav.xhtml",
                     "OEBPS/chapter00001.xhtml", "META-INF/container.xml"]:
            minidom.parseString(zf.read(name))

        ch1 = zf.read("OEBPS/chapter00001.xhtml").decode("utf-8")
        # 广告行经 junk_lines 二次过滤
        assert "本站牢记地址" not in ch1
        # 特殊字符正确转义
        assert "&amp;" in ch1 and "“今天" in ch1

        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert book_uuid("测试书") in opf
        assert "张三 &amp; 李四" in opf
        # 封面必含：即使工作区没有站点封面，也用内置默认封面；
        # 封面以 EPUB3 cover-image 属性声明（非独立封面页，避免与 Calibre 生成页重复）
        assert 'id="cover-image"' in opf and 'properties="cover-image"' in opf
        assert '<meta name="cover"' in opf
        assert '<itemref idref="cover"' not in opf  # spine 不再包含自带封面页
        assert zf.read("OEBPS/cover.jpg")  # 默认封面图片已打入
        # 目录/章节齐备
        toc = zf.read("OEBPS/book-toc.xhtml").decode("utf-8")
        assert '第1章 "开端"' in toc and "第2章 转折" in toc
        assert sum(1 for n in names if n.startswith("OEBPS/chapter")) == 2

        ncx = zf.read("OEBPS/toc.ncx").decode("utf-8")
        assert ncx.count("navPoint id") == 2


def test_epub_no_chapters_raises(tmp_path):
    import pytest
    store = BookStore(str(tmp_path / "empty"))
    store.save_meta(BookMeta(title="空书"))
    with pytest.raises(RuntimeError):
        build_epub(store, str(tmp_path / "x.epub"))
