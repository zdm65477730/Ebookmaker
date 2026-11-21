# -*- coding: utf-8 -*-
"""站点自动适配学习器（Auto Site Learner）。

目标：用户只需给出目录页 URL，无需为每个站点手写规则。

流程：
1. 采样若干章节（目录首/中/尾分布）
2. 对每页的所有 div/section/article 候选容器：生成稳定 CSS 选择器，
   抽取正文并经 Cleaner 清洗，统计中文字数
3. 跨样本聚合：出现在 >=80% 页面且清洗后字数达标、稳定的选择器胜出
4. 目录页同理定位最密集链接容器并生成选择器
5. 组装成 RegexSite 描述符并回验（解析结果不得比启发式 generic 差 20%）
6. 成功后落盘 <workdir>/auto/<host>.yaml，之后同站点的爬取直接复用，
   无需再次学习（等效于自动生成的“站点规则”，但完全免手动）
"""

import math
import os
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .cleaner import Cleaner
from .config import AutoConfig
from .log import get_logger
from .models import TocEntry
from .sites.base import (SiteAdapter, container_to_lines, densest_toc_container,
                         make_soup)
from .sites.regex_site import RegexSite

log = get_logger(__name__)

# 工程根（ebookmaker 包的父目录），学习产物默认落在 <工程根>/sites
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 文本当量：中文字 + PUA 私有区字符（笔趣阁系字体加密站点正文以 PUA 码位呈现，
# 若只统计 CJK 会错判“无正文容器”，故打分与回验统一用文本当量）
TEXT_MASS_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\ue000-\uf8ff]")
PUA_ONLY_RE = re.compile(r"[\ue000-\uf8ff]")

# 字体解密：@font-face 下载地址与 glyph 命名中的原始码位（开源通用做法）
FONT_FACE_URL_RE = re.compile(r"@font-face[^}]*?url\(\s*['\"]?([^'\")]+?)['\"]?\s*\)", re.I | re.S)
FONT_EXT_RE = re.compile(r"\.(woff2?|ttf|otf)(\?|#|$)", re.I)
GLYPH_UNICODE_RE = re.compile(r"(?:uni|u\+|u)([0-9A-Fa-f]{4,5})$")

# 容器命名线索（正文容器常见 id/class 词）
CONTENT_HINT_RE = re.compile(r"(content|chapter|read|article|txt|book)", re.I)


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def auto_dir_for(cfg_workdir: str, save_dir: str = "") -> str:
    """站点学习产物目录：config 的 auto.save_dir 优先；
    默认为 <工程根>/sites（跟随包位置，不受运行 cwd 影响）。"""
    return save_dir or os.path.join(PROJECT_ROOT, "sites")


def descriptor_filename(url_or_host: str) -> str:
    """接受完整 URL 或裸 host，生成稳定的规则文件名。"""
    host = host_of(url_or_host) or url_or_host.lower()
    host = re.sub(r"^www\.", "", host)
    return re.sub(r"[^a-zA-Z0-9]", "_", host) + ".yaml"


# ---------- CSS 选择器生成 ----------
def css_selector(node, soup) -> Optional[str]:
    """为节点生成在当前文档内唯一命中自身的 CSS 选择器（跨页面稳定的优先）。"""
    # 1. id
    node_id = node.get("id")
    if node_id:
        sel = "#{0}".format(node_id)
        try:
            if len(soup.select(sel)) == 1:
                return sel
        except Exception:
            pass
    # 2. tag + 最具区分度的 class
    classes = node.get("class") or []
    if classes:
        scored = []
        for cls in classes:
            sel = "{0}.{1}".format(node.name, cls)
            try:
                scored.append((len(soup.select(sel)), sel))
            except Exception:
                continue
        for cnt, sel in sorted(scored):
            if cnt == 1:
                return sel
        # 全部 class 组合
        sel = node.name + "".join("." + c for c in classes)
        try:
            if len(soup.select(sel)) == 1:
                return sel
        except Exception:
            pass
    # 3. 父链 nth-of-type 路径（深度限制 4，需每一层唯一）
    parts = []
    cur = node
    for _ in range(4):
        parent = cur.parent
        if parent is None:
            parts.insert(0, cur.name)
            break
        siblings = parent.find_all(cur.name, recursive=False)
        if len(siblings) == 1:
            parts.insert(0, cur.name)
        else:
            idx = siblings.index(cur) + 1
            parts.insert(0, "{0}:nth-of-type({1})".format(cur.name, idx))
        if parent.name in ("[document]", "html", "body"):
            break
        cur = parent
    if not parts:
        return None
    sel = " > ".join(parts)
    try:
        if len(soup.select(sel)) == 1:
            return sel
    except Exception:
        return None
    return None


