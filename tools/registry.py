"""名字是誰的：registry.json 的讀寫、看不見的字與太像的名字、版本、每個帳號的上限（設計第 6、7 節）。

registry.json 的鍵一律是 key(name)（NFC＋casefold）；每一筆的形狀：
保留 {"name", "reserved": true}；種子 {"name", "owner_id", "owner"}（沒有 version）；
一般 {"name", "owner_id", "owner", "version", "notes", "issue", "updated"}；手動加的 removed、warning 可以出現在任何一筆。
機器人只寫 owner、version、notes、issue、updated，其他欄一律不動。
"""

import json
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from iplot_rules import bad_name, latest, newer
from say import Refusal, clip, refuse

MAX_NOTES = 1000
MAX_PER_DAY = 10
MAX_NAMES = 20
MAX_MODULES = 800 * 1024 * 1024
VERSION_RE = re.compile(r"[0-9]{1,9}(\.[0-9]{1,9}){0,9}", re.ASCII)
SCRIPTS = ("LATIN", "CYRILLIC", "GREEK")
EXTRA_INVISIBLE = frozenset({0x2800})  # 點字空白：不是空白、類別是 So，Default_Ignorable 也沒有它
AT = "%Y-%m-%dT%H:%M:%SZ"  # received.json 的 at（UTC）

# Unicode 15.0.0（Python 3.12 的 unicodedata 那一版）的 Default_Ignorable_Code_Point，閉區間；
# 對過 https://www.unicode.org/Public/15.0.0/ucd/DerivedCoreProperties.txt（相鄰的區間已合併）。
DEFAULT_IGNORABLE: tuple[tuple[int, int], ...] = (
    (0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160), (0x17B4, 0x17B5),
    (0x180B, 0x180F), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x3164, 0x3164),
    (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF),
)

REMARK_CHANGELOG = "模組裡有 CHANGELOG.md：這一版改了什麼照它寫，表單那一格沒有用到。"
REMARK_NO_CHANGELOG = "模組裡沒有 CHANGELOG.md：版本自動往上加。"
REMARK_CLIPPED = f"這一版改了什麼超過 {MAX_NOTES} 字，只留前 {MAX_NOTES} 字。"


class DuplicateKey(ValueError):
    pass


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for k, v in pairs:
        if k in result:
            raise DuplicateKey(k)
        result[k] = v
    return result


def read_json_strict(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} 最上層不是物件")
    return data


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def key(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def _ignorable(c: str) -> bool:
    cp = ord(c)
    return cp in EXTRA_INVISIBLE or any(lo <= cp <= hi for lo, hi in DEFAULT_IGNORABLE)


def invisible(name: str) -> bool:
    if name != name.strip():
        return True
    for c in name:
        if _ignorable(c) or (c.isspace() and c != " ") or unicodedata.category(c) in ("Co", "Cn"):
            return True
    used = {s for c in name if c.isalpha()
            for s in SCRIPTS if unicodedata.name(c, "").startswith(s)}
    return len(used) >= 2


def looks_like(name: str) -> str:
    folded = unicodedata.normalize("NFKC", name).casefold()
    return "".join(c for c in folded if not c.isspace())


def similar_to(name: str, uploader_id: int, registry: dict) -> str | None:
    own, mine = key(name), looks_like(name)
    for k, entry in registry.items():
        if k == own or entry.get("owner_id") == uploader_id:
            continue
        if looks_like(entry["name"]) == mine:
            return entry["name"]
    return None


def check_name(name: str, uploader_id: int, registry: dict) -> Refusal | None:
    if bad_name(name):
        return refuse("bad_name")
    if invisible(name):
        return refuse("invisible")
    other = similar_to(name, uploader_id, registry)
    if other is not None:
        return refuse("similar", name=name, other=other)
    return None


def owner_refusal(name: str, uploader_id: int, registry: dict) -> Refusal | None:
    entry = registry.get(key(name))
    if entry is None:
        return None
    if entry.get("reserved"):
        return refuse("reserved", name=name)
    if entry.get("removed"):
        return refuse("removed", name=name)
    if entry.get("owner_id") != uploader_id:
        return refuse("taken", name=name, owner=entry.get("owner") or "不明")
    if entry.get("name") != name:
        return refuse("case", first=entry["name"])
    return None


def modules_size(root: Path) -> int:
    total = 0
    for here, _dirs, files in os.walk(root / "modules", followlinks=False):
        for f in files:
            st = os.lstat(os.path.join(here, f))
            if stat.S_ISREG(st.st_mode):
                total += st.st_size
    return total


def _received_at(entry: dict) -> datetime:
    return datetime.strptime(entry["at"], AT).replace(tzinfo=UTC)


def limit_refusal(uploader_id: int, is_new: bool, upload_size: int, registry: dict, received: dict,
                  used: int, now: datetime) -> Refusal | None:
    since = now - timedelta(hours=24)
    recent = sum(1 for e in received.values() if e.get("owner_id") == uploader_id and _received_at(e) > since)
    if recent >= MAX_PER_DAY:
        return refuse("too_many_uploads", n=recent)
    if is_new:
        names = sum(1 for e in registry.values() if e.get("owner_id") == uploader_id)
        if names >= MAX_NAMES:
            return refuse("too_many_names", n=names)
        if used + upload_size > MAX_MODULES:
            return refuse("full")
    return None


@dataclass(frozen=True)
class Version:
    version: str
    notes: str
    remarks: tuple[str, ...]


def bump(version: str) -> str:
    *head, last = version.split(".")
    return ".".join([*head, str(int(last) + 1)])


def version_for(entry: dict | None, paths: set[str], folder: Path, form_notes: str) -> Version | Refusal:
    current = entry.get("version") if entry else None
    if "CHANGELOG.md" in paths:
        try:
            version, notes = latest(folder / "CHANGELOG.md")
        except ValueError as exc:
            return refuse("changelog", reason=str(exc))
        if version is None or not VERSION_RE.fullmatch(version):
            return refuse("bad_version", version=version or "")
        if current is not None and not newer(current, version):
            return refuse("not_newer", v=version, cur=current)
        remarks = [REMARK_CHANGELOG]
    else:
        try:
            version = "0.0.1" if current is None else bump(current)
        except ValueError:
            return refuse("bad_version", version=str(current))
        if not VERSION_RE.fullmatch(version):
            return refuse("bad_version", version=version)
        notes = form_notes
        remarks = [REMARK_NO_CHANGELOG]
    notes, clipped = clip(notes, MAX_NOTES)
    if clipped:
        remarks.append(REMARK_CLIPPED)
    return Version(version, notes, tuple(remarks))


def record(registry: dict, name: str, uploader_id: int, login: str, version: str, notes: str, issue: int,
           today: str) -> None:
    entry = registry.setdefault(key(name), {"name": name, "owner_id": uploader_id})
    entry["owner"] = login
    entry["version"] = version
    entry["notes"] = notes
    entry["issue"] = issue
    entry["updated"] = today
