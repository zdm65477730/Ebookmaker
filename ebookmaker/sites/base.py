# -*- coding: utf-8 -*-
"""站点适配器基类与共用解析工具。

接口约定（对应方案）：
- parse_meta(html, url)   -> BookMeta      目录页元信息
- parse_toc(html, url)    -> [TocEntry]    归一化（排序/去重）后的目录
- parse_chapter(html, url)-> [str]         正文容器的原始行（未净化，交给 Cleaner）
"""

import re
from abc import ABC, abstractmethod
from typing import List, Optional, Sequence
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..log import get_logger
from ..models import BookMeta, TocEntry

log = get_logger(__name__)

# 常见正文容器（优先级从高到低）
DEFAULT_CONTENT_SELECTORS = [
    "#content", "#chaptercontent", "#booktxt", "#txt", "div.showtxt",
    "div.chapter-con", "div.content", "article",
]
# 常见目录容器
DEFAULT_TOC_SELECTORS = ["#list dd a", "dl dd a", ".chapterlist a", "#chapterlist a", "div.listmain dd a"]

_TITLE_NUM_RE = re.compile(r"第\s*([0-9０-９]+)\s*[章节回]")


def make_soup(html: str):
    """HTML -> BeautifulSoup(lxml)。"""
    return BeautifulSoup(html, "lxml")


def container_to_lines(node) -> List[str]:
    """正文 DOM 节点 -> 原始行列表。<br>/块级元素转换行，去标签。"""
    if node is None:
        return []
    for tag in node(["script", "style"]):
        tag.decompose()
    for br in node.find_all("br"):
        br.replace_with("\n")
    for p in node.find_all(["p", "div"]):
        p.append("\n")
    text = node.get_text()
    return text.split("\n")


def find_content_node(soup, selectors: Sequence[str] = None):
    for sel in (selectors or DEFAULT_CONTENT_SELECTORS):
        node = soup.select_one(sel)
        if node is not None and len(node.get_text(strip=True)) > 50:
            return node
    return None


# “下一页”分页链接文本（仅接受精确匹配，避免误中“下一章”）
_NEXT_PAGE_TEXT_RE = re.compile(r"^下一[页頁]$|^next page$|^第?\s*\d+\s*页$", re.I)

# onclick 跳转式链接：location.href('/x') 与 location.href='/x' 两种引号形态
_ONCLICK_URL_RE = re.compile(r"location\.\s*href\s*=\s*[('\"]+\s*([^'\")]+)")


def anchor_href(tag) -> str:
    """取锚点目标 URL：优先 href；href 为 javascript: 或缺失时回退 onclick 里的 location.href。"""
    href = (tag.get("href") or "").strip()
    if href and not href.lower().startswith("javascript:"):
        return href
    oc = tag.get("onclick") or ""
    m = _ONCLICK_URL_RE.search(oc)
    if m:
        return m.group(1).strip()
    # href="javascript:..." 内嵌的 location.href='/x'
    if href.lower().startswith("javascript:"):
        m = _ONCLICK_URL_RE.search(href)
        if m:
            return m.group(1).strip()
    return ""

# 章节链接形态：带 .html 后缀，或路径以独立数字段结尾（至少三位，排除 /2/ /13/ 这类栏目/目录分页）
_CHAPTER_HREF_RE = re.compile(r"\.html?($|[?#])|(?:^|/)\d{3,}(?:/|$|[?#])")
# 通用导航词标题（分页/目录/开关类），命中即非章节
_NAV_TITLE_RE = re.compile(
    r"^(?:上一[页頁]|下一[页頁]|首[页頁]|尾[页頁]|末[页頁]|最新[页頁]|目[录錄]|书[页頁]|"
    r"返回(?:书页|目录)?|展开|收起|更多|全部|第?\s*\d+\s*[页頁])$")


def looks_like_chapter(href: str, title: str) -> bool:
    """链接+标题双重判断：非导航词且 href 形如章节文档。"""
    if _NAV_TITLE_RE.match((title or "").strip()):
        return False
    return bool(_CHAPTER_HREF_RE.search(href or ""))


