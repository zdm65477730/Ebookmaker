# -*- coding: utf-8 -*-
"""原生 EPUB 生成（EPUB3 包 + NCX 兼容目录，Kindle/Calibre 友好）。

对应方案修复/改进：
- mimetype 必须为 zip 首个条目且 STORED 不压缩（旧实现最后写入且 deflate，违反规范）
- 段落文本做 XML 转义（旧实现直接塞文本节点，正文含 & < 时产生非法 XHTML）
- toc.ncx + nav.xhtml 双目录，兼顾旧版 Kindle 与标准阅读器
- 排版由内嵌 epub_style.css 控制：段首 2em 缩进、章前分页
"""

import hashlib
import os
import time
import zipfile
from string import Template
from xml.sax.saxutils import escape as xml_escape
from typing import List, Optional

from ..cleaner import Cleaner
from ..log import get_logger
from ..models import BookMeta, ChapterData
from ..store import BookStore

log = get_logger(__name__)

RES_DIR = os.path.dirname(os.path.abspath(__file__))

XHTML_TMPL = """<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}" lang="{lang}">
<head>
<meta http-equiv="Content-Type" content="application/xhtml+xml; charset=utf-8" />
<title>{title}</title>
<link rel="stylesheet" type="text/css" href="style.css" />
</head>
<body>
{body}
</body>
</html>
"""

CONTAINER_XML = """<?xml version='1.0' encoding='utf-8'?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>
"""

UUID_PREFIX = "Ebookmaker-"


def book_uuid(title: str) -> str:
    """与旧版一致的 UUID 生成，保证同书标识稳定。"""
    return UUID_PREFIX + hashlib.md5(title.encode("utf-8")).hexdigest()[0:7]


def _chapter_xhtml(ch: ChapterData, lang: str) -> str:
    """使用 chapter_template.xhtml 模板渲染章节（string.Template，$title/$content）。"""
    paras = "\n".join('<p class="indent">{}</p>'.format(xml_escape(p)) for p in ch.paragraphs)
    tmpl_path = os.path.join(RES_DIR, "chapter_template.xhtml")
    if os.path.isfile(tmpl_path):
        with open(tmpl_path, "r", encoding="utf-8") as fp:
            tmpl = Template(fp.read())
    else:
        tmpl = Template('<h1 class="chapter-title">$title</h1>\n$content')
    body = tmpl.safe_substitute(title=xml_escape(ch.title), content=paras)
    return XHTML_TMPL.format(lang=lang, title=xml_escape(ch.title), body=body)


def _title_xhtml(meta: BookMeta) -> str:
    """使用 title_template.xhtml 模板渲染扉页（string.Template 语法，$变量）。"""
    tmpl_path = os.path.join(RES_DIR, "title_template.xhtml")
    if os.path.isfile(tmpl_path):
        with open(tmpl_path, "r", encoding="utf-8") as fp:
            tmpl = Template(fp.read())
    else:
        tmpl = Template('<div class="titlepage">\n'
                        '<p class="booktitle">$title</p>\n'
                        '<p class="bookauthor">$author</p>\n'
                        '$description\n'
                        '</div>')
    desc_block = ''
    if meta.description:
        desc_block = '<div class="bookdesc"><p class="bookmeta">{}</p></div>'.format(
            xml_escape(meta.description))
    body = tmpl.safe_substitute(
        title=xml_escape(meta.title),
        author=xml_escape(meta.author),
        description=desc_block,
        publisher=xml_escape(meta.publisher),
        category=xml_escape(meta.category),
        update_time=xml_escape(meta.update_time),
        lang=meta.language,
    )
    return XHTML_TMPL.format(lang=meta.language, title=xml_escape(meta.title), body=body)


def _toc_xhtml(meta: BookMeta, chapters: List[ChapterData]) -> str:
    items = "\n".join(
        '<dt><a href="chapter{:05d}.xhtml">{}</a></dt>'.format(ch.index, xml_escape(ch.title))
        for ch in chapters)
    body = ('<div class="tocpage"><h1 class="toc-title">{}</h1><dl class="toc">\n{}\n</dl></div>'
            .format(xml_escape(meta.title), items))
    return XHTML_TMPL.format(lang=meta.language, title="目录", body=body)


def _nav_xhtml(meta: BookMeta, chapters: List[ChapterData]) -> str:
    items = "\n".join(
        '<li><a href="chapter{:05d}.xhtml">{}</a></li>'.format(ch.index, xml_escape(ch.title))
        for ch in chapters)
    body = ('<h1 id="toc-title">目录</h1>\n<nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops">\n'
            '<ol>\n{}\n</ol>\n</nav>'.format(items))
    return XHTML_TMPL.format(lang=meta.language, title="目录", body=body)


