# -*- coding: utf-8 -*-
"""CLI 入口测试：一步式 URL 用法与单步命令保留。"""

from ebookmaker import cli
from ebookmaker.store import BookStore


# ---------- normalize_argv ----------
def test_normalize_bare_url():
    assert cli.normalize_argv(["https://x.com/book/1/"]) == \
        ["run", "--url", "https://x.com/book/1/"]
    # URL 后仍可带 run 的子参数
    assert cli.normalize_argv(["http://x/b/", "--threads", "4"]) == \
        ["run", "--url", "http://x/b/", "--threads", "4"]


def test_normalize_keeps_explicit_forms():
    for argv in (["run", "--url", "http://x/"], ["crawl", "--url", "http://x/"],
                 ["build", "books/x"], ["convert", "a.epub"],
                 ["-q", "http://x/"], []):
        assert cli.normalize_argv(argv) == list(argv)


# ---------- main 分发 ----------
def test_main_one_step_dispatches_run(tmp_path, monkeypatch):
    calls = {}

    def fake_crawl(cfg, url, site, rules_dirs, force, sources=None):
        calls["crawl"] = url
        return BookStore(str(tmp_path / "书"))

    def fake_build(cfg, store, formats):
        calls["build"] = formats
        return 0

    monkeypatch.setattr(cli, "cmd_crawl", fake_crawl)
    monkeypatch.setattr(cli, "cmd_build", fake_build)
    rc = cli.main(["https://novel.example.com/book/1/", "--threads", "3"])
    assert rc == 0
    assert calls["crawl"] == "https://novel.example.com/book/1/"
    # 默认格式集合包含 epub/mobi/azw3（epub 必出）
    assert "epub" in calls["build"] and "azw3" in calls["build"]


def test_main_single_step_commands(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "cmd_crawl",
                        lambda cfg, url, site, rd, force, sources=None: (seen.__setitem__("cmd", "crawl"),
                                                           BookStore(str(tmp_path / "c")))[1])
    monkeypatch.setattr(cli, "cmd_build",
                        lambda cfg, store, formats: (seen.__setitem__("cmd", "build"), 0)[1])
    assert cli.main(["crawl", "--url", "https://x/b/"]) == 0
    assert seen["cmd"] == "crawl"
    assert cli.main(["build", str(tmp_path / "c"), "--formats", "epub"]) == 0
    assert seen["cmd"] == "build"


def test_main_no_args_shows_help(capsys):
    assert cli.main([]) == 1
    out = capsys.readouterr().out
    assert "usage" in out.lower()


def test_log_book_info_output(caplog):
    import logging
    from ebookmaker.models import BookMeta
    meta = BookMeta(title="测试书", author="某某", category="玄幻",
                    update_time="2026-11-21 12:00:00", description="简" * 200)
    with caplog.at_level(logging.INFO, logger="ebookmaker.cli"):
        cli._log_book_info(meta, 1234, cover_ok=False)
    text = caplog.text
    assert "书名：测试书" in text
    assert "作者：某某" in text
    assert "章节数：1234" in text
    assert "封面：未获取" in text
    assert "简介：" in text
    # 简介截断到 160 字符 + 省略号
    assert "简" * 161 not in text
