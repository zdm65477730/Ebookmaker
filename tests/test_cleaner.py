# -*- coding: utf-8 -*-
"""净化管线测试（全部为内建通用逻辑，无规则文件）。"""

import re

from ebookmaker.cleaner import BUILTIN_CHAPTER_PATTERNS, Cleaner, ReplaceRule
from ebookmaker.config import CleanerConfig
from ebookmaker.sites.generic import GenericSite


def make_cleaner():
    return Cleaner(CleanerConfig())


def test_clean_removes_ads_and_watermarks(fixture_html):
    raw = GenericSite().parse_chapter(fixture_html("raw/xbiquge_chapter.html"), "http://x/")
    out = make_cleaner().clean_paragraphs(raw, chapter_index=1, title="第1章 少年秦尘")
    joined = "\n".join(out)
    assert "笔趣阁" not in joined
    assert "领" not in joined or "♂" not in joined          # 水印符号被清除
    assert "本章未完" not in joined
    assert "第1章 少年秦尘" not in joined                    # 正文重复标题行被剔除
    assert "嗡！" in joined
    # 半角逗号邻接中文 -> 全角
    assert "永恒天塔之灵，等待有缘人" in joined


def test_clean_xbooktxt_page_with_builtin_logic(fixture_html):
    """不再有任何站点专属规则，内建通用逻辑仍需清掉该页所有广告/乱码并修复标点。"""
    raw = GenericSite().parse_chapter(fixture_html("raw/xbooktxt_chapter.html"), "http://x/")
    out = make_cleaner().clean_paragraphs(raw, chapter_index=2, title="第2章 觉醒")
    joined = "\n".join(out)
    assert "顶点小说" not in joined
    assert "喜欢武神主宰" not in joined
    assert "————————————" not in joined
    # 半角标点邻接中文转全角 + “、“修复为左引号+冒号
    assert "：“什么？" in joined
    assert "、“" not in joined
    assert "秦尘淡淡说道，眼中精芒闪烁" in joined
    # 正常正文一字不丢
    assert "他缓缓抬起手，周围的灵气顿时疯狂的涌动起来" in joined


def test_builtin_quote_rules_apply_everywhere():
    """内建通用引号排版规则对所有站生效。"""
    c = make_cleaner()
    out = c.clean_paragraphs(["他道：“也好。”“那就动身吧。”"], chapter_index=1)
    # 引语粘连断行为整章规则，重清洗后段落数+1
    assert len(out) == 2 and out[1].startswith("“那就动身吧")


def test_zero_width_and_control_chars():
    c = make_cleaner()
    out = c.clean_paragraphs(["秦\u200b尘\x00test，加\uFEFF速"], chapter_index=1)
    assert out == ["秦尘test，加速"] or out == ["秦尘test，加速"]
    assert "\u200b" not in out[0] and "\x00" not in out[0] and "\ufeff" not in out[0]


def test_junk_line_frequency_scan():
    c = make_cleaner()
    chapters = []
    for i in range(1, 41):
        paras = [
            "天才一秒记住本站地址，每秒更新！",   # 章首高频广告
            "第{}章 测试章节标题".format(i),
            "正文段落甲乙丙丁戊己庚辛壬癸，子丑寅卯辰巳午未申酉戌亥。" * 10,
            "正文段落内容是唯一的不会重复出现的句子编号{}".format(i),
            "请记住本站书名加入收藏夹。",          # 章尾高频广告
        ]
        chapters.append((i, paras))
    junk = c.find_junk_lines(chapters)
    norm = {c._normalize(l) for l in ("天才一秒记住本站地址，每秒更新！", "请记住本站书名加入收藏夹。")}
    assert norm <= junk
    # 正文唯一句子不误杀
    assert not any("子丑寅卯" in j for j in junk)


def test_junk_lines_filtered_in_clean(fixture_html):
    raw = GenericSite().parse_chapter(fixture_html("raw/xbiquge_chapter.html"), "http://x/")
    c = make_cleaner()
    junk = {c._normalize("与此同时，他的脑海中，一道苍老的声音缓缓响起，带着无尽的沧桑。")}
    out = c.clean_paragraphs(raw, chapter_index=1, junk_lines=junk, title="第1章 少年秦尘")
    joined = "\n".join(out)
    assert "与此同时" not in joined


def test_quality_checks():
    c = make_cleaner()
    status, problems = c.check_quality(["太短"])
    assert status == "suspicious" and problems
    status, _ = c.check_quality(["正常正文" * 100])
    assert status == "ok"
    # 非中文垃圾文本（拉丁乱码）才是真异常
    status, problems = c.check_quality(["ab12!@#~$%^&*()_+" * 30])
    assert status == "suspicious"
    # 字体加密站未配解密表：PUA 视为正常正文，不触发无效补爬
    status, _ = c.check_quality(["\ue000\ue001\ue002" * 150])
    assert status == "ok"


def test_cleaner_no_file_inputs():
    """Cleaner 构造不读取任何规则/配置文件，规则集固定为内建项。"""
    c1, c2 = Cleaner(CleanerConfig()), Cleaner(CleanerConfig())
    assert len(c1.rules) == len(c2.rules) == len(BUILTIN_CHAPTER_PATTERNS)


def test_replace_rule_chapter_scoped():
    rule = ReplaceRule(chapters={3}, pattern=re.compile("甲"), repl="乙")
    c = Cleaner(CleanerConfig(), [rule])
    assert c.clean_paragraphs(["测试甲"], chapter_index=3) == ["测试乙"]
    assert c.clean_paragraphs(["测试甲"], chapter_index=4) == ["测试甲"]
