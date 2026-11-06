"""模組的授權：上傳一律以 MIT 公開（iplot 主 repo 的 D122）。機器人不解讀任何上傳者寫的授權文字。

版權人記在 registry.json 每一筆的 copyright（[[年份, 顯示名, 帳號 id], ...]，只增不刪），認人只認帳號 id：
帳號名可以改、可以被別人重新註冊，顯示名只是印在 LICENSE 上的字。LICENSE 由機器人照固定格式產生，
上傳的 zip 裡的 LICENSE 一律不寫進 repo。原作者從三個地方併進來（依先後、用 id 去重）：
zip 裡的 LICENSE（sha256 在 licenses.json 裡，＝機器人產生過的那一份）、zip 裡工作坊寫的 .origin（記的網址指到工作坊
的哪個模組）、表單的 fork_of 那一格（填的名字）。
最上層名字是標準授權檔名（copying、licence、copyright、unlicense、license-*、license.<其他>…）的一律不收；
其他檔名不管，也不讀任何檔的內容。上傳的東西只讀不執行。
"""

import hashlib
import json
import re
import unicodedata
from urllib.parse import unquote, urlsplit

from say import Refusal, refuse
from zipcheck import File, Unpacked

MIT_BODY = """Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
LICENSE_NAMES = frozenset({"license", "license.md", "license.txt"})  # 機器人換掉的三個名字
STANDARD_BASES = ("license", "copying", "licence", "copyright", "unlicense")
OWNER_RA_ID = 71483597
RA_HOLDER = "Wei-Heng Chien (簡偉恆)"
HOLDER_RE = re.compile(r"@[A-Za-z0-9-]{1,39} \(GitHub user ([0-9]+)\)", re.ASCII)
WORKSHOP_URL = "https://william10310406.github.io/iplot-modules/"  # 跟 build.BASE_URL 一樣（有測試對）
ORIGIN_DIR = "模組"
MAX_ORIGIN = 64 * 1024

Copyright = list[list]  # [[年份, 顯示名, 帳號 id], ...]：先加入的在前


class BadCopyright(Exception):
    """版權人清單不合格（多半是有人手動改壞了 registry.json）。不繼承 ValueError：receive 的「zip 壞了」不接它，
    會變成「卡住」，研究助理看得到。"""


def holder(user_id: int, login: str) -> str:
    """顯示名：研究助理用 RA_HOLDER，其他人是第一次加入時的 @帳號 加上帳號 id。"""
    return RA_HOLDER if user_id == OWNER_RA_ID else f"@{login} (GitHub user {user_id})"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate(copyright: Copyright) -> None:
    """每一筆：[年份, 顯示名, 帳號 id]；帳號 id 是正整數，年份是 1000–9999，顯示名是 RA_HOLDER 或
    「@帳號 (GitHub user 數字)」而且數字等於帳號 id。不合格丟 BadCopyright。"""
    if not isinstance(copyright, (list, tuple)):
        raise BadCopyright(f"版權人清單不是清單：{copyright!r}")
    for item in copyright:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise BadCopyright(f"版權人不是 [年份, 顯示名, 帳號 id]：{item!r}")
        year, who, owner_id = item
        if not _is_int(owner_id) or owner_id <= 0:
            raise BadCopyright(f"帳號 id 不是正整數：{item!r}")
        if not _is_int(year) or not 1000 <= year <= 9999:
            raise BadCopyright(f"年份不合格：{item!r}")
        if not isinstance(who, str):
            raise BadCopyright(f"顯示名不是字：{item!r}")
        if who != RA_HOLDER:
            m = HOLDER_RE.fullmatch(who)
            if m is None or int(m.group(1)) != owner_id:
                raise BadCopyright(f"顯示名不合格：{item!r}")


def lines_of(copyright: Copyright) -> list[str]:
    validate(copyright)
    return [f"Copyright (c) {year} {who}" for year, who, _ in copyright]


def render(copyright: Copyright) -> str:
    """LICENSE 的全文：同樣的清單，位元組一模一樣。清單不合格丟 BadCopyright（這次不寫入）。"""
    return f"MIT License\n\n{chr(10).join(lines_of(copyright))}\n\n{MIT_BODY}"


def digest(copyright: Copyright) -> str:
    return hashlib.sha256(render(copyright).encode("utf-8")).hexdigest()


def merge(base: Copyright, *more: Copyright) -> Copyright:
    """base 後面依序接 more 裡 id 還不在的人：只增不刪、先後不動、同一個 id 只出現一次、已經在的顯示名不改。"""
    validate(base)
    merged = [list(item) for item in base]
    seen = {item[2] for item in merged}
    for extra in more:
        validate(extra)
        for year, who, owner_id in extra:
            if owner_id not in seen:
                seen.add(owner_id)
                merged.append([year, who, owner_id])
    return merged


def _folded(name: str) -> str:
    return unicodedata.normalize("NFKC", name).casefold()


def is_license_file(path: str) -> bool:
    """最上層、名字（ASCII，不分大小寫）剛好是 LICENSE、LICENSE.md、LICENSE.txt 其中之一：機器人換掉的那一個。"""
    return "/" not in path and path.isascii() and path.lower() in LICENSE_NAMES


def _standard(name: str) -> bool:
    folded = _folded(name)
    return any(folded == base or folded.startswith((base + ".", base + "-")) for base in STANDARD_BASES)


def standard_license_name(paths: list[str]) -> str | None:
    """最上層（檔或資料夾，只看第一段）的名字是標準授權檔名、又不是機器人換掉的那一個 LICENSE 的，回那個名字；
    最上層有兩個以上機器人換掉的 LICENSE，回第二個；沒有回 None。其他層、其他名字、檔的內容一概不看。"""
    tops = sorted({p.split("/")[0] for p in paths})
    for top in tops:
        if _standard(top) and not (top in paths and is_license_file(top)):
            return top
    mine = [t for t in tops if t in paths and is_license_file(t)]
    return mine[1] if len(mine) > 1 else None


def origin_url(raw: bytes | None) -> str | None:
    """.origin 記的網址。工作坊寫的是一行一個「key: value」（url: …）；JSON 物件的 "url" 也認。讀不懂回 None。"""
    if raw is None or len(raw) > MAX_ORIGIN:
        return None
    try:
        text = raw.decode("utf-8").lstrip("﻿")
    except UnicodeDecodeError:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        url = data.get("url")
        return url if isinstance(url, str) else None
    for line in text.splitlines():
        field, sep, value = line.partition(": ")
        if sep and field == "url":
            return value.strip()
    return None


def origin_name(url: str | None) -> str | None:
    """網址是工作坊網站的「模組/<名稱>.zip」才回 <名稱>；其他網址、帶 query 或 fragment 的都回 None。"""
    if not url:
        return None
    try:
        parts = urlsplit(url)
        path = unquote(parts.path, errors="strict")
    except (ValueError, UnicodeDecodeError):
        return None
    site = urlsplit(WORKSHOP_URL)
    prefix = f"{site.path}{ORIGIN_DIR}/"
    if (parts.scheme, parts.netloc) != (site.scheme, site.netloc) or parts.query or parts.fragment:
        return None
    if not path.startswith(prefix) or not path.endswith(".zip"):
        return None
    name = path[len(prefix):-len(".zip")]
    return name if name and "/" not in name else None


def copyright_of_module(name: str, registry_data: dict) -> Copyright | None:
    """registry 裡這個名字（NFC＋casefold）的那一筆的版權人；沒有這個模組（或是保留的名字）回 None，
    有模組但沒有版權人（舊的、沒授權的）回 []。"""
    key = unicodedata.normalize("NFC", name).casefold()
    entry = registry_data.get(key)
    if not isinstance(entry, dict) or entry.get("reserved"):
        return None
    cp = entry.get("copyright")
    return cp if isinstance(cp, list) else []


def origin_copyright(raw: bytes | None, registry_data: dict) -> Copyright:
    """zip 裡的 .origin 指到工作坊的哪個模組，就回那個模組的版權人；讀不懂、不在工作坊、名稱找不到都回 []。"""
    name = origin_name(origin_url(raw))
    found = None if name is None else copyright_of_module(name, registry_data)
    return found or []


def _install(unpacked: Unpacked, dropped: list[str], raw: bytes) -> Unpacked:
    """把 LICENSE 寫進暫存的資料夾，上傳的 LICENSE 類的檔拿掉，並更新檔案清單（place 與 index 核對都看這份清單）。"""
    for path in dropped:
        (unpacked.folder / path).unlink()
    (unpacked.folder / "LICENSE").write_bytes(raw)
    record = File("LICENSE", len(raw), hashlib.sha256(raw).hexdigest())
    files = tuple(sorted((*(f for f in unpacked.files if f.path not in (*dropped, "LICENSE")), record),
                         key=lambda f: f.path))
    return Unpacked(unpacked.name, unpacked.folder, files, unpacked.skipped, unpacked.origin)


def apply(unpacked: Unpacked, user_id: int, login: str, year: int, current: Copyright, licenses: dict,
          registry_data: dict, fork_of: str = "") -> tuple[Unpacked, Copyright] | Refusal:
    """回 (換上機器人產生的 LICENSE 的 Unpacked, 新的版權人清單)，或拒收的那一句（在寫任何檔之前）。
    清單 ＝ registry 原本的 current → zip 的 LICENSE → .origin → fork_of → 上傳者，依先後、用帳號 id 去重。"""
    paths = [f.path for f in unpacked.files]
    if bad := standard_license_name(paths):
        return refuse("license_like", path=bad)
    forked: Copyright = []
    if fork_of:
        found = copyright_of_module(fork_of, registry_data)
        if found is None:
            return refuse("fork_unknown", name=fork_of)
        forked = found
    given = [p for p in paths if is_license_file(p)]
    theirs: Copyright = []
    if given:
        known = licenses.get(next(f.sha256 for f in unpacked.files if f.path == given[0]))
        if known is None:
            return refuse("license_unknown")
        theirs = known
    mine = [[year, holder(user_id, login), user_id]]
    copyright = merge(current, theirs, origin_copyright(unpacked.origin, registry_data), forked, mine)
    return _install(unpacked, given, render(copyright).encode("utf-8")), copyright
