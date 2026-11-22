# -*- coding: utf-8 -*-
"""页级全文审查管线（review_page + 激进清洗联动）的离线验证。"""

from ebookmaker.cleaner import Cleaner
from ebookmaker.config import CleanerConfig


def _c():
    return Cleaner(CleanerConfig())


NARRATIVE = [
    "夜色如墨，远处的山峦在月光下起伏如浪。",
    "他握紧了手中的剑，指节因用力而发白。",
    "风从谷口灌进来，吹得衣袍猎猎作响。",
    "终于，第一缕晨光刺破云层，照在了那面残破的旗帜上。",
]


def test_review_clean_page_passes():
    r = _c().review_page(NARRATIVE, title="第1章 测试")
    assert not r.severe
    assert r.findings == []
    assert r.cjk_ratio > 0.7
    assert r.punct_ratio > 0.03


def test_review_blank_page_severe():
    r = _c().review_page(["", "   "])
    assert r.severe and "空白页" in r.findings


def test_review_detects_each_noise_class():
    c = _c()
    # 符号水印（交替型，统计必须基于原始文本）
    r = c.review_page(["♂领♂域♂文♂学♂*♂♂ng♂♂g"] + NARRATIVE)
    assert r.watermark_hits >= 6 and "符号水印" in r.findings
    # 拼音乱码括号（≥8 处才判 severe）
    r = c.review_page(["他(身shēn)体一震。", "淫(荡dàng)归一笑。",
                       "禁(jìn)地之中，有(fú)光升腾。", "这是(禁jin)地。",
                       "秦(尘chén)抬头，看(向xiàng)远方。", "杀(意yì)沸腾。"] + NARRATIVE)
    assert r.pinyin_hits >= 8 and "拼音乱码" in r.findings
    # 导航列表
    r = c.review_page(["第1章 重生 第2章 母亲 第3章 赵夫人 第4章 杀"] + NARRATIVE)
    assert r.navlist_hits >= 1 and "导航列表混入" in r.findings
    # 广告/URL 行
    r = c.review_page(["最快更新请收藏http://www.xiaoshuo.com小说网址。",
                       "请收藏www.b.com记住本站域名。",
                       "无弹窗最新章节请访问http://m.y.com"] + NARRATIVE)
    assert r.url_hits >= 2 and "URL行" in r.findings
    # 页内行重复
    dup = ["他缓缓抬起头"] * 5 + ["窗外下起了雨"] * 5
    r = c.review_page(dup)
    assert r.dup_line_ratio > 0.4 and "页内行重复" in r.findings
    # PUA 残留
    r = c.review_page(["\ue000\ue001\ue002" * 10] + NARRATIVE)
    assert r.pua_hits > 0 and "PUA残留" in r.findings


def test_clean_page_auto_aggressive_from_review():
    # 预审 severe（6 个水印符号）→ 自动启用激进块清除：5 连短书名块被删
    lines = ["♂a♂b♂c♂d♂e♂", "短书名一", "短书名二", "短书名三",
             "短书名四", "短书名五", "正常正文段落，这里带句号。"]
    out, _needs = _c().clean_page(lines, title="第1章 测试")
    assert out == ["正常正文段落，这里带句号。"]
    # 显式关闭激进：同样的短块（5 段）达不到常规阈值 8，保留
    out2, _ = _c().clean_page(lines, title="第1章 测试", aggressive=False)
    assert "短书名一" in out2


def test_review_metrics_shape():
    r = _c().review_page(NARRATIVE, title="第1章 测试")
    assert r.n_lines == 4 and r.n_chars > 50
    assert 0.0 <= r.noise_ratio <= 1.0
    assert isinstance(r.findings, list)