def _ncx(meta: BookMeta, chapters: List[ChapterData]) -> str:
    uid = xml_escape(book_uuid(meta.title))
    points = "\n".join(
        ('<navPoint id="chapter{idx}" playOrder="{idx}">\n'
         '  <navLabel><text>{title}</text></navLabel>\n'
         '  <content src="chapter{idx:05d}.xhtml" />\n'
         '</navPoint>').format(idx=ch.index, title=xml_escape(ch.title))
        for ch in chapters)
    return """<?xml version='1.0' encoding='utf-8'?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{uid}" />
    <meta name="dtb:depth" content="1" />
    <meta name="dtb:totalTimeSize" content="0" />
    <meta name="dtb:copyRight" content="" />
  </head>
  <docTitle><text>{title}</text></docTitle>
  <docAuthor><text>{author}</text></docAuthor>
  <navMap>
{points}
  </navMap>
</ncx>
""".format(uid=uid, title=xml_escape(meta.title), author=xml_escape(meta.author), points=points)


def _opf(meta: BookMeta, chapters: List[ChapterData], cover_file: str, cover_mime: str) -> str:
    """OPF 清单；封面必含（build_epub 已保证封面文件存在）。"""
    uid = xml_escape(book_uuid(meta.title))
    date = xml_escape(meta.update_time.split(" ")[0] if meta.update_time else time.strftime("%Y-%m-%d"))

    manifest_items = [
        '<item id="style" href="style.css" media-type="text/css" />',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml" />',
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />',
        '<item id="cover-image" href="{}" media-type="{}" properties="cover-image" />'.format(cover_file, cover_mime),
        '<item id="titlepage" href="title.xhtml" media-type="application/xhtml+xml" />',
        '<item id="book-toc" href="book-toc.xhtml" media-type="application/xhtml+xml" />',
    ]
    # 封面只声明 cover-image（EPUB3 标准）：Kindle/Calibre 会据此自动生成唯一全屏封面页，
    # 避免自带 cover.xhtml 与 Calibre 生成页叠加成“两张封面”。
    meta_cover = ('\n    <meta name="cover" content="cover-image" />'
                  '\n    <meta property="dcterms:modified">{}</meta>'
                  .format(time.strftime("%Y-%m-%dT%H:%M:%SZ")))

    for ch in chapters:
        manifest_items.append(
            '<item id="chapter{idx}" href="chapter{idx:05d}.xhtml" media-type="application/xhtml+xml" />'
            .format(idx=ch.index))

    spine_items = ['<itemref idref="titlepage" linear="yes" />',
                   '<itemref idref="book-toc" linear="yes" />']
    for ch in chapters:
        spine_items.append('<itemref idref="chapter{idx}" linear="yes" />'.format(idx=ch.index))

    return """<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{uid}</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:date>{date}</dc:date>
    <dc:publisher>{publisher}</dc:publisher>
    <dc:language>{lang}</dc:language>
    <dc:subject>{subject}</dc:subject>
    <dc:description>{desc}</dc:description>
    <dc:rights>{rights}</dc:rights>{meta_cover}
  </metadata>
  <manifest>
    {manifest}
  </manifest>
  <spine toc="ncx">
    {spine}
  </spine>
</package>
""".format(
        uid=uid,
        title=xml_escape(meta.title),
        author=xml_escape(meta.author),
        date=date,
        publisher=xml_escape(meta.publisher),
        lang=xml_escape(meta.language),
        subject=xml_escape(meta.category),
        desc=xml_escape(meta.description),
        rights=xml_escape(meta.rights),
        meta_cover=meta_cover,
        manifest="\n    ".join(manifest_items),
        spine="\n    ".join(spine_items),
    )


def _write(zf: zipfile.ZipFile, name: str, data, compress=True):
    if isinstance(data, str):
        data = data.encode("utf-8")
    zf.writestr(zipfile.ZipInfo(name), data, compress_type=zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED)


