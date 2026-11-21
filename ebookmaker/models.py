# -*- coding: utf-8 -*-
"""核心数据模型。所有中间落盘格式均由这些 dataclass 派生。"""

import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

# 章节序号解析：第123章 / 第 一二三 回（仅数字）/ URL 尾号
_CH_NUM_RE = re.compile(r"第\s*([0-9０-９]+)\s*(?:章|节|回|篇)")
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


@dataclass
class BookMeta:
    """书籍元信息（来自站点目录页）。"""
    title: str = "MyBook"
    author: str = "未知"
    category: str = "其他"
    description: str = ""
    update_time: str = ""
    cover_url: str = ""
    source_url: str = ""
    site: str = ""
    language: str = "zh-CN"
    publisher: str = "Ebookmaker"
    rights: str = "Created with Ebookmaker v2.0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BookMeta":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class TocEntry:
    """目录条目。href 为相对或绝对 URL，title 为章节标题。"""
    href: str
    title: str

    @property
    def number(self) -> Optional[int]:
        """从标题或 URL 解析章节序号，解析失败返回 None。"""
        m = _CH_NUM_RE.search(self.title.translate(_FULLWIDTH_DIGITS))
        if m:
            return int(m.group(1))
        m = re.search(r"(\d{1,9})(?:\.html|/?$)", self.href.rstrip("/"))
        if m:
            return int(m.group(1))
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {"href": self.href, "title": self.title}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TocEntry":
        return cls(href=data["href"], title=data["title"])


@dataclass
class ChapterData:
    """已下载并净化的章节。status: ok / suspicious / error。"""
    index: int               # 从 1 开始的目录序号
    title: str
    url: str
    paragraphs: List[str] = field(default_factory=list)
    status: str = "ok"
    problems: List[str] = field(default_factory=list)

    def text_length(self) -> int:
        return sum(len(p) for p in self.paragraphs)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChapterData":
        return cls(
            index=int(data["index"]),
            title=data.get("title", ""),
            url=data.get("url", ""),
            paragraphs=list(data.get("paragraphs", [])),
            status=data.get("status", "ok"),
            problems=list(data.get("problems", [])),
        )
