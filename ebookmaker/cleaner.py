# -*- coding: utf-8 -*-
"""内容净化管线（全部为内建通用逻辑，不加载任何规则文件）。

分层执行：
1. 单行结构清洗：去零宽/控制字符、符号间隔乱码（♂领♂域♂）、拼音注音乱码、空白归一
2. 静态广告/干扰行过滤：内置黑名单正则（URL/水印/引导语/纯符号行等）
3. 文本规范化：半角标点邻接中文转全角、省略号归一、内建通用引号排版规则
4. 跨章节频次统计：章首/章尾高频短行判定为插入广告（junk lines），build 前二次过滤
5. 质量检查：字数离群、乱码率（PUA/替换符占比）→ suspicious 章节进补爬队列
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional, Sequence, Set, Tuple

from .config import CleanerConfig
from .log import get_logger

log = get_logger(__name__)

# ---------- 字符级清洗 ----------
# 零宽字符 / BOM / 控制字符（保留 \t\n）
ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff\ufffe\uffff]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 干扰符号（夹在正文里的水印字符，如 ♂领♂域♂文♂学♂、★☆）
NOISE_SYMBOL_RE = re.compile(r"[♂♀★◎@☆цц]{1,}[ ]?")
# 拼音注音乱码（防盗版插入的“汉字+拼音”括号噪声）
PINYIN_NOISE_RE = re.compile(
    r"[\u4e00-\u9fff]?[(（][\u4e00-\u9fff][a-zāáǎàōóǒòēéěèīíǐìūúǔùǖǘǚǜ]+[)）]")
# 连续 &nbsp; 残留
NBSP_RE = re.compile(r"(?:\u00a0|&nbsp;)+")

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
PUA_RE = re.compile(r"[\ue000-\uf8ff\ufffd]")
# 中文文本当量（含 PUA）：字体加密站未解密时不应因此反复补爬
MASS_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\ue000-\uf8ff]")

# ---------- 行级广告黑名单（常见站点水印/引导语的通用特征） ----------
AD_LINE_PATTERNS = [re.compile(p, re.I) for p in (
    r"https?://|www\.|m\.[a-z0-9\-]+\.(com|net|cc|org)|\.(com|net|cc|la|xyz)(?=[/\s]|$)",
    r"(请?收藏|记住|首发|最新更新|最快更新).{0,30}(小说|网址|地址|域名)",
    r"(笔趣?阁|顶点小说|八一?小说|书海阁|69书吧|妙笔阁|oku|书旗|起点|横店|嘉年华).{0,20}(小说|无弹窗|无弹窗|提醒您|首发)",
    r"(本章未完|点击下一页|下一章自己找|请返回|章节目录|加入书签|章节错误|报错|举报)",
    r"(喜欢|如果觉得|如果阅读).{0,25}(的话|吗).{0,25}(请|记得|收藏|分享|推荐)",
    r"（.{0,12}(小说|网站|域名|地址).{0,12}）$",
    r"translat|service generated|copyright",
    r"^[0-9\s\-—=:;,.!?,.，。、！；：]+$",          # 纯符号/数字分割线
    r"^[a-zA-Z0-9_\-\*#]{4,}$",                    # 纯 ASCII 乱码行
)]

# 疑似广告线索（用于跨章节频次统计的候选收紧）
JUNK_HINT_RE = re.compile(
    r"(小说|网址|地址|收藏|记住|首发|笔趣|顶点|章节|无弹窗|域名|域名|更新|支持|txt|下载)", re.I)

# 规范化：半角标点紧挨中文时转全角
_PUNCT_MAP = {",": "，", ";": "；", ":": "：", "?": "？", "!": "！"}
_PUNCT_RULES = [(re.compile(r"(?<=[\u4e00-\u9fff”》！？。])[" + re.escape(k) + r"](?=[\u4e00-\u9fff“（])"), v)
                for k, v in _PUNCT_MAP.items()]
_ELLIPSIS_RE = re.compile(r"\.{3,}|。{3,}")
_EXCLAM_RE = re.compile(r"！{3,}")

# 章节标题行（频次统计时永不删除）
CHAPTER_TITLE_RE = re.compile(r"^第\s*[0-9０-９一二三四五六七八九十百千]+\s*[章节回]")

# ---------- 内建通用整章排版规则（取代外部规则文件） ----------
# 仅收录对任意站点都安全的引号/标点排版修复，不含任何删除类规则
BUILTIN_CHAPTER_PATTERNS = [
    ("”“", "”\n“"),        # 两段引语粘连时断行
    ("！“", "！\n“"),        # 感叹结束接引语时断行
    ("”\n，", "”，"),          # 跨行粘连的标点碎片合并
    ("”\n？", "”？"),
    ("，;", "，"),
]


@dataclass
class ReplaceRule:
    """内部替换规则（chapters 为 None 时全章通用）。"""
    chapters: Optional[Set[int]]
    pattern: "re.Pattern"
    repl: str


class Cleaner:
    def __init__(self, cfg: CleanerConfig, rules: Optional[Sequence[ReplaceRule]] = None,
                 font_map: Optional[dict] = None):
        self.cfg = cfg
        # 内建通用规则优先，额外规则仅测试/内部使用，不从任何文件加载
        self.rules: List[ReplaceRule] = [
            ReplaceRule(chapters=None, pattern=re.compile(p, re.M), repl=r)
            for p, r in BUILTIN_CHAPTER_PATTERNS
        ]
        self.rules.extend(rules or [])
        self.ad_patterns = list(AD_LINE_PATTERNS)
        self.set_font_map(font_map or {})

    def set_font_map(self, font_map: dict):
        """字体加密站点自动解密后，PUA 码位 -> 真实字符的还原表。"""
        self._font_table = str.maketrans(font_map) if font_map else None

    def _restore_font(self, text: str) -> str:
        return text.translate(self._font_table) if self._font_table else text

    # ---------- 阶段 1-4：单章清洗 ----------
    def clean_paragraphs(self, raw_lines: Sequence[str], chapter_index: int = 0,
                         junk_lines: Optional[Set[str]] = None,
                         title: str = "") -> List[str]:
        # 第一步：字符级预清洗 + 静态广告行过滤
        norm_title = self._normalize(title) if title else ""
        lines = []
        for line in raw_lines:
            text = self._pre_clean_line(line, junk_lines)
            if not text:
                continue
            # 正文里重复出现的本章标题行（旧 bageoo 配置“第N章 ”剔除规则的通用化）
            if norm_title and self._normalize(text) == norm_title:
                continue
            lines.append(text)
        # 第二步：替换规则在整章文本上应用（支持跨行拆分，兼容旧 re.M 规则）
        text = "\n".join(lines)
        for rule in self.rules:
            if rule.chapters is None or chapter_index in rule.chapters:
                text = rule.pattern.sub(rule.repl, text)
        # 第三步：重新切行，规范化并二次过滤拆出来的广告片段
        out = []
        for line in text.split("\n"):
            final = self._finalize_line(line)
            if final:
                out.append(final)
        return out

    def _pre_clean_line(self, line: str, junk_lines: Optional[Set[str]]) -> str:
        text = CONTROL_RE.sub("", ZERO_WIDTH_RE.sub("", line))
        text = self._restore_font(text)          # 先还原加密字体码位
        text = NBSP_RE.sub(" ", text)
        text = PINYIN_NOISE_RE.sub("", text)
        text = NOISE_SYMBOL_RE.sub("", text)
        text = re.sub(r"[ \t]+", " ", text).strip()
        if not text:
            return ""
        # 静态广告行
        for pat in self.ad_patterns:
            if pat.search(text):
                return ""
        # 全局统计出的广告行（build 二次过滤阶段传入）
        if junk_lines and self._normalize(text) in junk_lines:
            return ""
        return text

    def _finalize_line(self, text: str) -> str:
        text = re.sub(r"[ \t]+", " ", text).strip()
        if not text:
            return ""
        for pat in self.ad_patterns:      # 规则拆分后新暴露的广告片段
            if pat.search(text):
                return ""
        if self.cfg.fix_punctuation:
            text = self._fix_punctuation(text)
        # 全角空格缩进交给 CSS，段内不留空白
        text = text.replace("\u3000", "").strip()
        return text if text and text not in ("：", "“", "”") else ""

    @staticmethod
    def _fix_punctuation(text: str) -> str:
        for pat, repl in _PUNCT_RULES:
            text = pat.sub(repl, text)
        text = _ELLIPSIS_RE.sub("……", text)
        text = _EXCLAM_RE.sub("！", text)
        text = text.replace("、“", "：“")
        return text

    @staticmethod
    def _normalize(line: str) -> str:
        return re.sub(r"\s+", "", line)

    @staticmethod
    def is_ad_line(line: str) -> bool:
        return any(pat.search(line) for pat in AD_LINE_PATTERNS)

    # ---------- 阶段 5：跨章节广告行统计 ----------
    def find_junk_lines(self, chapters: Sequence[Tuple[int, Sequence[str]]]) -> Set[str]:
        """在章首/章尾段落中统计跨章节高频短行，判定为插入广告。

        chapters: [(chapter_index, paragraphs), ...]
        返回规范化后的行集合（build 阶段传入 clean_paragraphs 二次过滤）。
        """
        total = len(chapters)
        if total < 20:  # 样本太少不做统计，避免误删
            return set()
        counter: Counter = Counter()
        for _, paragraphs in chapters:
            head = list(paragraphs[:3])
            tail = list(paragraphs[-5:])
            seen_in_chapter = set()
            for line in head + tail:
                if CHAPTER_TITLE_RE.match(line):
                    continue
                norm = self._normalize(line)
                if not norm or len(line) > self.cfg.junk_line_max_len:
                    continue
                if norm not in seen_in_chapter:
                    counter[norm] += 1
                    seen_in_chapter.add(norm)
        junk: Set[str] = set()
        threshold = max(3, int(total * self.cfg.junk_line_ratio))
        for norm, cnt in counter.items():
            if cnt < threshold:
                continue
            has_hint = bool(JUNK_HINT_RE.search(norm)) or any(pat.search(norm) for pat in self.ad_patterns)
            ascii_heavy = sum(1 for c in norm if c.isascii()) / max(1, len(norm)) > 0.4
            if has_hint or ascii_heavy:
                junk.add(norm)
        if junk:
            log.info("跨章节统计发现 %d 种疑似插入广告行", len(junk))
        return junk

    # ---------- 阶段 5：质量检查 ----------
    def check_quality(self, paragraphs: Sequence[str]) -> Tuple[str, List[str]]:
        """返回 (status, problems)。status: ok / suspicious。"""
        problems: List[str] = []
        text = "".join(paragraphs)
        length = len(text)
        if length < self.cfg.min_chapter_len:
            problems.append("正文过短({})".format(length))
        if not paragraphs:
            problems.append("无正文")
        elif length:
            junk_chars = len(PUA_RE.findall(text))
            pua_ratio = junk_chars / length
            mass = len(MASS_RE.findall(text))
            if mass / max(1, length) < 0.5:
                problems.append("中文文本占比过低({:.1%})".format(mass / length))
            elif pua_ratio > 0.02:
                if self._font_table:
                    # 已配解密表仍残留 PUA => 字体映射不全，补爬无益，仅告警
                    log.warning("字体解密不完整：仍有 {:.1%} PUA 字符".format(pua_ratio))
                else:
                    log.info("检测到加密字体（PUA 占比 {:.1%}），未配置解密，正文将保留原码位".format(pua_ratio))
        status = "suspicious" if problems else "ok"
        return status, problems
