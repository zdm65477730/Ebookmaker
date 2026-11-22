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


def test_sticky_title_prefix():
    # 真实形态（武神主宰 ch226/238）：源站标题行后无换行，标题与正文首句粘连同段
    c = Cleaner(CleanerConfig())
    out = c.clean_paragraphs(
        ["第226章阻拦这突如其来的一幕，令得所有人都大惊。", "“所有人都退后。”"],
        title="第226章 阻拦")
    assert out == ["这突如其来的一幕，令得所有人都大惊。", "“所有人都退后。”"]
    out2 = c.clean_paragraphs(["第238章一个耳光张斐脸色，陡然一变。"], title="第238章 一个耳光")
    assert out2 == ["张斐脸色，陡然一变。"]
    # 不误伤：正文叙事恰好以相似字开头但非标题键完全匹配
    keep = ["第226章的阻拦来得及时，众人惊魂未定。"]
    assert c.clean_paragraphs(keep, title="第226章 阻拦") == keep
    # 源站标题章号笔误（ch244 真实形态）：正文页“第2章封杀”，目录“第244章 封杀”
    out3 = c.clean_paragraphs(["第2章封杀秦奋知道，秦尘连大哥都能打伤。"],
                              title="第244章 封杀")
    assert out3 == ["秦奋知道，秦尘连大哥都能打伤。"]
    # 单字章名不走宽松路径（防误剥“杀死…”叙事段）
    keep2 = ["第9章杀死那个叛徒。"]
    assert c.clean_paragraphs(keep2, title="第4章 杀")[0] == keep2[0]


def test_watermark_and_promo_lines():
    c = Cleaner(CleanerConfig())
    # 交替型水印：不能只去符号留下站点名“领域文学”
    out = c.clean_paragraphs(["♂领♂域♂文♂学♂*♂♂ng♂♂g", "正文一句。"], title="x")
    assert out == ["正文一句。"]
    # 真实残留形态（武神主宰 ch3280/4865）
    out2 = c.clean_paragraphs(
        ["秦尘微微一笑。", "更多精彩尽在138du。", "ins/ins", "转身就走。"],
        title="x")
    assert out2 == ["秦尘微微一笑。", "转身就走。"]
    # 不误伤：含“更多”字样的正常叙事、少量单个装饰符号的句子不被整行删
    assert c.clean_paragraphs(["他想要更多，更多力量。"], title="x") == ["他想要更多，更多力量。"]
    assert c.clean_paragraphs(["☆新星升起。"], title="x")[0].startswith("新星")


def test_dun_list_and_nav_button_lines():
    # 真实形态（mxgbq.cc）：首段顿号连缀书名推荐行 + 章尾“上一章”按钮
    c = Cleaner(CleanerConfig())
    noise = ["推荐阅读：至尊神魔、权路迷局、直死无限、古董商的寻宝之旅、"
             "天域苍穹、超级吞噬系统、圣墟、男人不低头、美女总裁的贴身狂少、灵武帝尊",
             "上一章", "正文结束。"]
    out = c.clean_paragraphs(noise, title="第1章 开端")
    assert out == ["正文结束。"]
    # 上一/下一 双向按钮均命中（旧正则只命中“下X”）
    for l in ("上一章", "下一章", "上一页", "下一页"):
        assert c._finalize_line(l) == "", l
    # 不误伤：带句读的顿号叙事行、少量顿号项的句子均保留
    keep = ["这一路，有笑、有泪、有遗憾、有不甘、有重逢。",
            "他买了苹果、香蕉和橙。"]
    assert c.clean_paragraphs(keep, title="x") == keep
    # 无句读但连缀 ≥5 短顿号项的书名形态（频率法覆盖不到）走块清除
    assert Cleaner._is_dun_list("热点推文：甲乙、丙丁、戊己、庚辛、壬癸、子丑")
    assert not Cleaner._is_dun_list("甲、乙、丙、丁、戊己庚辛壬癸子丑寅卯辰巳午未申酉戌")  # 单项超 15 字


