# -*- coding: utf-8 -*-
"""旧版产物（tests/fixtures/legacy_output/*.html）作为真实文本夹具：
验证 cleaner 的质量检查与广告过滤不会误伤正常章节正文。"""

import re

from ebookmaker.cleaner import Cleaner
from ebookmaker.config import CleanerConfig

LEGACY_FILES = ["chapter282.html", "chapter284.html", "chapter3031.html",
                "chapter5091.html", "chapter972.html"]

P_RE = re.compile(r'<p class="a">(.*?)</p>')
H2_RE = re.compile(r'<h2 id="title"[^>]*>(.*?)</h2>')


def test_legacy_chapters_pass_quality(fixture_html):
    cleaner = Cleaner(CleanerConfig())
    for name in LEGACY_FILES:
        html = fixture_html("legacy_output/" + name)
        title = H2_RE.search(html).group(1)
        paragraphs = [p for p in P_RE.findall(html) if p.strip()]
        assert len(paragraphs) > 10, name + " 段落太少"
        status, problems = cleaner.check_quality(paragraphs)
        assert status == "ok", "{}: {}".format(name, problems)
        # 二次清洗不应吞掉正文（旧产物本身已净化过；引号断行规则允许段落数变化）
        cleaned = cleaner.clean_paragraphs(paragraphs, chapter_index=1, title=title)
        before = sum(len(re.sub(r"\s", "", p)) for p in paragraphs)
        after = sum(len(re.sub(r"\s", "", p)) for p in cleaned)
        assert after / before > 0.97, "{}: {} -> {}".format(name, before, after)
