# -*- coding: utf-8 -*-
"""通用兜底站点：无适配器的站点走这里。

- 元信息：og:novel:* meta（继承基类实现）
- 目录：链接密度兜底容器
- 正文：优先 trafilatura（若安装），否则启发式最大文本密度块
"""

import re
from typing import List

from .base import BiqugeStyleSite, container_to_lines, make_soup
from ..log import get_logger

log = get_logger(__name__)

# 常见的“疑似正文”id/class 线索
_CONTENT_HINT_RE = re.compile(r"(content|chapter|booktxt|read|article|txt)", re.I)


def heuristic_content(soup):
    """启发式找正文节点：id/class 命中线索的节点中，文本最长者。"""
    candidates = []
    for node in soup.find_all(["div", "section", "article"]):
        attrs = " ".join(filter(None, [node.get("id") or "", node.get("class") and " ".join(node.get("class")) or ""]))
        if not attrs:
            continue
        text = node.get_text(strip=True)
        if len(text) < 80:
            continue
        score = len(text) * (3 if _CONTENT_HINT_RE.search(attrs) else 1)
        brs = len(node.find_all("br"))
        score += brs * 50
        candidates.append((score, node))
    if not candidates:
        return None
    return max(candidates, key=lambda t: t[0])[1]


def _trafilatura_lines(html: str) -> List[str]:
    try:
        import trafilatura
    except ImportError:
        return []
    text = trafilatura.extract(html, include_comments=False, favor_precision=True) or ""
    return [l for l in text.split("\n") if l.strip()]


class GenericSite(BiqugeStyleSite):
    name = "generic"
    hosts: List[str] = []  # 仅作为兜底，不参与 host 匹配

    def parse_chapter(self, html: str, url: str) -> List[str]:
        soup = make_soup(html)
        node = self._select_node(soup)
        if node is not None:
            return container_to_lines(node)
        lines = _trafilatura_lines(html)
        if lines:
            log.debug("%s 使用 trafilatura 抽取正文", url)
            return lines
        node = heuristic_content(soup)
        return container_to_lines(node)

    @staticmethod
    def _select_node(soup):
        from .base import DEFAULT_CONTENT_SELECTORS, find_content_node
        node = find_content_node(soup, DEFAULT_CONTENT_SELECTORS)
        if node is not None:
            return node
        return heuristic_content(soup)
