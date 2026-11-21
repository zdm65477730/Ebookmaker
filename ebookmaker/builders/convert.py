# -*- coding: utf-8 -*-
"""Kindle 格式转换：calibre ebook-convert（首选）/ kindlegen（回退）。

- ebook-convert 支持 epub -> azw3 / mobi，活跃维护
- kindlegen 已被 Amazon 停止更新，但 tools/ 目录内仍有三平台二进制，作为回退；
  它可从 epub 一次产出 mobi + azw3
- 两者都缺失时打印安装指引，不影响已生成的 epub
"""

import os
import platform
import shutil
import subprocess
from typing import List, Optional

from ..config import ConvertConfig
from ..log import get_logger

log = get_logger(__name__)

CALIBRE_INSTALL_HINT = """未找到 calibre 的 ebook-convert 工具，跳过 azw3/mobi 转换。
安装方式：
  Linux:   sudo -v && wget -nv -O- https://download.calibre-ebook.com/linux-installer.sh | sudo sh /dev/stdin
  macOS:   brew install --cask calibre  或  https://calibre-ebook.com/download_osx
  Windows: https://calibre-ebook.com/download_windows
也可在 config.yaml 的 convert.ebook_convert_path 指定已有路径。"""


def find_ebook_convert(cfg: ConvertConfig) -> Optional[str]:
    if cfg.ebook_convert_path and os.path.isfile(cfg.ebook_convert_path):
        return cfg.ebook_convert_path
    found = shutil.which("ebook-convert")
    if found:
        return found
    # 常见安装位置
    sysname = platform.system()
    guesses = {
        "Linux": ["/usr/bin/ebook-convert", "/usr/local/bin/ebook-convert",
                  os.path.expanduser("~/.local/bin/ebook-convert")],
        "Darwin": ["/Applications/calibre.app/Contents/MacOS/ebook-convert",
                   "/usr/local/bin/ebook-convert"],
        "Windows": [],
    }.get(sysname, [])
    for g in guesses:
        if os.path.isfile(g):
            return g
    return None


def find_kindlegen(cfg: ConvertConfig) -> Optional[str]:
    sysname = platform.system()
    name = {"Linux": "kindlegen-linux", "Darwin": "kindlegen-darwin",
            "Windows": "kindlegen.exe"}.get(sysname)
    if not name:
        return None
    path = os.path.join(cfg.tools_base_path, name)
    if os.path.isfile(path):
        if sysname != "Windows" and not os.access(path, os.X_OK):
            try:
                os.chmod(path, 0o755)
            except OSError:
                pass
        return path
    return None


def convert_epub(epub_path: str, formats: List[str], cfg: ConvertConfig,
                 language: str = "zh") -> List[str]:
    """把 epub 转为要求的格式集合，返回生成文件路径列表。"""
    formats = [f.lower() for f in formats if f.lower() in ("azw3", "mobi")]
    if not formats:
        return []
    outputs: List[str] = []
    base = os.path.splitext(epub_path)[0]

    ebook_convert = find_ebook_convert(cfg)
    if ebook_convert:
        for fmt in formats:
            out = base + "." + fmt
            cmd = [ebook_convert, epub_path, out,
                   "--language=" + ("zh" if language.startswith("zh") else language),
                   "--input-profile=kindle",
                   "--output-profile=kindle_pw3" if fmt == "azw3" else "--output-profile=generic_eink",
                   "--chapter-mark=pagebreak",
                   "--max-toc-links=0",
                   "--use-auto-toc",
                   "--mobi-toc-at-start" if fmt == "mobi" else "--insert-metadata",
                   "--prefer-metadata-cover",
                   "--remove-paragraph-spacing-indent-size=2"]
            if _run(cmd, "ebook-convert -> " + fmt):
                if os.path.isfile(out):
                    outputs.append(out)
        if outputs:
            return outputs
        # ebook-convert 全部失败则继续尝试 kindlegen

    kindlegen = find_kindlegen(cfg)
    if kindlegen:
        log.info("使用 kindlegen 回退转换（注意其已停止维护）...")
        # kindlegen 在 epub 同目录一次产出 mobi 与 azw3
        cmd = [kindlegen, epub_path, "-dont_append_source", "-c" + cfg.kindlegen_compression_level,
               "-locale", cfg.kindlegen_locale]
        if _run(cmd, "kindlegen"):
            for fmt in formats:
                out = base + "." + fmt
                if os.path.isfile(out):
                    outputs.append(out)
        return outputs

    log.warning(CALIBRE_INSTALL_HINT)
    if not find_kindlegen(cfg):
        log.warning("tools/ 目录也未找到 kindlegen 二进制，无法转换 %s", ",".join(formats))
    return outputs


def _run(cmd: List[str], tag: str) -> bool:
    log.info("执行: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              encoding="utf-8", errors="replace", timeout=3600)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.error("%s 启动失败: %s", tag, e)
        return False
    tail = (proc.stdout or "").strip().splitlines()[-8:]
    for line in tail:
        log.info("[%s] %s", tag, line)
    # kindlegen 成功也可能返回 1（仅警告）
    ok = proc.returncode in (0, 1) if "kindlegen" in tag else proc.returncode == 0
    if not ok:
        log.warning("%s 返回码 %s", tag, proc.returncode)
    return ok