# ---------- 候选容器打分 ----------
def content_candidates(soup, cleaner: Cleaner, min_cjk: int) -> Dict[str, tuple]:
    """selector -> (加权得分, 清洗后中文字数, 清洗后正文文本)。

    统计前剔除 a/button 文本（导航/分页链接不属于正文），对命中正文命名线索的
    选择器给予 20% 加权。跨样本的“重复度”甄别在 learn_site 里做（外壳/侧栏
    在章与章之间几乎不变，真正文几乎不重复）。"""
    stats: Dict[str, tuple] = {}
    for node in soup.find_all(["div", "section", "article"]):
        raw_text = node.get_text(strip=True)
        if len(raw_text) < min_cjk:
            continue
        sel = css_selector(node, soup)
        if not sel:
            continue
        # container_to_lines 会破坏节点，用文档快照独立解析
        frag = make_soup(str(node))
        for t in frag.find_all(["a", "button"]):
            t.decompose()
        lines = container_to_lines(frag.body or frag)
        cleaned = cleaner.clean_paragraphs(lines, chapter_index=1)
        blob = "".join(cleaned)
        cjk = len(TEXT_MASS_RE.findall(blob))
        if cjk < min_cjk:
            continue
        score = int(cjk * 1.2) if CONTENT_HINT_RE.search(sel) else cjk
        prev = stats.get(sel)
        if prev is None or score > prev[0]:
            stats[sel] = (score, cjk, blob)
    return stats


# ---------- 字体加密检测与自动解密 ----------
def pua_ratio(text: str) -> float:
    """PUA 私有区字符占比，>2% 基本可判定站点使用了字体加密。"""
    if not text:
        return 0.0
    return len(PUA_ONLY_RE.findall(text)) / len(text)


def font_bytes_to_map(data: bytes) -> Dict[str, str]:
    """解析字体 cmap：PUA 码位 -> glyph 名中的原始 unicode 字符。

    适用于 glyph 命名保留 uniXXXX 规律的站点（开源字体解密工具的通用首要策略）；
    命名无规律时返回空表，由调用方提示安装依赖/降级。
    """
    from fontTools.ttLib import TTFont  # 可选依赖
    import io
    font = TTFont(io.BytesIO(data), lazy=True)
    cmap = font.getBestCmap() or {}
    mapping: Dict[str, str] = {}
    for cp, glyph_name in cmap.items():
        if not (0xE000 <= cp <= 0xF8FF):
            continue
        m = GLYPH_UNICODE_RE.search(str(glyph_name))
        if not m:
            continue
        try:
            real = int(m.group(1), 16)
        except ValueError:
            continue
        if real > 0x20 and real != cp:
            mapping[chr(cp)] = chr(real)
    return mapping


def learn_font_map(http, page_html: str, page_url: str, max_fonts: int = 4) -> Dict[str, str]:
    """从章节页提取 @font-face 字体并构建 PUA->真实字符映射。"""
    urls = []
    for m in FONT_FACE_URL_RE.finditer(page_html):
        u = m.group(1).strip()
        if FONT_EXT_RE.search(u):
            urls.append(urljoin(page_url, u))
    merged: Dict[str, str] = {}
    for u in dict.fromkeys(urls):  # 去重保序
        if len(merged) >= 2000:
            break
        try:
            data = http.get(u, referer=page_url, stream=True, as_text=False).content
        except Exception as e:
            log.debug("字体下载失败 %s: %s", u, e)
            continue
        try:
            merged.update(font_bytes_to_map(data))
        except ImportError:
            log.warning("检测到加密字体，但未安装 fonttools（pip install fonttools），无法解密")
            return {}
        except Exception as e:
            log.debug("字体解析失败 %s: %s", u, e)
    return merged


def _sample_indices(total: int, samples: int) -> List[int]:
    samples = max(3, min(samples, total))
    if total <= samples:
        return list(range(total))
    step = (total - 1) / (samples - 1)
    return sorted({int(round(i * step)) for i in range(samples)})


