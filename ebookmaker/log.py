# -*- coding: utf-8 -*-
"""统一日志配置。

支持进度条共存：通过 set_progress_hooks 注册擦除/重绘回调，
每条日志输出前擦掉当前进度行、输出后重绘（tqdm 同类做法），
保证进度条永远只占最底下一行。
"""

import logging
import sys

_CONFIGURED = False
_PROGRESS_HOOKS = {"clear": None, "redraw": None}


def set_progress_hooks(clear=None, redraw=None):
    """注册/注销进度条钩子（由 downloader.Progress 调用）。"""
    _PROGRESS_HOOKS["clear"] = clear
    _PROGRESS_HOOKS["redraw"] = redraw


class _ProgressAwareHandler(logging.StreamHandler):
    """日志与单行进度条共用 stdout 时互不破坏。"""

    def emit(self, record):
        clear = _PROGRESS_HOOKS["clear"]
        redraw = _PROGRESS_HOOKS["redraw"]
        if clear:
            try:
                clear()
            except Exception:
                pass
        try:
            super().emit(record)
        finally:
            if redraw:
                try:
                    redraw()
                except Exception:
                    pass


def setup_logging(verbosity: int = 0):
    """verbosity: 0=INFO, 1=DEBUG, <0=WARNING"""
    global _CONFIGURED
    level = logging.INFO
    if verbosity >= 1:
        level = logging.DEBUG
    elif verbosity < 0:
        level = logging.WARNING

    handler = _ProgressAwareHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # 第三方库降噪
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("charset_normalizer").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    if not _CONFIGURED:
        setup_logging()
    return logging.getLogger(name)
