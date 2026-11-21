# -*- coding: utf-8 -*-
"""全局配置：dataclass 默认值 + YAML/JSON 文件覆盖 + CLI 覆盖。"""

import os
from dataclasses import dataclass, field, asdict, fields
from typing import List, Optional, Dict, Any

from .log import get_logger

log = get_logger(__name__)


def _build(cls, data: Optional[Dict[str, Any]]):
    """按字段名从 dict 构造 dataclass，忽略未知键，递归嵌套段。"""
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise ValueError("配置段 {} 必须是字典，实际为 {}".format(cls.__name__, type(data)))
    kwargs = {}
    for f in fields(cls):
        if f.name in data:
            kwargs[f.name] = data[f.name]
    known = {f.name for f in fields(cls)}
    for key in data:
        if key not in known:
            log.warning("忽略未知配置项: %s.%s", cls.__name__, key)
    return cls(**kwargs)


@dataclass
class FetchConfig:
    threads: int = 8                 # 章节下载工作线程数
    timeout_connect: float = 10.0
    timeout_read: float = 15.0
    retry_count: int = 5             # 单章抓取重试次数
    backoff_base: float = 1.0        # 指数退避基数（秒）
    backoff_max: float = 60.0        # 退避上限
    jitter_min: float = 0.1          # 每次请求前的随机延迟下界（令牌桶之外再加一层错峰）
    jitter_max: float = 0.5
    verify_ssl: bool = False         # 小说站证书经常失效，默认不校验
    cookie: str = ""
    max_next_pages: int = 8          # 章节分页自动拼接的最大页数


@dataclass
class RateConfig:
    rate_per_sec: float = 5.0        # 每域名请求速率上限（AIMD 自适应：被封减半、成功回升）
    burst: int = 5                   # 桶容量
    cooldown_on_block: float = 20.0  # 命中反爬的递增冷却上限基准（秒）


@dataclass
class ProxyConfig:
    source: str = "none"             # none | list | api | file
    list_providers: List[str] = field(default_factory=lambda: ["kuaidaili", "jiangxianli"])
    list_pages: int = 5              # list 源抓取页数
    api_url: str = ""                # api 源：返回 ip:port 文本
    file_path: str = ""              # file 源：本地 ip:port 列表
    check_url: str = "http://httpbin.org/ip"  # 连通性校验地址
    check_timeout: float = 8.0
    max_proxy: int = 100             # 池容量上限
    min_alive: int = 4               # 低于该数量自动补充
    fail_limit: int = 3              # 连续失败次数达到则拉黑
    bootstrap_proxy: str = ""        # 抓代理列表本身可走的代理（ip:port）


@dataclass
class CleanerConfig:
    min_chapter_len: int = 200       # 少于该字数判定可疑，进入补爬队列
    junk_line_ratio: float = 0.3     # 行在超过该比例章节中出现 => 判定为插入广告
    junk_line_max_len: int = 60      # 超长行不当广告处理
    fix_punctuation: bool = True     # 半角标点邻接中文时转全角
    drop_site_name_lines: bool = True


@dataclass
class EpubConfig:
    publisher: str = "Ebookmaker"
    rights: str = "Created with Ebookmaker v2.0"
    language: str = "zh-CN"


@dataclass
class ConvertConfig:
    tools_base_path: str = "tools"   # kindlegen 二进制目录（相对工程根）
    ebook_convert_path: str = ""     # 留空则自动 which
    kindlegen_compression_level: str = "1"
    kindlegen_locale: str = "zh"


@dataclass
class AutoConfig:
    """站点自动适配（无规则时采样章节学习选择器并落盘复用）。"""
    enabled: bool = True
    samples: int = 5                 # 学习采样章节数
    min_cjk: int = 200               # 候选正文容器清洗后最少中文字数
    save_dir: str = ""               # 学习产物目录，空为 <工程根>/sites


@dataclass
class CleanupConfig:
    """输出目录清理行为。"""
    auto: bool = False               # run/build 产出后自动清工作区缓存（保留成品）


_SECTION_TYPES = (FetchConfig, RateConfig, ProxyConfig, CleanerConfig,
                  EpubConfig, ConvertConfig, AutoConfig, CleanupConfig)


@dataclass
class AppConfig:
    workdir: str = "books"           # 书籍工作区根目录
    formats: List[str] = field(default_factory=lambda: ["epub", "mobi", "azw3"])
    fetch: FetchConfig = field(default_factory=FetchConfig)
    rate: RateConfig = field(default_factory=RateConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    cleaner: CleanerConfig = field(default_factory=CleanerConfig)
    epub: EpubConfig = field(default_factory=EpubConfig)
    convert: ConvertConfig = field(default_factory=ConvertConfig)
    auto: AutoConfig = field(default_factory=AutoConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        cfg = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            v = data[f.name]
            current = getattr(cfg, f.name)
            if isinstance(current, _SECTION_TYPES):
                setattr(cfg, f.name, _build(current.__class__, v))
            else:
                setattr(cfg, f.name, v)
        return cfg

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_config(path: Optional[str] = None) -> AppConfig:
    """加载 config.yaml / config.json；path 为空时尝试工程根 config.yaml。"""
    candidates = []
    if path:
        candidates.append(path)
    else:
        candidates.append(os.path.join(os.getcwd(), "config.yaml"))
        candidates.append(os.path.join(os.getcwd(), "config.yml"))
    for cand in candidates:
        if not cand or not os.path.isfile(cand):
            continue
        try:
            import yaml
            with open(cand, "r", encoding="utf-8") as fp:
                data = yaml.safe_load(fp) or {}
            log.info("已加载配置文件: %s", cand)
            return AppConfig.from_dict(data)
        except ImportError:
            log.warning("未安装 PyYAML，忽略配置文件 %s", cand)
    if path:
        log.warning("配置文件不存在: %s，使用默认配置", path)
    return AppConfig()