# ---------- 主学习入口 ----------
def learn_site(http, book_url: str, toc: List[TocEntry], cleaner: Cleaner,
               cfg: AutoConfig) -> Optional[dict]:
    """采样学习站点结构，成功返回 RegexSite 描述符 dict，失败返回 None。"""
    if not toc or len(toc) < 3:
        log.info("目录过短，跳过站点结构学习")
        return None
    host = host_of(book_url)
    idxs = _sample_indices(len(toc), cfg.samples)
    per_doc: List[Dict[str, tuple]] = []
    sample_pages: List[Tuple[str, str]] = []   # (url, html)

    for i in idxs:
        ch_url = SiteAdapter.chapter_url(book_url, toc[i].href)
        try:
            html = http.get(ch_url, referer=book_url).text
        except Exception as e:
            log.debug("学习采样失败 %s: %s", ch_url, e)
            continue
        sample_pages.append((ch_url, html))
        soup = make_soup(html)
        per_doc.append(content_candidates(soup, cleaner, cfg.min_cjk))

    if len(per_doc) < 3:
        return None

    agg: Dict[str, List[int]] = defaultdict(list)
    raw_agg: Dict[str, List[int]] = defaultdict(list)
    blob_agg: Dict[str, List[str]] = defaultdict(list)
    for d in per_doc:
        for sel, (score, raw, blob) in d.items():
            agg[sel].append(score)
            raw_agg[sel].append(raw)
            blob_agg[sel].append(blob)

    def _repetition_factor(sel: str) -> float:
        """跨样本重复度：两两 3-gram **多重集**质量 Jaccard 的中位数。

        用多重集而非集合：侧栏复读文案在集合下 gram 种类极少会低估重复度，
        质量占比才是“容器文本有多少来自固定挂件”的真实度量。
        页面壳/侧栏跨章几乎原样重现（高）；真正文章与章仅共享常用词（低）。
        ≥ 0.20 按 (1-rep)^2 降权，下限 0.01。"""
        blobs = blob_agg.get(sel) or []
        if len(blobs) < 3:
            return 1.0
        def grams(b: str):
            b = re.sub(r"\s+", "", b)
            return Counter(b[i:i + 3] for i in range(max(1, len(b) - 2)))
        g = [grams(b) for b in blobs[:6]]
        sims = []
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                inter = sum((g[i] & g[j]).values())
                union = sum((g[i] | g[j]).values()) or 1
                sims.append(inter / union)
        sims.sort()
        rep = sims[len(sims) // 2]
        if rep >= 0.20:
            return max(0.01, (1.0 - rep) ** 2)
        return 1.0

    need = max(3, math.ceil(0.8 * len(per_doc)))
    best_sel, best_med, best_raw = None, 0, []
    for sel, vals in agg.items():
        if len(vals) < need:
            continue
        med = sorted(vals)[len(vals) // 2] * _repetition_factor(sel)   # 中位分×重复度因子，非首样本分
        if med > best_med:
            best_sel, best_med, best_raw = sel, med, raw_agg[sel]
    if not best_sel:
        log.info("未能自动定位正文容器（站点可能需要 JS 渲染或存在加密字体）")
        return None

    # 目录容器选择器
    toc_sel = None
    try:
        book_html = http.get(book_url).text
        soup = make_soup(book_html)
        cont, _links = densest_toc_container(soup)
        if cont is not None:
            toc_sel = css_selector(cont, soup)
    except Exception as e:
        log.debug("目录容器学习失败: %s", e)

    descriptor = {
        "name": "auto-" + host,
        "type": "site",
        "hosts": [host],
        "content": {"selector": best_sel},
    }
    if toc_sel:
        # 存链接形态选择器（容器 + 空格 a），与描述符 toc.selector 语义一致
        descriptor["toc"] = {"selector": toc_sel + " a"}

    # 回验：学习产物解析结果不得比启发式差 20%，且目录必须能解出
    try:
        site = RegexSite(descriptor)
    except re.error as e:
        log.warning("生成的选择器不可用: %s", e)
        return None
    if toc_sel and len(site.parse_toc(book_html, book_url)) < 5:
        log.info("目录选择器回验不通过（%s），退回通用启发式抽取", host)
        return None
    for ch_url, html in sample_pages:
        learned_lines = site.parse_chapter(html, ch_url)
        learned_cjk = len(TEXT_MASS_RE.findall("".join(learned_lines)))
        if learned_cjk < min(best_raw) * 0.8:
            log.info("站点学习回验未通过（%s），退回通用启发式抽取", host)
            return None

    log.info("站点自动适配成功: %s -> 正文 %s%s", host, best_sel,
             "，目录 " + toc_sel if toc_sel else "")
    return descriptor


def save_descriptor(descriptor: dict, directory: str) -> str:
    import yaml
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, descriptor_filename(descriptor["hosts"][0]))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        yaml.safe_dump(descriptor, fp, allow_unicode=True, sort_keys=False)
    os.replace(tmp, path)
    log.info("站点规则已自动保存，后续爬取将直接复用: %s", path)
    return path


def load_learned_site(directory: str, url: str) -> Optional[RegexSite]:
    """按 host 查找已学习的站点规则文件。"""
    import yaml
    if not os.path.isdir(directory):
        return None
    fname = descriptor_filename(url)
    path = os.path.join(directory, fname)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp) or {}
        if data.get("type") != "site":
            return None
        site = RegexSite(data)
        log.info("复用已学习的站点规则: %s", path)
        return site
    except Exception as e:
        log.warning("加载学习规则 %s 失败: %s", path, e)
        return None