def find_next_page_url(html: str, cur_url: str) -> Optional[str]:
    """自动探测同一章节的分页链接：仅当目标 URL 是当前章节 URL 的“同系列后缀”
    （如 12345.html -> 12345_2.html / 12345-2.html / 12345/2/）才视为分页，
    指向下一篇不同编号文档的“下一页”不会被误拼。"""
    soup = make_soup(html)
    cur = urlparse(cur_url)
    stem = re.sub(r"\.html?$", "", cur.path)
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        if not _NEXT_PAGE_TEXT_RE.match(text):
            continue
        href = anchor_href(a)
        if not href:
            continue
        absu = urljoin(cur_url, href.strip())
        p = urlparse(absu)
        if p.netloc != cur.netloc:
            continue
        sp = re.sub(r"\.html?$", "", p.path)
        if not sp.startswith(stem + "_") and not sp.startswith(stem + "-") \
                and not (sp.startswith(stem + "/") and len(sp) > len(stem) + 1):
            continue
        tail = sp[len(stem):]
        if re.fullmatch(r"[_\-/]?\d+(/.*)?", tail):
            return absu
    return None


def densest_toc_container(soup):
    """找 .html 链接最密集的容器，返回 (container, links) 或 (None, [])。"""
    best, best_cnt = None, 0
    for container in soup.find_all(["dl", "ul", "ol", "div"]):
        links = container.find_all("a", href=re.compile(r"\.html?($|[?#])"))
        if len(links) > best_cnt:
            best, best_cnt = container, len(links)
    if best is None or best_cnt < 5:
        return None, []
    return best, best.find_all("a", href=re.compile(r"\.html?($|[?#])"))


def filter_same_host(entries: List[TocEntry], book_url: str) -> List[TocEntry]:
    """保留与目录页同域且同书路径的章节链接，筛除同站“其他作品”侧栏推荐。

    路径约束采用软过滤：若本批同域条目中大多数均在书籍目录下，才应用该约束；
    否则（章节独立存于其它路径的站点）只过域名，不会误删全书。"""
    host = urlparse(book_url).netloc.lower()
    book_path = urlparse(book_url).path
    book_dir = book_path if book_path.endswith("/") else book_path.rsplit("/", 1)[0] + "/"

    def same(href: str) -> bool:
        if href.startswith("//"):
            href = "https:" + href
        return urlparse(urljoin(book_url, href)).netloc.lower() in (host, "")

    def same_dir(href: str) -> bool:
        if href.startswith("//"):
            href = "https:" + href
        return urlparse(urljoin(book_url, href)).path.startswith(book_dir)

    same_entries = [e for e in entries if same(e.href)]
    if not same_entries:
        return entries   # 全部外域：不过滤
    dir_entries = [e for e in same_entries if same_dir(e.href)]
    # 大多数同域条目都在书目录下：进一步用路径约束去侧栏推荐
    if len(dir_entries) >= len(same_entries) * 0.5:
        return dir_entries
    return same_entries


# 目录分页合并的页数上限（每页通常百来章，够覆盖上万章的长篇）
MAX_TOC_PAGES = 100


def _labeled_targets(soup) -> List[tuple]:
    """(跳转URL, 可见标签) 对；无标签的跳转（JS value）标签为空串。"""
    out = []
    for tag in soup.find_all(["a", "link", "area"]):
        href = tag.get("href")
        if href:
            out.append((href.strip(), tag.get_text(strip=True)))
        m = _ONCLICK_URL_RE.search(tag.get("onclick") or "")
        if m:
            out.append((m.group(1).strip(), tag.get_text(strip=True)))
    for tag in soup.find_all(["option", "input"], value=True):
        label = tag.get_text(strip=True) if tag.name == "option" else ""
        out.append((tag["value"].strip(), label))
    return out


def _page_targets(soup) -> List[str]:
    """页面里所有可能是跳转目标的取值：<a>/<link>/<area> 的 href、onclick 跳转 URL、
    <option>/<input> 的 value。部分站点目录页码是 <select> 或 <a onclick=location.href> 形式，
    只看 <a href> 会漏掉全部分页。"""
    out = []
    for tag in soup.find_all(["a", "link", "area"]):
        href = tag.get("href")
        if href:
            out.append(href.strip())
        m = _ONCLICK_URL_RE.search(tag.get("onclick") or "")
        if m:
            out.append(m.group(1).strip())
    for tag in soup.find_all(["option", "input"], value=True):
        out.append(tag["value"].strip())
    return out


def _page_key(url: str) -> str:
    """分页 URL 归一化键：去尾斜杠与 .html，便于识别同一页的不同写法。"""
    p = urlparse(url)
    path = re.sub(r"/\.?(html)?/?$", "", p.path).rstrip("/")
    return "{}{}".format(p.netloc.lower(), path)


