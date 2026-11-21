# -*- coding: utf-8 -*-
"""书籍工作区存储。

books/<书名>/
├── meta.json        书籍元信息
├── toc.json         归一化后的目录（index/title/url）
├── cover.<ext>      封面
├── junk_lines.json  跨章节统计出的广告行（清洗第二阶段产物）
└── chapters/
    └── 0001.json    单章净化结果（models.ChapterData 序列化）

所有写入均为临时文件 + 原子替换，保证中断后可续跑。
"""

import json
import os
import re
import shutil
import tempfile
import threading
from typing import Dict, List, Optional

from .log import get_logger
from .models import BookMeta, ChapterData, TocEntry

log = get_logger(__name__)

_UNSAFE_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_dirname(name: str) -> str:
    name = _UNSAFE_RE.sub("_", (name or "").strip())
    return name[:80] or "MyBook"


def _atomic_write(path: str, write_fn):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            write_fn(fp)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


class BookStore:
    """单个书籍工作区。方法线程安全。"""

    def __init__(self, root: str):
        self.root = root
        self.chapters_dir = os.path.join(root, "chapters")
        os.makedirs(self.chapters_dir, exist_ok=True)
        self._lock = threading.Lock()

    # ---------- 路径 ----------
    @property
    def meta_path(self) -> str:
        return os.path.join(self.root, "meta.json")

    @property
    def toc_path(self) -> str:
        return os.path.join(self.root, "toc.json")

    @property
    def junk_path(self) -> str:
        return os.path.join(self.root, "junk_lines.json")

    @property
    def font_map_path(self) -> str:
        return os.path.join(self.root, "font_map.json")

    def chapter_path(self, index: int) -> str:
        return os.path.join(self.chapters_dir, "{:05d}.json".format(index))

    def cover_path(self) -> Optional[str]:
        for name in os.listdir(self.root) if os.path.isdir(self.root) else []:
            if name.startswith("cover."):
                return os.path.join(self.root, name)
        return None

    def save_cover(self, content: bytes, ext: str = "jpg") -> str:
        old = self.cover_path()
        if old:
            os.remove(old)
        path = os.path.join(self.root, "cover." + ext)
        tmp = path + ".tmp"
        with open(tmp, "wb") as fp:
            fp.write(content)
        os.replace(tmp, path)
        return path

    # ---------- meta / toc ----------
    def save_meta(self, meta: BookMeta):
        with self._lock:
            _atomic_write(self.meta_path, lambda fp: json.dump(meta.to_dict(), fp, ensure_ascii=False, indent=2))

    def load_meta(self) -> Optional[BookMeta]:
        if not os.path.isfile(self.meta_path):
            return None
        with open(self.meta_path, "r", encoding="utf-8") as fp:
            return BookMeta.from_dict(json.load(fp))

    def save_toc(self, toc: List[TocEntry]):
        data = [{"index": i + 1, "href": t.href, "title": t.title} for i, t in enumerate(toc)]
        with self._lock:
            _atomic_write(self.toc_path, lambda fp: json.dump(data, fp, ensure_ascii=False, indent=2))

    def load_toc(self) -> List[dict]:
        if not os.path.isfile(self.toc_path):
            return []
        with open(self.toc_path, "r", encoding="utf-8") as fp:
            return json.load(fp)

    # ---------- 章节 ----------
    def save_chapter(self, ch: ChapterData):
        with self._lock:
            _atomic_write(self.chapter_path(ch.index),
                          lambda fp: json.dump(ch.to_dict(), fp, ensure_ascii=False))

    def load_chapter(self, index: int) -> Optional[ChapterData]:
        path = self.chapter_path(index)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fp:
                return ChapterData.from_dict(json.load(fp))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("章节缓存损坏，忽略: %s (%s)", path, e)
            return None

    def has_valid_chapter(self, index: int) -> bool:
        ch = self.load_chapter(index)
        return ch is not None and ch.status == "ok"

    def delete_chapter(self, index: int) -> None:
        """删除单章缓存（目录结构变更时作废旧索引）。"""
        path = self.chapter_path(index)
        with self._lock:
            try:
                os.remove(path)
            except OSError:
                pass

    def shift_chapters(self, start: int, delta: int) -> None:
        """将 index >= start 的章节缓存文件整体平移 delta（跨源补抓插洞/回滚，
        避免目录新增一章导致其后全部缓存被当作错位作废）。"""
        idxs = []
        try:
            for name in os.listdir(self.chapters_dir):
                if name.endswith(".json"):
                    try:
                        idxs.append(int(name[:-5]))
                    except ValueError:
                        pass
        except OSError:
            return
        if not idxs:
            return
        rng = (range(max(idxs), start - 1, -1) if delta > 0
               else range(start, max(idxs) + 1))
        with self._lock:
            for i in rng:
                src = self.chapter_path(i)
                if os.path.isfile(src):
                    os.replace(src, self.chapter_path(i + delta))

    def iter_chapters(self) -> List[ChapterData]:
        """按目录顺序返回全部已缓存章节（缺失的跳过）。"""
        result = []
        if not os.path.isdir(self.chapters_dir):
            return result
        for name in sorted(os.listdir(self.chapters_dir)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.chapters_dir, name), "r", encoding="utf-8") as fp:
                    result.append(ChapterData.from_dict(json.load(fp)))
            except (json.JSONDecodeError, OSError):
                continue
        return result

    def chapter_count(self) -> int:
        toc = self.load_toc()
        if toc:
            return len(toc)
        return len(self.iter_chapters())

    # ---------- 全局广告行 ----------
    def save_junk_lines(self, lines: List[str]):
        with self._lock:
            _atomic_write(self.junk_path, lambda fp: json.dump(lines, fp, ensure_ascii=False, indent=1))

    def load_junk_lines(self) -> List[str]:
        if not os.path.isfile(self.junk_path):
            return []
        with open(self.junk_path, "r", encoding="utf-8") as fp:
            return json.load(fp)

    # ---------- 字体解密映射 ----------
    def save_font_map(self, mapping: Dict[str, str]):
        with self._lock:
            _atomic_write(self.font_map_path,
                          lambda fp: json.dump(mapping, fp, ensure_ascii=False))

    def load_font_map(self) -> Dict[str, str]:
        if not os.path.isfile(self.font_map_path):
            return {}
        try:
            with open(self.font_map_path, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except (json.JSONDecodeError, OSError):
            return {}

    # ---------- 清理 ----------
    def drop_invalid_chapters(self) -> int:
        """删除 status != ok 的缓存，便于强制重爬。"""
        removed = 0
        for ch in self.iter_chapters():
            if ch.status != "ok":
                os.remove(self.chapter_path(ch.index))
                removed += 1
        return removed

    def size(self) -> int:
        total = 0
        for dirpath, _dirs, files in os.walk(self.root):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
        return total

    def temp_artifacts(self) -> List[str]:
        """中间产物路径（不含 meta.json）：章节缓存/目录/广告行/字体表/封面/残留 tmp。"""
        items = [self.chapters_dir, self.toc_path, self.junk_path, self.font_map_path]
        cover = self.cover_path()
        if cover:
            items.append(cover)
        for scan in (self.root, self.chapters_dir):
            if os.path.isdir(scan):
                for name in os.listdir(scan):
                    if name.endswith(".tmp"):
                        items.append(os.path.join(scan, name))
        return [p for p in dict.fromkeys(items) if os.path.exists(p)]

    def cleanup(self, everything: bool = False) -> int:
        """清理本地临时文件，返回释放字节数。

        everything=False：删中间产物（chapters/、toc、junk_lines、font_map、封面、*.tmp），
        仅保留 meta.json 作为书籍档案；everything=True：删除整个工作区目录。
        """
        freed = self.size()
        if everything:
            shutil.rmtree(self.root, ignore_errors=True)
            return freed
        for path in self.temp_artifacts():
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
            except OSError:
                pass
        return freed - self.size()

    @staticmethod
    def purge(root: str):
        if os.path.isdir(root):
            shutil.rmtree(root)
