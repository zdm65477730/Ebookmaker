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
# 括号拼音注音（源站在正文汉字里插“（汉字+拼音”防盗/注音）：汉字是正文必要
# 内容，只去拼音与括号：“七大(禁jin)地”→“七大禁地”；允许拼音后带 1~2 个
# 孤立字母噪声（“（荡dàng)d”形态，后接汉字才删，防误伤英文词）
_PINYIN_ANNO_RE = re.compile(
    r"[(（]([\u4e00-\u9fff]{1,3})[a-zà-ǜ]+(?:\s+[a-zà-ǜ]+)*[)）]"
    r"(?:[a-z]{1,2}(?=[\u4e00-\u9fff]|$))?")
# 纯拼音括号（汉字已在括号外，括号内只是注音）→ 整体删除：“禁(jin)地”→“禁地”
_PURE_PINYIN_RE = re.compile(
    r"[(（][a-zà-ǜ]+(?:\s+[a-zà-ǜ]+)*[)）]")


def _strip_paren_pinyin(text: str) -> str:
    """括号拼音注音按内容判定：括号含汉字则保留汉字去拼音，纯拼音则整体去。"""
    text = _PINYIN_ANNO_RE.sub(r"\1", text)
    return _PURE_PINYIN_RE.sub("", text)
# 连续 &nbsp; 残留
NBSP_RE = re.compile(r"(?:\u00a0|&nbsp;)+")

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
PUA_RE = re.compile(r"[\ue000-\uf8ff\ufffd]")
# 中文文本当量（含 PUA）：字体加密站未解密时不应因此反复补爬
MASS_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\ue000-\uf8ff]")