def find_series_pages(html: str, cur_url: str, max_pages: int = MAX_TOC_PAGES) -> List[str]:
    """探测同系列目录分页，返回绝对 URL 列表。支持两种形态：

    1) 后缀式兄弟页：/490651_5/ 对应 _1.._N（基础名_数字 fullmatch 守护）；
    2) 数字目录式：/xiaoshuo/842/842172/ 的 /1/ /2/ …（base 下一段纯数字+尾斜杠，
       必须带尾斜杠才不会误把章节文档 /842172/183863035.html 当分页）。
    """
    soup = make_soup(html)
    cur = urlparse(cur_url)
    stem = re.sub(r"/\.?(html)?/?$", "", cur.path).rstrip("/")
    base = re.sub(r"_\d+$", "", stem)
    # 当前页自身就是数字目录页（/base/N/）：兄弟页必属同系列，直接剥页号求 base
    # （lxml 会去掉属性 URL 的尾斜杠，两种形态都认）
    self_dir = re.search(r"/\d{1,4}/?$", stem) and (cur.path.endswith("/") or stem != cur.path.rstrip("/"))
    if self_dir:
        base = re.sub(r"/\d{1,4}$", "", base)
    pattern = re.compile(re.escape(base) + r"_\d+$")
    dir_pattern = re.compile(re.escape(base) + r"/(\d{1,4})/?$")
    # 首页/正文页上的 /base/N/ 链接只有在“标签是纯数字或翻页词”时才是目录分页，
    # 否则可能是形似 /9/ 的章节文档；“全部章节/目录”类入口无条件作为种子。
    NUM_LABEL_RE = re.compile(r"^\d{1,4}$")
    found = set()
    for href, label in _labeled_targets(soup):
        absu = urljoin(cur_url, href)
        p = urlparse(absu)
        if p.netloc.lower() != cur.netloc.lower():
            continue
        ppath = re.sub(r"/\.?(html)?/?$", "", p.path).rstrip("/")
        if pattern.fullmatch(ppath) and ppath != stem:
            found.add("{}://{}{}".format(p.scheme or cur.scheme, p.netloc, p.path))
            continue
        # 数字目录式：非自指；lxml 剥斜杠后统一补回尾斜杠（目录页形态）
        if not dir_pattern.fullmatch(p.path):
            continue
        if ppath == stem:
            continue
        if self_dir or NUM_LABEL_RE.match(label or "") or re.search(r"全部章节|章节目录", label or ""):
            found.add("{}://{}{}".format(p.scheme or cur.scheme, p.netloc,
                                         p.path if p.path.endswith("/") else p.path + "/"))
    return sorted(found)[:max_pages]


def collect_series_pages(html: str, cur_url: str, get_html, max_pages: int = MAX_TOC_PAGES):
    """逐页展开目录分页，返回 [(页 URL, 页 HTML), ...]（不含当前页），按页码升序。

    真实站点的分页条常常只渲染相邻页（上一页/下一页），单跳探测只能看到下一页，
    会把目录截断在第一二页；这里对每个新页面继续探测兄弟页直到没有新链接。
    get_html(url) 取页 HTML，失败的分支记警告后跳过。
    """
    cur_key = _page_key(cur_url)
    seen = {cur_key}
    if not re.search(r"_\d+$", cur_key):
        # 无后缀 URL 就是首页，站点导航里写成 `基础名_1` 的同一个页不重取
        seen.add(cur_key + "_1")
    queue = find_series_pages(html, cur_url)
    pages = []
    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        key = _page_key(url)
        if key in seen:
            continue
        seen.add(key)
        try:
            page_html = get_html(url)
        except Exception as e:
            log.warning("目录页获取失败，跳过 %s: %s", url, e)
            continue
        pages.append((url, page_html))
        for nxt in find_series_pages(page_html, url):
            if _page_key(nxt) not in seen:
                queue.append(nxt)
    if queue and len(pages) >= max_pages:
        log.warning("目录分页达到 %d 页上限，剩余分页未合并", max_pages)
    pages.sort(key=lambda t: _page_number(t[0]))
    return pages


def _page_number(url: str) -> int:
    m = re.search(r"_(\d+)(?:[/.]|$)", urlparse(url).path)
    if m:
        return int(m.group(1))
    m = re.search(r"/(\d+)/$", urlparse(url).path)   # 数字目录式 /base/12/
    return int(m.group(1)) if m else 0


