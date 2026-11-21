"""书目索引：记录"同一本书在哪些源有过目录"，供跨源补全章节。

用户要求零规则文件——索引不是站点规则，而是爬取行为的自然副产品：
每次爬书自动登记 {书名: [{source_url, chapters:[{title,url}]}]}，
下次爬同名书时，缺章/短章就能去其他源按章名对齐补齐。

位置：<工程根>/sites/book_index.json（与站点描述符同目录、同生命周期，
不受 clean 影响）。
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path

from .log import get_logger
from .models import TocEntry

log = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 同一书名最多保留的源数（防止索引无限膨胀）
MAX_SOURCES = 8


def _index_file(workdir: str | Path) -> Path:
    return PROJECT_ROOT / "sites" / "book_index.json"


def norm_title(s: str) -> str:
    """章节名归一：NFKC 统一全/半角、去空白与（N/M）分页后缀、小写。"""
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[（(]\s*\d+\s*/\s*\d+\s*[)）]\s*$", "", s)
    s = re.sub(r"\s+", "", s)
    return s.lower()


def book_key(title: str) -> str:
    """书名归一为索引键：去空白/标点/下划线。"""
    s = unicodedata.normalize("NFKC", title or "")
    s = re.sub(r"[\s\-_—－·．。，,。！!？?：:；;]+", "", s)
    return s.lower()


def load(workdir: str | Path) -> dict:
    path = _index_file(workdir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def record(workdir: str | Path, book_title: str, source_url: str,
           toc: list[TocEntry]) -> None:
    """登记/更新一个源。同 URL 的旧记录整组替换（目录可能随连载更新）。"""
    key = book_key(book_title)
    if not key or not source_url:
        return
    idx = load(workdir)
    sources = idx.get(key, [])
    entry = {
        "url": source_url,
        "added": time.strftime("%Y-%m-%d"),
        "chapters": [{"t": c.title, "u": c.href} for c in toc],
    }
    sources = [s for s in sources if s.get("url") != source_url]
    sources.insert(0, entry)
    if len(sources) > MAX_SOURCES:
        log.info("书目索引：%r 的源超过 %d 个，最旧的不再保留", book_title, MAX_SOURCES)
        sources = sources[:MAX_SOURCES]
    idx[key] = sources
    path = _index_file(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    log.info("已登记书目索引：%r（源 %s，%d 章）", book_title, source_url, len(toc))


def other_sources(workdir: str | Path, book_title: str,
                  exclude_url: str) -> list[str]:
    """同书名的其他源 URL（新登记的在前）。"""
    key = book_key(book_title)
    urls = []
    for s in load(workdir).get(key, []):
        u = s.get("url")
        if u and u != exclude_url and u not in urls:
            urls.append(u)
    return urls


def source_toc(workdir: str | Path, source_url: str) -> list[TocEntry]:
    """索引中某源的章节表（免去网络解析）。"""
    key_entries = load(workdir)
    for sources in key_entries.values():
        for s in sources:
            if s.get("url") == source_url:
                return [TocEntry(title=c.get("t", ""), href=c.get("u", ""))
                        for c in s.get("chapters", [])]
    return []
