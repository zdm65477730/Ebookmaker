# -*- coding: utf-8 -*-
"""MOBI/AZW3 EXTH 修补：把书籍类型从 EBOK 改为 PDOC（个人文档）。

背景（书伴/Calibre 官方 FAQ 一致确认）：Calibre 生成的 MOBI/AZW3 在 EXTH 记录 501
被标记为 "EBOK"（与亚马逊商店书同类）。Kindle 一旦联网，会用 EXTH 113/504 的 ASIN
去亚马逊服务器抓取封面；Calibre 填的是随机 UUID，匹配失败后 Kindle 就把本地正确封面
覆盖成“暂无图片”占位符——于是“书内封面正常、书架小图标空白，且重启无效”。

对策：将 EXTH 501 的值 EBOK → PDOC。标记为个人文档后，Kindle 直接从文件读取内嵌
封面、不再联网比对 ASIN，封面/缩略图得以保留。EBOK 与 PDOC 均为 4 字节，原地等长
替换，不改动任何偏移/计数，安全无副作用。

只处理确实含 EXTH 且 501=EBOK 的文件；结构不符预期则原样返回、绝不改动，避免损坏。
"""

import struct

from .log import get_logger

log = get_logger(__name__)

_KF8_SUFFIXES = (".mobi", ".azw3", ".azw")


def mark_personal_document(path: str) -> bool:
    """把 MOBI/AZW3 的 EXTH 501 由 EBOK 原地改为 PDOC。返回是否发生修改。"""
    if not path.lower().endswith(_KF8_SUFFIXES):
        return False
    try:
        with open(path, "rb") as fp:
            d = bytearray(fp.read())
    except OSError:
        return False

    ei = _exth_offset(d)
    if ei is None:
        log.debug("未定位到 EXTH，跳过个人文档标记: %s", path)
        return False

    n = struct.unpack(">I", d[ei + 8:ei + 12])[0]
    p = ei + 12
    changed = 0
    for _ in range(n):
        if p + 8 > len(d):
            break
        rtype, rlen = struct.unpack(">II", d[p:p + 8])
        if rlen < 8:
            break
        if rtype == 501 and d[p + 8:p + 12] == b"EBOK":
            d[p + 8:p + 12] = b"PDOC"   # 等长 4 字节，无需改任何长度/偏移
            changed += 1
        p += rlen
    if not changed:
        return False
    try:
        with open(path, "wb") as fp:
            fp.write(d)
    except OSError:
        return False
    log.info("已标记为个人文档(PDOC)，Kindle 将直接读取内嵌封面、不再联网覆盖: %s", path)
    return True


def _exth_offset(d) -> int:
    """返回 EXTH 头起始偏移；结构不符返回 None。record0 内 MOBI 头之后紧跟 EXTH。"""
    if len(d) < 86:
        return None
    r0 = struct.unpack(">I", d[78:82])[0]
    mi = r0 + 16
    if d[mi:mi + 4] != b"MOBI":
        return None
    hlen = struct.unpack(">I", d[mi + 4:mi + 8])[0]
    ei = mi + hlen
    return ei if d[ei:ei + 4] == b"EXTH" else None