def parse_og_meta(soup, url: str) -> BookMeta:
    """统一从 og:novel:* meta 标签提取书籍信息，书名/作者做通用噪声净化
    （部分站点的 og 值自带“最新章节”等后缀，而 <h1> 中才是干净书名）。"""
    def og(prop: str) -> str:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return (tag.get("content") or "").strip() if tag else ""

    h1_tag = soup.find("h1")
    h1_text = h1_tag.get_text(strip=True) if h1_tag else ""
    title = clean_book_title(og("og:novel:book_name") or og("og:title"))
    if not title:
        title = clean_book_title(h1_text)
    else:
        # og 值净化后仍与干净的 h1 不同时，信任页面可见主标题
        h1_clean = clean_book_title(h1_text)
        if h1_clean and h1_clean != title and len(h1_clean) < len(title):
            title = h1_clean
    description = re.sub(r"<[^>]+>", "", og("og:description"))
    description = description.replace("&amp;lt;", "<").replace("&lt;", "").strip()
    cover = og("og:image")
    if cover and cover.startswith("/"):
        cover = _scheme_host(url) + cover
    author = clean_author(og("og:novel:author"))
    return BookMeta(
        title=title or "MyBook",
        author=author or "未知",
        category=og("og:novel:category") or "其他",
        description=description,
        update_time=og("og:novel:update_time"),
        cover_url=cover,
        source_url=url,
    )


def _scheme_host(url: str) -> str:
    p = urlparse(url)
    return "{}://{}".format(p.scheme or "https", p.netloc)


# 书名尾部通用营销噪声（小说网页公版词汇，非站点专属规则）
TITLE_NOISE_SUFFIX_RE = re.compile(
    r"(?:最新章节目录|最新章节列表|最新章节|最新章節|全部章节目录|全部章节|所有章节|"
    r"全文TXT下载|TXT下载|txt下载|全文免费阅读|免费全文阅读|全文在线阅读|全文阅读|"
    r"在线阅读|无错无弹窗|无弹窗阅读|无弹窗|免费小说阅读|小说阅读|无弹窗全文阅读)+$")
# 浏览器标题惯例：“书名_站点名”/“书名|站点名”；仅当分隔符后的段具有站点名特征才切割，
# 避免误删含下划线的真实书名
_TITLE_DELIM_RE = re.compile(r"[_|｜]")
SITEISH_RE = re.compile(
    r"(小说|筆趣|笔趣|中文网|笔趣阁|阁|看书|读书|首页|阅读|book|bqg|txt|"
    r"www|\.(?:com|net|org|cc|la|xyz))", re.I)
AUTHOR_PREFIX_RE = re.compile(r"^(?:作者|著者)\s*[:：]")


def clean_book_title(raw: str) -> str:
    """通用书名净化：去“书名_站点名”分段（后段需具站点名特征）+ 循环剥离尾部营销词。"""
    title = (raw or "").strip()
    if not title:
        return title
    m = _TITLE_DELIM_RE.search(title)
    if m:
        head, tail = title[:m.start()].strip(), title[m.end():].strip()
        if head and SITEISH_RE.search(tail):
            title = head
    prev = None
    while prev != title:
        prev = title
        title = TITLE_NOISE_SUFFIX_RE.sub("", title).strip()
    return title or (raw or "").strip()


def clean_author(raw: str) -> str:
    author = (raw or "").strip()
    return AUTHOR_PREFIX_RE.sub("", author)


_FW_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_HREF_NUM_RE = re.compile(r"/(\d{1,9})(?:_\d+)?(?:\.html?|\.htm)?/?:\d*$")


def _title_number(title: str) -> Optional[int]:
    m = _TITLE_NUM_RE.search((title or "").translate(_FW_DIGITS))
    return int(m.group(1)) if m else None


def _href_number(href: str) -> Optional[int]:
    """URL 尾号（去分页后缀）：/490/336.html -> 336；/842/842172/12/ -> 12。"""
    m = _HREF_NUM_RE.search((href or "").rstrip("/"))
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{1,9})(?:_\d+)?\.html?$", href or "", re.I)
    return int(m.group(1)) if m else None


