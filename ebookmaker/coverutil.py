# -*- coding: utf-8 -*-
"""封面归一化：把站点抓到的低分辨率小封面放大到 Kindle 可用的尺寸。

Kindle 书库缩略图与封面页对分辨率有隐性下限，~225x300 的小图会导致
“封面不铺满 / 缩略图空白”。这里在打包前把过小的封面等比放大到长边 target_long，
并统一转成 RGB（去掉 alpha/CMYK，Kindle 对非 RGB JPEG 兼容性差）。

Pillow 作为可选依赖：未安装时原样返回，不阻塞出书。
"""

import os

from .log import get_logger

log = get_logger(__name__)

# 长边达到该值即认为足够，不再放大；过小则放大到 target_long
MIN_LONG_EDGE = 1000
TARGET_LONG_EDGE = 1600
JPEG_QUALITY = 90


def normalize_cover(src_path):
    """返回 (bytes, ext, mime)；ext 不含点。放大/标准化失败或 PIL 缺失时回退原始字节。"""
    try:
        with open(src_path, "rb") as fp:
            raw = fp.read()
    except OSError:
        return None
    try:
        import io

        from PIL import Image
    except ImportError:
        log.debug("未安装 Pillow，封面按原始尺寸打包（小封面可能在 Kindle 上显示偏小）")
        return raw, _ext_of(src_path), _mime_of(src_path)

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as e:  # 无法解码：退回原图
        log.debug("封面无法解码，保持原样: %s", e)
        return raw, _ext_of(src_path), _mime_of(src_path)

    w, h = img.size
    long_edge = max(w, h)
    fmt = (img.format or "").upper()

    if long_edge >= MIN_LONG_EDGE and fmt in ("JPEG", "PNG"):
        ext = "jpg" if fmt == "JPEG" else "png"
        return raw, ext, ("image/jpeg" if fmt == "JPEG" else "image/png")

    # 等比放大到长边 target（仅放大，绝不缩小；不做裁剪/加边，最大程度保真）
    scale = float(TARGET_LONG_EDGE) / float(long_edge)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    try:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        resized = img.resize((nw, nh), Image.LANCZOS)
        if resized.mode != "RGB":
            resized = resized.convert("RGB")
        buf = io.BytesIO()
        resized.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        log.info("封面已放大: %dx%d -> %dx%d", w, h, nw, nh)
        return buf.getvalue(), "jpg", "image/jpeg"
    except Exception as e:
        log.debug("封面放大失败，保持原样: %s", e)
        return raw, _ext_of(src_path), _mime_of(src_path)


def _ext_of(path):
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    return "jpg" if ext in ("jpg", "jpeg") else (ext or "jpg")


def _mime_of(path):
    return "image/png" if _ext_of(path) == "png" else "image/jpeg"
