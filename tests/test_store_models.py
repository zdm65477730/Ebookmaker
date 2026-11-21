# -*- coding: utf-8 -*-
"""数据模型与工作区存储测试。"""

import os

from ebookmaker.models import BookMeta, ChapterData, TocEntry
from ebookmaker.store import BookStore, safe_dirname


def test_toc_entry_number_parsing():
    assert TocEntry("a/123.html", "第28章 突破").number == 28
    assert TocEntry("a/123.html", "第 28 章").number == 28
    assert TocEntry("a/123.html", "第２８章").number == 28   # 全角数字
    assert TocEntry("/66/66747/26547971.html", "前言").number == 26547971
    assert TocEntry("../", "返回书页").number is None


def test_safe_dirname():
    assert safe_dirname("武神/主宰:完结") == "武神_主宰_完结"
    assert safe_dirname("") == "MyBook"


def test_store_roundtrip(tmp_path):
    store = BookStore(str(tmp_path / "书"))
    meta = BookMeta(title="测试书", author="测试作者", source_url="http://a/")
    store.save_meta(meta)
    loaded = store.load_meta()
    assert loaded.title == "测试书" and loaded.source_url == "http://a/"

    ch = ChapterData(index=1, title="第1章", url="http://a/1", paragraphs=["正文" * 50])
    store.save_chapter(ch)
    got = store.load_chapter(1)
    assert got.title == "第1章" and got.status == "ok"
    assert store.has_valid_chapter(1)
    assert not store.has_valid_chapter(2)

    # 可疑章节不算有效缓存
    bad = ChapterData(index=2, title="第2章", url="http://a/2", paragraphs=["短"],
                      status="suspicious", problems=["过短"])
    store.save_chapter(bad)
    assert not store.has_valid_chapter(2)
    assert store.drop_invalid_chapters() == 1
    assert store.load_chapter(2) is None

    # 原子写不留 tmp 文件
    leftovers = [f for f in os.listdir(store.chapters_dir) if f.endswith(".tmp")]
    assert leftovers == []