def normalize_toc(entries: List[TocEntry]) -> List[TocEntry]:
    """排序 + 去重，标题序号与 URL 尾号双证据仲裁：

    - 首选“标题序号==URL尾号”的条目（两证据互证，最可信）占位；
    - 其余按标题序号（缺失回退 URL 尾号）顺序占位，同序号先到先得（站点
      “最新章节”模块跨页重复即此路径消除）；
    - 撞车条目若其 URL 尾号尚无人占用，则按尾号补位——源站个别章节
      标题笔误（如 336.html 标题误写“第366章”）时不再掉真章。
    - 若绝大多数条目有序号（≥ 80%），则丢弃无序号条目（通常是其他书侧栏推荐）。
    """
    assigned: dict = {}          # num -> (order, entry)
    deferred: list = []          # (num, order, entry, urlnum)
    unkeyed: list = []
    for i, e in enumerate(entries):
        tnum = _title_number(e.title)
        unum = _href_number(e.href)
        if tnum is not None and tnum == unum:
            if tnum not in assigned:
                assigned[tnum] = (i, e)
        elif tnum is not None:
            deferred.append((tnum, i, e, unum))
        elif unum is not None:
            deferred.append((unum, i, e, unum))
        else:
            unkeyed.append((i, e))
    rescued = 0
    for num, i, e, unum in sorted(deferred, key=lambda t: (t[0], t[1])):
        if num not in assigned:
            assigned[num] = (i, e)
            continue
        ci, ce = assigned[num]
        if ce.href == e.href:
            continue               # href 完全相同 => 同章重复展示（最新章节模块），丢
        if unum is not None and unum not in assigned:
            assigned[unum] = (i, e)   # 标题序号被占：按 URL 尾号补位（源站标题笔误）
            rescued += 1
    if rescued:
        log.info("目录中 %d 个条目标题序号与 URL 尾号不符，已按尾号补位（源站笔误救援）",
                 rescued)
    result = [e for _, e in (v for _, v in sorted(assigned.items()))]
    # 当绝大多数条目都有序号时，无序号条目是噪声（其他书链接等），丢弃
    total = len(assigned) + len(unkeyed)
    if unkeyed and total and len(assigned) / total >= 0.8:
        log.info("目录中 %d 个无序号条目被丢弃（其他链接，占比 %.0f%%）",
                 len(unkeyed), 100.0 * len(unkeyed) / total)
        return result
    for _, e in unkeyed:
        # 无序号条目（前言/尾声等）按原始相对顺序保留；href 与有序号条目
        # 重复的（如“开始阅读”按钮指向第一章）丢弃
        if e.href in {x.href for x in result}:
            continue
        result.append(e)
    if unkeyed:
        log.info("目录中 %d 个条目无法解析序号，已按原顺序保留", len(unkeyed))
    return result


class SiteAdapter(ABC):
    name: str = "base"
    hosts: List[str] = []          # 后缀匹配；空表示仅手动指定或启发式默认适配器
    toc_selectors: Sequence[str] = DEFAULT_TOC_SELECTORS
    content_selectors: Sequence[str] = DEFAULT_CONTENT_SELECTORS

    def has_content_container(self, html: str) -> bool:
        """页面是否含本站正文容器（章节分页归属判据之一）。"""
        try:
            return find_content_node(make_soup(html), self.content_selectors) is not None
        except Exception:
            return False

    def matches(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return any(host == h or host.endswith("." + h) or host.endswith(h) for h in self.hosts)

    @staticmethod
    def chapter_url(book_url: str, href: str) -> str:
        if href.startswith("//"):
            href = "https:" + href
        return urljoin(book_url, href)

    def parse_meta(self, html: str, url: str) -> BookMeta:
        meta = parse_og_meta(make_soup(html), url)
        meta.site = self.name
        return meta

    def parse_toc(self, html: str, url: str) -> List[TocEntry]:
        soup = make_soup(html)
        links = []
        for sel in self.toc_selectors:
            links = soup.select(sel)
            if len(links) >= 5:
                break
        entries = []
        for a in links:
            href = anchor_href(a)
            title = a.get_text(strip=True)
            if not href or not title:
                continue
            if href.startswith("#"):
                continue
            # 过滤分页导航/返回目录/镜像栏目等非章节链接
            if not looks_like_chapter(href, title):
                continue
            entries.append(TocEntry(href=href, title=title))
        if not entries:
            entries = self._fallback_toc(soup)
        return normalize_toc(filter_same_host(entries, url))

    @staticmethod
    def _fallback_toc(soup) -> List[TocEntry]:
        """兜底：找到 .html 链接最密集的容器（参考 espc/novel-downloader 做法）。"""
        _, links = densest_toc_container(soup)
        entries = []
        for a in links:
            href = anchor_href(a)
            title = a.get_text(strip=True)
            if href and title and looks_like_chapter(href, title):
                entries.append(TocEntry(href=href, title=title))
        return entries

    @abstractmethod
    def parse_chapter(self, html: str, url: str) -> List[str]:
        ...


class BiqugeStyleSite(SiteAdapter):
    """笔趣阁系站点：目录 dd>a + 正文 #content，子类只需声明 hosts。"""

    def parse_chapter(self, html: str, url: str) -> List[str]:
        soup = make_soup(html)
        node = find_content_node(soup, self.content_selectors)
        if node is None:
            from .generic import heuristic_content
            node = heuristic_content(soup)
        return container_to_lines(node)