def build_epub(store: BookStore, out_path: str, cleaner: Optional[Cleaner] = None) -> str:
    """从书籍工作区生成 EPUB。成品必含：封面页、扉页、目录页、全部章节。

    封面优先使用站点下载的 cover.*，缺失时使用内置默认封面；
    cleaner 提供时对全文做跨章节广告行二次过滤。
    """
    meta = store.load_meta()
    if meta is None:
        raise RuntimeError("工作区缺少 meta.json，请先执行 crawl: {}".format(store.root))
    chapters = store.iter_chapters()
    if not chapters:
        raise RuntimeError("工作区没有已缓存章节，请先执行 crawl")
    # 以目录为准截断：缓存文件多于目录条目时，多出的（孤儿/插洞残留）
    # 不进入成品，避免重复章
    toc_n = len(store.load_toc())
    if toc_n and len(chapters) > toc_n:
        log.info("缓存章节 %d 个多于目录 %d 条，超出部分不纳入成品",
                 len(chapters), toc_n)
        chapters = chapters[:toc_n]
    # 按目录文件名序重编号：跨源补洞的缓存平移会使文件内 index 字段留旧值，
    # 直接用它生成章节文件名会碰撞（Duplicate name 警告的根因）
    for pos, ch in enumerate(chapters, start=1):
        ch.index = pos

    junk = set(store.load_junk_lines())
    if cleaner is not None:
        if junk:
            log.info("应用跨章节广告行过滤（%d 种）...", len(junk))
        # 无论是否有高频广告行，都要跑结构清洗：去重复章名 / 删导航列表 / 删推荐块
        for ch in chapters:
            ch.paragraphs = cleaner.clean_paragraphs(ch.paragraphs, chapter_index=ch.index,
                                                     junk_lines=junk, title=ch.title)
            # 成品形态重算置信度并回写缓存，供 verify 审核报告使用
            ch.confidence = round(cleaner.chapter_confidence(ch.paragraphs, title=ch.title)[0], 3)
            try:
                store.save_chapter(ch)
            except OSError:
                pass
    elif junk:
        for ch in chapters:
            ch.paragraphs = [p for p in ch.paragraphs if re_normalize(p) not in junk]

    # 安全网：清洗后为空的章节（多为源站缺章/锁定），插占位并告警，避免无声空白页
    empty = [ch for ch in chapters if not ch.paragraphs]
    if empty:
        log.warning("%d 章清洗后无正文（源站可能缺章）：%s", len(empty),
                    ", ".join(str(c.index) for c in empty[:12]) + (" …" if len(empty) > 12 else ""))
        for ch in empty:
            ch.paragraphs = ["（本章节在源站暂无正文内容。）"]

    # 封面保障：站点封面缺失时退回内置默认封面
    cover_src = store.cover_path()
    if not cover_src or os.path.getsize(cover_src) == 0:
        cover_src = os.path.join(RES_DIR, "default_cover.jpg")
        if not os.path.isfile(cover_src):
            raise RuntimeError("内置默认封面缺失，无法生成封面页: " + cover_src)
        log.info("未获取到站点封面，使用内置默认封面")
    # 封面归一化：小封面等比放大到 Kindle 可用分辨率，统一 RGB JPEG
    from ..coverutil import normalize_cover
    norm = normalize_cover(cover_src)
    if norm is None:
        raise RuntimeError("封面读取失败: " + cover_src)
    cover_bytes, cover_ext, cover_mime = norm
    cover_file = "cover." + cover_ext

    with zipfile.ZipFile(out_path, "w") as zf:
        # 规范要求：mimetype 必须为首个条目且不压缩
        _write(zf, "mimetype", "application/epub+zip", compress=False)
        _write(zf, "META-INF/container.xml", CONTAINER_XML)
        with open(os.path.join(RES_DIR, "epub_style.css"), "r", encoding="utf-8") as fp:
            _write(zf, "OEBPS/style.css", fp.read())
        _write(zf, "OEBPS/content.opf", _opf(meta, chapters, cover_file, cover_mime))
        _write(zf, "OEBPS/toc.ncx", _ncx(meta, chapters))
        _write(zf, "OEBPS/nav.xhtml", _nav_xhtml(meta, chapters))
        _write(zf, "OEBPS/title.xhtml", _title_xhtml(meta))
        _write(zf, "OEBPS/book-toc.xhtml", _toc_xhtml(meta, chapters))
        _write(zf, "OEBPS/" + cover_file, cover_bytes, compress=False)
        for ch in chapters:
            _write(zf, "OEBPS/chapter{:05d}.xhtml".format(ch.index), _chapter_xhtml(ch, meta.language))

    size_mb = os.path.getsize(out_path) / 1048576.0
    log.info("EPUB 已生成: %s（%d 章，%.1f MB）", out_path, len(chapters), size_mb)
    return out_path


def re_normalize(line: str) -> str:
    import re
    return re.sub(r"\s+", "", line)
