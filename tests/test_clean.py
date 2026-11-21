# -*- coding: utf-8 -*-
"""输出目录清理（clean 子命令）测试：裸清缓存留成品，--all 全删。"""

import os

from ebookmaker import cli
from ebookmaker.config import AppConfig
from ebookmaker.store import BookStore
from ebookmaker.models import BookMeta, ChapterData, TocEntry


def make_store(tmp_path, title="测试书", with_final=False):
    workdir = tmp_path / "books"
    root = workdir / title
    store = BookStore(str(root))
    store.save_meta(BookMeta(title=title))
    store.save_toc([TocEntry("1.html", "第一章")])
    store.save_chapter(ChapterData(index=1, title="第一章", url="u", paragraphs=["正文"] * 100))
    store.save_junk_lines(["广告行"])
    store.save_font_map({"\ue800": "中"})
    store.save_cover(b"jpgbytes", "jpg")
    if with_final:
        (workdir / (title + ".epub")).write_text("epub")
    return store, str(workdir)


def cfg_for(workdir):
    cfg = AppConfig()
    cfg.workdir = workdir
    return cfg


# ---------- 裸 clean：清缓存，留成品 ----------
def test_clean_removes_workspace_keeps_finals(tmp_path):
    store, workdir = make_store(tmp_path, with_final=True)
    rc = cli.cmd_clean(cfg_for(workdir), [])
    assert rc == 0
    assert not os.path.isdir(store.root)                     # 工作区（缓存）删除
    assert os.path.isfile(os.path.join(workdir, "测试书.epub"))  # 成品保留
    assert os.path.isdir(workdir)                            # 还有成品，目录保留


def test_clean_keeps_finals_even_without_them(tmp_path):
    """成品不存在时也照清缓存（不再有任何保护开关）。"""
    store, workdir = make_store(tmp_path, with_final=False)
    cli.cmd_clean(cfg_for(workdir), [])
    assert not os.path.isdir(store.root)
    assert os.path.isdir(workdir)


def test_clean_removes_stray_files(tmp_path):
    """workdir 里非成品书的杂项文件视为缓存一并删除。"""
    store, workdir = make_store(tmp_path, with_final=True)
    stray = os.path.join(workdir, "leftover.tmp")
    with open(stray, "w") as fp:
        fp.write("x")
    cli.cmd_clean(cfg_for(workdir), [])
    assert not os.path.exists(stray)
    assert os.path.isfile(os.path.join(workdir, "测试书.epub"))


def test_clean_dry_run(tmp_path):
    store, workdir = make_store(tmp_path, with_final=True)
    cli.cmd_clean(cfg_for(workdir), [], dry_run=True)
    assert os.path.isdir(store.root)
    assert os.path.isfile(os.path.join(workdir, "测试书.epub"))


# ---------- --all：全删 ----------
def test_clean_all_removes_everything(tmp_path):
    store, workdir = make_store(tmp_path, with_final=True)
    rc = cli.cmd_clean(cfg_for(workdir), [], everything=True)
    assert rc == 0
    assert not os.path.exists(workdir)   # 工作区+成品+books 目录本身


def test_clean_targets_scoped(tmp_path):
    """裸清指定工作区：只删缓存目录，该书成品也保留，其余不动。"""
    s1, workdir = make_store(tmp_path, title="书一", with_final=True)
    s2, _ = make_store(tmp_path, title="书二", with_final=True)
    cli.cmd_clean(cfg_for(workdir), [s1.root])
    assert not os.path.isdir(s1.root)
    assert os.path.isfile(os.path.join(workdir, "书一.epub"))   # 裸清保留成品
    assert os.path.isdir(s2.root)
    # --all 指定目标：连对应成品一起删
    cli.cmd_clean(cfg_for(workdir), [s2.root], everything=True)
    assert not os.path.isdir(s2.root)
    assert not os.path.exists(os.path.join(workdir, "书二.epub"))
    assert os.path.isdir(workdir)      # 书一成品还在


# ---------- cleanup.auto / --clean：与裸 clean 一致 ----------
def test_auto_clean_removes_workspace_keeps_final(tmp_path, monkeypatch):
    store, workdir = make_store(tmp_path, with_final=True)
    cfg = cfg_for(workdir)
    cfg.cleanup.auto = True
    monkeypatch.setattr(cli, "cmd_build", lambda c, s, f: 0)
    args = cli.argparse.Namespace(command="build", book_dir=store.root,
                                  formats="", clean=False)
    assert cli._dispatch(args, cfg) == 0
    assert not os.path.isdir(store.root)                       # 工作区已清
    assert os.path.isfile(os.path.join(workdir, "测试书.epub"))  # 成品保留


# ---------- CLI 分发 ----------
def test_cli_clean_dispatch(monkeypatch):
    seen = {}
    def fake_clean(cfg, targets, everything, dry_run):
        seen["args"] = (list(targets), everything, dry_run)
        return 0
    monkeypatch.setattr(cli, "cmd_clean", fake_clean)
    assert cli.main(["clean"]) == 0
    assert seen["args"] == ([], False, False)
    assert cli.main(["clean", "--all", "--dry-run"]) == 0
    assert seen["args"] == ([], True, True)


def test_normalize_argv_keeps_clean():
    assert cli.normalize_argv(["clean"]) == ["clean"]
    assert cli.normalize_argv(["clean", "books/x"]) == ["clean", "books/x"]
