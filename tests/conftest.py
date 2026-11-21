# -*- coding: utf-8 -*-
import os
import sys

# 让测试直接以仓库根为包路径运行（无需 pip install）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@pytest.fixture
def fixture_html():
    def _read(rel_path: str) -> str:
        with open(os.path.join(FIXTURES, rel_path), "r", encoding="utf-8") as fp:
            return fp.read()
    return _read