def test_paren_pinyin_keeps_hanzi():
    # 真实形态（武神主宰/bqg2 第一章）：“七大(禁jin)地”必须洗成“七大禁地”，
    # 括号里的汉字是正文必要内容，只能去拼音和括号
    c = Cleaner(CleanerConfig())
    out = c.clean_paragraphs(
        ["这里是天武大陆七大(禁jin)地之一，位于武域的死亡峡谷。"], title="第1章 重生")
    assert out == ["这里是天武大陆七大禁地之一，位于武域的死亡峡谷。"]
    # 多音节/带声调/括号后孤立字母噪声
    assert c.clean_paragraphs(["他(身shēn)体一震。"], title="x")[0] == "他身体一震。"
    assert c.clean_paragraphs(["淫(荡dàng)d妇一笑。"], title="x")[0] == "淫荡妇一笑。"
    # 纯拼音括号（汉字已在括号外）→ 整体删
    assert c.clean_paragraphs(["这是禁(jin)地。"], title="x")[0] == "这是禁地。"
    # 不误伤：纯中文括号、带大写英文的括号、分页后缀、数字括号
    for keep in ["此间(未完待续)另有一说。", "用(WiFi)连接。",
                 "正文结束(1/3)。", "他说(大笑)着离开。"]:
        assert c.clean_paragraphs([keep], title="x") == [keep]


def test_title_line_separator_variants():
    # 真实形态（武神主宰/bqg2）：目录写“第1章 重生”，正文页标题行写“第1章：重生”
    # 去重必须跨分隔符形态生效；同时不误伤恰好以章号开头的叙事句
    c = Cleaner(CleanerConfig())
    out = c.clean_paragraphs(
        ["第1章：重生", "武神历2216年。", "天武大陆至高之地——武域。"],
        title="第1章 重生")
    assert out == ["武神历2216年。", "天武大陆至高之地——武域。"]
    # 带分页后缀的冒号形态（多页拼接时每页各插一次）
    out2 = c.clean_paragraphs(
        ["第1章：重生（2/3）", "正文段落一。", "正文段落二。"],
        title="第1章 重生")
    assert out2 == ["正文段落一。", "正文段落二。"]
    # 间隔号/全角空格形态
    out3 = c.clean_paragraphs(["第1章・重生", "正文。"], title="第1章 重生")
    assert out3 == ["正文。"]
    # 不误伤：正文句子提及章名但不独立成标题行
    keep = ["第1章 重生是全书的起点，很多人讨论过。"]
    assert c.clean_paragraphs(keep, title="第1章 重生") == keep
    # 标题拆行：“第8章：”独立成行，内容在下一行
    out4 = c.clean_paragraphs(["第8章：", "无双天下。", "正文。"], title="第8章 无双天下")
    assert out4 == ["无双天下。", "正文。"]
    # 源站标题截断：正文“第56章：败名裂” vs 目录“第56章 身败名裂”
    out5 = c.clean_paragraphs(["第56章：败名裂", "正文内容。"], title="第56章 身败名裂")
    assert out5 == ["正文内容。"]
    # 截断条款不误伤：叙事句含章号但非标题形态
    keep2 = ["第56章 身败名裂这五个字像一记耳光抽在他脸上，他永远不会忘记。"]
    assert c.clean_paragraphs(keep2, title="第56章 身败名裂") == keep2
    # 源站正文页标题措辞与目录完全不同（武神主宰 ch18 真实形态）
    out6 = c.clean_paragraphs(["第18章：古朴小剑", "正文。"], title="第18章 神秘古书")
    assert out6 == ["正文。"]
    # 措辞不同条款不误伤：章号开头的长叙事段（带句读）
    keep3 = ["第18章 神秘古书他翻来覆去看了三遍还是看不出所以然。"]
    assert c.clean_paragraphs(keep3, title="第18章 神秘古书") == keep3
