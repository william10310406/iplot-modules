"""zip 的檢查與解開：上傳的東西只讀不執行；一條一條讀、每次一小塊，不用 read、不用 extractall。

例外交給 receive：加密 RuntimeError、Deflate64 NotImplementedError、壞的 deflate zlib.error、
CRC 不對 zipfile.BadZipFile。
"""

import hashlib
import re
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

from iplot_rules import RESERVED, SKIP
from say import Refusal, refuse

MAX_ENTRIES = 20000
MAX_FILES = 2000
MAX_UNPACKED = 100 * 1024 * 1024
CHUNK = 64 * 1024
WINDOWS_CHARS = set(':*?"<>|')
GIT_SHORT = re.compile(r"git~[0-9]+", re.IGNORECASE)
SKIP_SHOWN = {".history": ".history/", "__pycache__": "__pycache__/", ".ds_store": ".DS_Store",
              ".origin": ".origin", ".unconfirmed": ".unconfirmed"}


@dataclass(frozen=True)
class File:
    path: str  # 相對於模組資料夾、posix、NFC
    size: int
    sha256: str


@dataclass(frozen=True)
class Unpacked:
    name: str
    folder: Path
    files: tuple[File, ...]
    skipped: dict[str, int]


def skip_group(parts: list[str], info: zipfile.ZipInfo) -> str | None:
    """這一條要略過的話，回它的群組名（給回覆裡數條數）；不略過回 None。parts 已經是 NFC。"""
    folded = [p.casefold() for p in parts]
    if folded[0] == "__macosx":
        return "__MACOSX/"
    if ".venv" in folded:
        return ".venv/"
    if any(p.startswith(".git") for p in folded):
        return ".git*"
    for p in folded:
        if p in SKIP:
            return SKIP_SHOWN[p]
    if parts[-1].startswith("._"):
        return "._*"
    if not info.is_dir() and parts[-1] == "Icon\r":
        return "Icon\\r"
    if stat.S_ISLNK(info.external_attr >> 16):
        return "符號連結"
    return None


def bad_path(rel: str) -> bool:
    if not rel or rel.startswith("/") or "\\" in rel:
        return True
    if any(unicodedata.category(c) == "Cc" or c in WINDOWS_CHARS for c in rel):
        return True
    return any(not seg or seg == ".." or seg.endswith((".", " ")) or seg.split(".")[0].upper() in RESERVED
               or GIT_SHORT.fullmatch(seg) for seg in rel.split("/"))


def _key(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def conflict(entries: list[tuple[str, bool]]) -> str | None:
    """重複、只差大小寫、檔跟資料夾同名：回第一條有問題的路徑；沒有回 None。"""
    seen: dict[str, tuple[str, bool]] = {}
    for path, is_dir in entries:
        path = unicodedata.normalize("NFC", path)
        parts = path.split("/")
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            prefix_is_dir = i < len(parts) or is_dir
            key = _key(prefix)
            if key not in seen:
                seen[key] = (prefix, prefix_is_dir)
                continue
            first, first_is_dir = seen[key]
            if first != prefix or first_is_dir != prefix_is_dir or not prefix_is_dir:
                return path
    return None


def inspect(zip_path: Path, staging: Path) -> Unpacked | Refusal:
    if not zipfile.is_zipfile(zip_path):
        return refuse("not_zip")
    try:
        z = zipfile.ZipFile(zip_path, metadata_encoding="utf-8")
    except UnicodeDecodeError:
        return refuse("names_not_utf8")
    with z:
        infos = z.infolist()
        if len(infos) > MAX_ENTRIES:
            return refuse("too_many_entries")
        skipped: dict[str, int] = {}
        kept: list[tuple[zipfile.ZipInfo, str, bool]] = []  # (info, NFC 路徑, 是不是目錄)
        for info in infos:
            path = unicodedata.normalize("NFC", info.filename)
            is_dir = path.endswith("/")
            if is_dir:
                path = path[:-1]
            group = skip_group(path.split("/"), info)
            if group:
                skipped[group] = skipped.get(group, 0) + 1
            else:
                kept.append((info, path, is_dir))
        for _, path, _ in kept:
            if bad_path(path):
                return refuse("bad_path", path=path)
        tops = {path.split("/")[0] for _, path, _ in kept}
        if len(tops) != 1:
            return refuse("shape")
        name = next(iter(tops))
        top_file = any(not is_dir and "/" not in path for _, path, is_dir in kept)
        if top_file or not any(not is_dir and path == f"{name}/iplot.py" for _, path, is_dir in kept):
            return refuse("shape")
        clash = conflict([(path, is_dir) for _, path, is_dir in kept])
        if clash is not None:
            return refuse("bad_path", path=clash)
        members = [(info, path[len(name) + 1:]) for info, path, is_dir in kept if not is_dir]
        if len(members) > MAX_FILES:
            return refuse("too_many_files")
        if sum(info.file_size for info, _ in members) > MAX_UNPACKED:
            return refuse("too_large")
        folder = staging / name
        files = []
        for info, rel in sorted(members, key=lambda m: m[1]):
            target = folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            digest, size = hashlib.sha256(), 0
            with z.open(info) as src, open(target, "xb") as dst:
                while chunk := src.read(CHUNK):
                    dst.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            if size != info.file_size:
                return refuse("broken", kind="宣告的大小跟內容不一樣")
            files.append(File(rel, size, digest.hexdigest()))
    return Unpacked(name, folder, tuple(files), skipped)
