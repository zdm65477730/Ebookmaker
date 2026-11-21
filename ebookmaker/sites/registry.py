# -*- coding: utf-8 -*-
"""适配器注册表：只保留两类来源——YAML 站点描述符 与 generic 自动兜底。

站点结构由 auto.py 在线学习并沉淀为描述符（<workdir>/auto/<host>.yaml）；
没有任何内置适配器，也没有任何净化规则文件——清洗全部走 cleaner 内建通用逻辑。
"""

from typing import List, Optional

from .base import SiteAdapter
from .generic import GenericSite
from .regex_site import load_sites_from_dirs
from ..log import get_logger

log = get_logger(__name__)


def all_adapters(extra_rules_dirs: Optional[List[str]] = None) -> List[SiteAdapter]:
    return list(load_sites_from_dirs(list(extra_rules_dirs or [])).values())


def get_adapter(url: str = "", site_name: str = "",
                extra_rules_dirs: Optional[List[str]] = None) -> SiteAdapter:
    """查找适配器：描述符按名称/host 匹配，未命中一律走 generic 自动适配。"""
    adapters = all_adapters(extra_rules_dirs)
    if site_name:
        for a in adapters:
            if a.name == site_name:
                log.info("使用指定站点描述符: %s", a.name)
                return a
        raise ValueError("未找到站点描述符: {}（可用: {}）".format(
            site_name, ", ".join(list_adapter_names(adapters)) or "无"))
    if url:
        for a in adapters:
            if a.matches(url):
                log.info("URL 匹配站点描述符: %s", a.name)
                return a
    return GenericSite()


def list_adapter_names(adapters: Optional[List[SiteAdapter]] = None) -> List[str]:
    return [a.name for a in (adapters or all_adapters())]
