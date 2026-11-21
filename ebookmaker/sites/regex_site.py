# -*- coding: utf-8 -*-
"""YAML 规则描述符站点：仅描述页面结构（爬取适配），不携带任何清洗规则。
内容净化统一由 cleaner 的内建通用逻辑（黑名单/统计/质量检查）完成。

描述符文件结构（自动学习产物与此一致，存于 <workdir>/auto/<host>.yaml）：

    name: mysite
    type: site                        # 必须
    hosts: [www.mysite.com]
    meta:                             # 可选，正则从目录页 HTML 提取（兼容旧 *_re 配置）
      book_name: "<h1>(.*?)</h1>"
      author: "作者：<a[^>]*>(.*?)</a>"
      cover_url: '<meta property="og:image" content="(.*?)">'
    toc:
      selector: "dl dd a"             # 二选一：CSS 选择器
      regex: '<dd><a href="([^"]+)"[^>]*>(.*?)</a></dd>'   # 或两捕获组正则 (href, title)
    content:
      selector: "#content"            # 二选一
      regex: '<div id="content">([\\s\\S]*?)</div>'          # 单捕获组正文 HTML
"""

import os
import re
from typing import Dict, List, Optional

from .base import (SiteAdapter, anchor_href, clean_author, clean_book_title, container_to_lines,
                   filter_same_host, looks_like_chapter, make_soup,
                   normalize_toc, parse_og_meta)
from ..log import get_logger
from ..models import BookMeta, TocEntry

log = get_logger(__name__)

_META_KEY_MAP = {
    "book_name": "title",
    "name": "title",
    "author": "author",
    "category": "category",
    "description": "description",
    "update_time": "update_time",
    "date": "update_time",
    "cover_url": "cover_url",
    "image": "cover_url",
}


class RegexSite(SiteAdapter):
    def __init__(self, descriptor: dict):
        self.name = descriptor.get("name", "regex_site")
        self.hosts = [h.lower() for h in descriptor.get("hosts", [])]
        self._meta_res = {
            _META_KEY_MAP.get(k, k): re.compile(v)
            for k, v in (descriptor.get("meta") or {}).items()
        }
        toc = descriptor.get("toc") or {}
        self._toc_selector = toc.get("selector")
        self._toc_re = re.compile(toc["regex"]) if toc.get("regex") else None
        content = descriptor.get("content") or {}
        self._content_selector = content.get("selector")
        self._content_re = re.compile(content["regex"]) if content.get("regex") else None

    def has_content_container(self, html: str) -> bool:
        """描述符站点：按学习到的正文选择器/正则判定页面是否含正文容器。"""
        try:
            if self._content_re is not None:
                return bool(self._content_re.search(html))
            if self._content_selector:
                node = make_soup(html).select_one(self._content_selector)
                return node is not None and len(node.get_text(strip=True)) > 20
        except Exception:
            return False
        return False

    def parse_meta(self, html: str, url: str) -> BookMeta:
        meta = parse_og_meta(make_soup(html), url)
        meta.site = self.name
        for key, pattern in self._meta_res.items():
            m = pattern.search(html)
            if m:
                value = m.group(1).strip()
                if key == "title":
                    value = clean_book_title(value)
                elif key == "author":
                    value = clean_author(value)
                setattr(meta, key, value)
        return meta

    def parse_toc(self, html: str, url: str) -> List[TocEntry]:
        entries = []
        if self._toc_re is not None:
            entries = [TocEntry(href=h.strip(), title=t.strip()) for h, t in self._toc_re.findall(html) if h and t]
        elif self._toc_selector:
            soup = make_soup(html)
            for node in soup.select(self._toc_selector):
                # 选择器命中的可能是 <a> 列表，也可能是容器节点（如学习产物存的是目录容器）；
                # 非 <a> 容器自动展开为其内部全部链接
                anchors = [node] if node.name == "a" else node.find_all("a")
                for a in anchors:
                    # 优先 href，href 为 javascript: 时回退 onclick 内的 location.href
                    href = anchor_href(a)
                    title = a.get_text(strip=True)
                    if href and title and not href.startswith("#") \
                            and looks_like_chapter(href, title):
                        entries.append(TocEntry(href=href, title=title))
        if entries:
            return normalize_toc(filter_same_host(entries, url))
        # 描述符未命中时回退通用密度定位，不硬失败
        log.debug("描述符 %s 的目录规则未命中，回退通用定位", self.name)
        return super().parse_toc(html, url)

    def parse_chapter(self, html: str, url: str) -> List[str]:
        lines: List[str] = []
        if self._content_re is not None:
            m = self._content_re.search(html)
            if m:
                inner = m.group(1) if m.groups() else m.group(0)
                soup = make_soup(inner)
                lines = container_to_lines(soup.body or soup)
        elif self._content_selector:
            node = make_soup(html).select_one(self._content_selector)
            if node is not None:
                lines = container_to_lines(node)
        if len("".join(lines).strip()) >= 50:
            return lines
        # 描述符未命中/过短：回退 generic 启发式（选择器优先 + trafilatura + 文本密度）
        log.debug("描述符 %s 的正文规则未命中，回退通用抽取", self.name)
        from .generic import GenericSite
        return GenericSite().parse_chapter(html, url)

    @staticmethod
    def from_yaml(path: str) -> Optional["RegexSite"]:
        try:
            import yaml
        except ImportError:
            log.warning("未安装 PyYAML，跳过站点描述符 %s", path)
            return None
        with open(path, "r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp) or {}
        if data.get("type") != "site":
            return None
        try:
            return RegexSite(data)
        except re.error as e:
            log.error("站点描述符 %s 含非法正则: %s", path, e)
            return None


def load_sites_from_dirs(dirs: List[str]) -> Dict[str, RegexSite]:
    """扫描规则目录，加载所有 type=site 描述符。返回 name -> RegexSite。"""
    sites: Dict[str, RegexSite] = {}
    for d in dirs or []:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith((".yaml", ".yml")):
                continue
            site = RegexSite.from_yaml(os.path.join(d, name))
            if site is not None:
                sites[site.name] = site
    return sites
