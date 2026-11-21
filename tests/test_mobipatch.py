# -*- coding: utf-8 -*-
"""mobipatch: EBOK -> PDOC 等长原地替换的安全性测试。"""

import struct

from ebookmaker.mobipatch import mark_personal_document, _exth_offset


def _build_mobi(exth_type501: bytes) -> bytes:
    """构造最小 PalmDB + MOBI(hlen=232) + EXTH(records) 结构。"""
    # EXTH 记录：type501(payload=exth_type501) + type201(4B)
    recs = b""
    for rtype, payload in ((501, exth_type501), (201, b"\x00\x00\x00\xcb")):
        recs += struct.pack(">II", rtype, 8 + len(payload)) + payload
    exth = b"EXTH" + struct.pack(">II", 12 + len(recs), 2) + recs

    mobi_header = b"MOBI" + struct.pack(">I", 232) + b"\x00" * (232 - 8)
    rec0 = b"\x00" * 16 + mobi_header + exth       # 16B PalmDOC 头 + MOBI 头 + EXTH

    header = bytearray(78)
    struct.pack_into(">H", header, 76, 2)          # numRecords = 2
    rec1 = b"<html>x</html>"
    info = struct.pack(">IB3s", 78 + 16, 0, b"\x00\x00\x00")          # rec0 -> 记录信息表之后
    info += struct.pack(">IB3s", 78 + 16 + len(rec0), 0, b"\x00\x00\x00")  # rec1
    return bytes(header) + info + rec0 + rec1


def test_mark_personal_document_flips_ebok_to_pdoc_same_length(tmp_path):
    data = _build_mobi(b"EBOK")
    f = tmp_path / "b.azw3"
    f.write_bytes(data)
    assert _exth_offset(bytearray(data)) is not None
    assert mark_personal_document(str(f)) is True
    out = f.read_bytes()
    assert len(out) == len(data)                       # 等长，未破坏结构
    assert b"PDOC" in out and b"EBOK" not in out


def test_mark_personal_document_noop_when_not_ebok(tmp_path):
    data = _build_mobi(b"PDOC")
    f = tmp_path / "b.mobi"
    f.write_bytes(data)
    assert mark_personal_document(str(f)) is False     # 已是 PDOC，不改
    assert f.read_bytes() == data


def test_mark_personal_document_skips_bad_structure(tmp_path):
    f = tmp_path / "b.mobi"
    f.write_bytes(b"not a mobi file at all")
    assert mark_personal_document(str(f)) is False     # 结构不符，安全跳过
    assert f.read_bytes() == b"not a mobi file at all"


def test_mark_personal_document_ignores_non_mobi(tmp_path):
    f = tmp_path / "b.epub"
    f.write_bytes(b"PK\x03\x04whatever")
    assert mark_personal_document(str(f)) is False     # 非 mobi/azw3 直接跳过