# ---------- 行级广告黑名单（常见站点水印/引导语的通用特征） ----------
AD_LINE_PATTERNS = [re.compile(p, re.I) for p in (
    r"https?://|www\.|m\.[a-z0-9\-]+\.(com|net|cc|org)|\.(com|net|cc|la|xyz)(?=[^\w]|$)",
    r"(请?收藏|记住|首发|最新更新|最快更新).{0,30}(小说|网址|地址|域名)",
    r"(笔趣?阁|顶点小说|八一?小说|书海阁|69书吧|妙笔阁|oku|书旗|起点|横店|嘉年华).{0,20}(小说|无弹窗|无弹窗|提醒您|首发)",
    r"(本章未完|点击下一页|下一章自己找|请返回|章节目录|加入书签|章节错误|报错|举报)",
    r"^上?下一[页章]\s*[目书]?[录籍]?\s*$",
    r"^(?:本\s*[页章节]?\s*(?:已)?完[成全]|本章结束|全文完|正文完|待续未完)[！!。\s]*$",
    r"(加载中|请稍候|请稍等|please wait|loading)",
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

# 页尾导航标记整行（未删前参与 clean_page 行锚扫描，删后不影响正文）：
#  A. 未完/完成类标记 + 省略号/破折号尾缀（如“本章未完，请翻下一页继续阅读......”）
#  B. 纯标记短句（如“本章已完成！”“（本章完）”，无句号且≤16字）
_PAGE_MARKER_LINE_RE = re.compile(
    r"^(?:本\s*[页章节]?\s*(?:已)?完[成全]|本章未完)[，,]?[^。！？]{0,24}[.。…~～*＊—-]{3,}$"
    r"|^（?本\s*[页章节]?\s*(?:已)?完[成全](?:本)?）?[！!]?$")

# 页内分页指示符：(第N/M页)，N==M 表示末页
PAGE_INDICATOR_RE = re.compile(
    r"[（(\u3010\[]\s*第?\s*(\d+)\s*[/／]\s*(\d+)\s*页?\s*[)）\u3011\]]")
PAGE_SUFFIX_RE = re.compile(r"(?:[（(\u3010\[]\s*(?:第\s*)?\d+\s*(?:[页\u9875]?\s*[/／]\s*共?\s*\d+|[/／]\s*\d+)\s*[)）\u3011\]])+$")

# 句末标点（用于区分正文短句与“书名类”推荐行）
SENTENCE_END_RE = re.compile(r"[。\u3002！？!?…〜~]$")

# URL/域名行（置信度噪声信号用）
URL_RE = re.compile(r"https?://|www\.|\.(com|net|cc|org|xyz|la)(?=[/\s]|$)", re.I)

# 导航列表行：一行里连缀了多个“第N章”标题（页面侧边章节列表被并入正文）
NAV_MARKER_RE = re.compile(r"第\s*[0-9０-９一二三四五六七八九十百千两]+\s*[章节回]")

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
    # 标题分隔符等价类：冒号/空格/间隔号等书写差异（“第1章：重生” vs “第1章 重生”）
    _TITLE_SEP_RE = re.compile(r"[\s：:、，,·・．.\-—_~～]+")
    _CH_HEAD_RE = re.compile(r"^第\s*(\d+)\s*[章节回]")

    @classmethod
    def _title_key(cls, s: str) -> str:
        """标题等价键：剥分页后缀后去掉全部分隔符。"""
        return cls._TITLE_SEP_RE.sub("", PAGE_SUFFIX_RE.sub("", s))

    @staticmethod
    def _is_title_line(text: str, norm_title: str) -> bool:
        if not norm_title:
            return False
        nt = Cleaner._normalize(text)
        if not nt:
            return False
        if nt == norm_title or PAGE_SUFFIX_RE.sub("", nt) == norm_title:
            return True
        # 分隔符等价：源站正文标题行写法与目录不一致（冒号/间隔号）时仍能识别；
        # 长度守护避免正文恰好以“第1章”三字符独立成行被误删
        a, b = Cleaner._title_key(nt), Cleaner._title_key(norm_title)
        if a and a == b and len(a) >= 4:
            return True
        # 章号一致 + 等价键子串：覆盖“第8章：”（标题拆行）与源站标题截断
        # （正文“第56章：败名裂” vs 目录“第56章 身败名裂”）；叙事句子不会
        # 恰好是目录标题的子串，故无误伤
        m1 = Cleaner._CH_HEAD_RE.match(nt)
        m2 = Cleaner._CH_HEAD_RE.match(norm_title)
        if (m1 and m2 and m1.group(1) == m2.group(1)
                and len(nt) <= 30
                and not re.search(r"[。，！？；…]", nt)):   # 标题行不带句读，叙事句几乎必带
            # 以本章章号开头的短行且无任何句读→标题行：覆盖源站正文页标题
            # 与目录措辞不同/截断/拆行（如目录“第18章 神秘古书”、正文页
            # “第18章：古朴小剑”）；叙事段落几乎不可能无句读且独立短行
            return True
        return False

    def _locate_start(self, raw_lines: Sequence[str], title: str) -> List[str]:
        """起始锚：预清洗（不过滤广告行）后定位首个“本章标题行”，从它开始取；
        找不到（标题在容器外或未渲染）则原样返回，交由后续过滤。"""
        norm_title = self._normalize(title) if title else ""
        if not norm_title:
            return list(raw_lines)
        for i, line in enumerate(raw_lines):
            text = CONTROL_RE.sub("", ZERO_WIDTH_RE.sub("", line)).strip()
            if self._is_title_line(self._restore_font(text), norm_title):
                return list(raw_lines[i:])
        return list(raw_lines)

    def _prefilter(self, raw_lines: Sequence[str],
                   junk_lines: Optional[Set[str]] = None,
                   title: str = "",
                   keep_page_markers: bool = False) -> List[str]:
        """字符级预清洗 + 静态广告/junk 行过滤 + 本章标题行剔除。"""
        norm_title = self._normalize(title) if title else ""
        lines = []
        for line in raw_lines:
            text = self._pre_clean_line(line, junk_lines, keep_page_markers)
            if not text:
                continue
            # 正文里重复出现的本章标题行（旧 bageoo 配置“第N章 ”剔除规则的通用化）
            if self._is_title_line(text, norm_title):
                continue
            lines.append(text)
        return lines

    def clean_paragraphs(self, raw_lines: Sequence[str], chapter_index: int = 0,
                         junk_lines: Optional[Set[str]] = None,
                         title: str = "") -> List[str]:
        lines = self._prefilter(raw_lines, junk_lines, title)
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
        # 第四步：结构性块清除（章节导航列表 / 连续短行推荐块，频率法覆盖不到的轮换推荐位）
        return self._drop_list_blocks(out)

    # ---------- 逐页定位清洗（分页章节的拼接单元，参考 go-crawler 行锚定算法） ----------
    #: 续页锚：本页未完/请翻下一页——从该行起全部截断，并告知调用方需继续拼下一页
    PAGE_BREAK_RES = (
        re.compile(r"本\s*[页章节]\s*未\s*完"),
        re.compile(r"请?翻[下后]|点击?下一[页頁]|下一[页頁]再看|下一章见|下章接着|接着看|继续阅读|未完待续"),
        re.compile(r"^下一\s*[页頁]$"),
        re.compile(r"to\s+be\s+continued", re.I),
    )
    #: 完页锚：本章已完成/加入书签/记住本站——截断但无需续页（组合词，避免误伤叙事短句）
    PAGE_END_RES = (
        re.compile(r"本\s*[页章节]?\s*(已)?完成|本章结束|全文完|正文完|待续未完"),
        re.compile(r"加入书签|加入收藏|记住本?站|返回目录|首页|作者更新|求收藏|求推荐|求月票|小说最新章节"),
    )

    @classmethod
    def _page_break_signal(cls, line: str) -> bool:
        core = line.rstrip(".。…~～*＊— -")
        return len(core) <= 20 and any(p.search(core) for p in cls.PAGE_BREAK_RES)

    @classmethod
    def _page_end_signal(cls, line: str) -> bool:
        # 强完页锚（本章已完成等）：短行且任意位置命中即截断；
        # 弱导航按钮词（加入书签/首页等）：仅尾部窗口参与，降低误伤叙事短句的风险。
        core = line.rstrip(".。…~～*＊— -")
        if len(core) > 20:
            return False
        if any(p.search(core) for p in cls.PAGE_END_RES[:1]):
            return True
        return any(p.search(core) for p in cls.PAGE_END_RES[1:])

    def clean_page(self, raw_lines: Sequence[str], title: str = "",
                   junk_lines: Optional[Set[str]] = None) -> Tuple[List[str], bool]:
        """清洗“单页”正文并定位页尾，返回 (正文段落, 是否还有下一页)。

        三重锚定：
        1) 起始锚：首个“等于本章标题（含分页后缀）”的预清洗行之前全部丢弃
           （导航/面包屑混入容器的情形一并被切掉）；
        2) 结束锚（短行才参与判定，避免误伤正文）：命中续页锚则从该行截断且
           needs_next=True；未命中但尾部窗口内有完页锚则从那里截断且 needs_next=False；
           两者都没有时保守 needs_next=True（由调用方的序列探针/链接探测去证明有无下页，
           空页即停）；
        3) 块清除：导航列表/连续短行推荐块逐页删除，防止相邻页的推荐块连成长 run
           超过阈值而漏删。
        """
        lines = self._locate_start(raw_lines, title)
        # 预清洗但保留页尾标记行（……结尾）参与行锚扫描；扫描完成后再剔除
        # 检测末页指示符：“(第N/M页)” 且 N==M → 这是最后一页，无需再续
        _this_is_last = False
        for _raw in list(raw_lines)[:3]:   # 前3行扫描（指示符常在开头）
            _m = PAGE_INDICATOR_RE.search(_raw)
            if _m and int(_m.group(1)) == int(_m.group(2)):
                _this_is_last = True
                break
        lines = self._prefilter(lines, junk_lines, title, keep_page_markers=True)
        needs_next = True
        cut = None
        for i, line in enumerate(lines):
            if self._page_break_signal(line):
                cut = i
                break
            if self._page_end_signal(line) and i >= len(lines) - 12:
                cut = i
                needs_next = False
                break
        if cut is not None:
            lines = lines[:cut]
        lines = [l for l in lines if not _PAGE_MARKER_LINE_RE.match(l)]
        # 末页指示符覆盖：即使没找到结束锚也确认不需翻页
        if _this_is_last:
            needs_next = False
        out = []
        for line in lines:
            final = self._finalize_line(line)
            if final:
                out.append(final)
        return self._drop_list_blocks(out), needs_next

    def _pre_clean_line(self, line: str, junk_lines: Optional[Set[str]],
                        keep_page_markers: bool = False) -> str:
        text = CONTROL_RE.sub("", ZERO_WIDTH_RE.sub("", line))
        text = self._restore_font(text)          # 先还原加密字体码位
        text = NBSP_RE.sub(" ", text)
        text = _strip_paren_pinyin(text)
        text = NOISE_SYMBOL_RE.sub("", text)
        text = re.sub(r"[ \t]+", " ", text).strip()
        if not text:
            return ""
        # 静态广告行
        for pat in self.ad_patterns:
            if pat.search(text):
                # 页尾导航标记行（……/…结尾）默认删除；keep_page_markers 时保留供行锚扫描
                if not (keep_page_markers and _PAGE_MARKER_LINE_RE.match(text)):
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
    def _is_navlist(line: str) -> bool:
        return len(NAV_MARKER_RE.findall(line)) >= 3

    def _drop_list_blocks(self, lines: Sequence[str]) -> List[str]:
        """丢弃结构性切块（与站点无关的通用启发）：

        1) 导航列表行：单行内含 ≥3 个“第N章”标记（侧边章节列表被当正文）。
        2) 推荐/书友块：连续 ≥junk_block_run 段、每段≤junk_title_max_len 且不含句号，
           这种“连续短句无句号”的长条不可能是叙事正文（叙事段落通常带句号且较长）。
        """
        short_max = self.cfg.junk_title_max_len
        run_min = 8
        tail_run_min = 4   # 章节末尾的推荐位（高频法删剩的轮换书名）用更低阈值
        kept: List[str] = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if self._is_navlist(line):
                i += 1
                continue
            if len(line) <= short_max and "。" not in line:
                j = i
                while (j < n and len(lines[j]) <= short_max and "。" not in lines[j]
                       and not self._is_navlist(lines[j])):
                    j += 1
                is_tail = (j == n)
                need = tail_run_min if is_tail else run_min
                if j - i >= need:
                    i = j          # 整块丢弃
                    continue
            kept.append(line)
            i += 1
        return kept

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
            head = list(paragraphs[:self.cfg.junk_head_lines])
            tail = list(paragraphs[-self.cfg.junk_tail_lines:])
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
            # 推荐位/书友切块的书名行：短、无句末标点，但本批样本里未携带广告词/ASCII，
            # 需要靠“跨大量章节尾部高频重现”兼判；真实剧情句不会逐字重复出现于多章尾部。
            title_like = (len(norm) <= self.cfg.junk_title_max_len
                          and not SENTENCE_END_RE.search(norm))
            if has_hint or ascii_heavy or title_like:
                junk.add(norm)
        if junk:
            log.info("跨章节统计发现 %d 种疑似插入广告行", len(junk))
        return junk

    # ---------- 阶段 5：质量检查 ----------
    def chapter_confidence(self, paragraphs: Sequence[str], title: str = "") -> Tuple[float, List[str]]:
        """章节正文置信度（与站点无关的通用信号）：返回 (0~1, 原因列表)。

        惩罚项（按占正文字符比例）：导航列表块 / 连续短行无句号块（推荐位）/
        URL 行 / 广告命中行 / PUA 残留 / 重复章名行；正面项：句号密度（叙事文体
        下限，对话体引号内句号仍自然达标，不误伤）、文本量饱和项。
        注意：只作质量闸门与审核报告，**绝不用于分页提前停止**。"""
        text = "".join(paragraphs)
        n = len(text)
        if n == 0:
            return 0.0, ["无正文"]
        problems: List[str] = []
        short_max = self.cfg.junk_title_max_len
        noise = 0
        # 1) 导航列表行（单行 ≥3 个“第N章”）
        for p in paragraphs:
            if self._is_navlist(p):
                noise += len(p)
        # 2) 连续短行无句号块（任意位置 ≥8，章尾 ≥4）
        i, cnt = 0, len(paragraphs)
        while i < cnt:
            if len(paragraphs[i]) <= short_max and "。" not in paragraphs[i] \
                    and not self._is_navlist(paragraphs[i]):
                j = i
                while (j < cnt and len(paragraphs[j]) <= short_max
                       and "。" not in paragraphs[j] and not self._is_navlist(paragraphs[j])):
                    j += 1
                if (j == cnt and j - i >= 4) or j - i >= 8:
                    noise += sum(len(x) for x in paragraphs[i:j])
                i = j
            else:
                i += 1
        # 3) URL/广告命中行（广告黑名单已删大部分，这里抓二次过滤未覆盖的）
        for p in paragraphs:
            if URL_RE.search(p) or any(pat.search(p) for pat in self.ad_patterns):
                noise += len(p)
        # 4) 重复章名行（剥分页后缀后等于章名）
        norm_title = self._normalize(title) if title else ""
        if norm_title:
            for p in paragraphs:
                if self._is_title_line(p, norm_title):
                    noise += len(p)
        # 5) PUA 残留（字体未解）
        pua = len(PUA_RE.findall(text))

        penalty = min(0.6, 0.6 * noise / n) + min(0.3, 0.6 * pua / n)
        score = 1.0 - penalty

        periods = text.count("。") + text.count("？") + text.count("！")
        density = periods / n
        if density < 0.005:                       # 叙事文体句号密度下限
            score -= 0.25
            problems.append("句号密度过低({:.3%})".format(density))
        if n < self.cfg.min_chapter_len:
            score -= 0.25
            problems.append("正文过短({})".format(n))
        # 文本量饱和项：长章更可信
        score += 0.1 * min(1.0, n / 1500.0)
        if noise:
            problems.append("噪声占比{:.0%}".format(noise / n))
        return max(0.0, min(1.0, score)), problems

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
