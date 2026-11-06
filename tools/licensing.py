"""模組的授權：上傳一律以 MIT 公開（iplot 主 repo 的 D122）。機器人不解讀任何上傳者寫的授權文字。

版權人記在 registry.json 每一筆的 copyright（[[年份, 版權人], ...]，只增不刪），LICENSE 由機器人照固定格式產生，
上傳的 zip 裡的 LICENSE 一律不寫進 repo。zip 裡有 LICENSE 的話，只有它的 sha256 在 licenses.json 裡
（＝機器人產生過的那一份）才收，這時把那一份的版權人併進來（改別人的模組再上傳）；不是就不收。
zip 裡其他像授權的檔（名字含 licen、copying、gpl、notice、eula）一律不收。上傳的東西只讀不執行。
"""

import hashlib
import unicodedata

from say import Refusal, code, refuse
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
LICENSE_NAMES = frozenset({"license", "license.md", "license.txt"})
LOOKALIKE_WORDS = ("licen", "copying", "gpl", "notice", "eula", "unlicense")
OWNER_RA_ID = 71483597
RA_HOLDER = "Wei-Heng Chien (簡偉恆)"
REMARK_ADDED = "模組裡沒有 LICENSE：已補上 MIT 的 LICENSE。"
REMARK_KEPT = "LICENSE 跟「{name}」的一樣，原作者的版權行已保留。"
REMARK_KEPT_UNNAMED = "LICENSE 是工作坊產生的，原作者的版權行已保留。"

Copyright = list[list]  # [[年份, 版權人], ...]：先加入的在前


def holder(user_id: int, login: str) -> str:
    """版權人：用帳號 id 認研究助理（login 可以改名、可以被別人搶註），其他人是 @帳號。"""
    return RA_HOLDER if user_id == OWNER_RA_ID else f"@{login}"


def render(copyright: Copyright) -> str:
    """LICENSE 的全文：同樣的清單，位元組一模一樣。"""
    lines = "\n".join(f"Copyright (c) {year} {who}" for year, who in copyright)
    return f"MIT License\n\n{lines}\n\n{MIT_BODY}"


def digest(copyright: Copyright) -> str:
    return hashlib.sha256(render(copyright).encode("utf-8")).hexdigest()


def merge(base: Copyright, extra: Copyright) -> Copyright:
    """base 後面接 extra 裡還不在的版權人（不分大小寫）：只增不刪、先後不動、同一個版權人不重複。"""
    merged = [[year, who] for year, who in base]
    seen = {who.casefold() for _, who in merged}
    for year, who in extra:
        if who.casefold() not in seen:
            seen.add(who.casefold())
            merged.append([year, who])
    return merged


def _folded(segment: str) -> str:
    return unicodedata.normalize("NFKC", segment).casefold()


def is_license_file(path: str) -> bool:
    """最上層、名字（ASCII，不分大小寫）剛好是 LICENSE、LICENSE.md、LICENSE.txt 其中之一。"""
    return "/" not in path and path.isascii() and path.lower() in LICENSE_NAMES


def lookalike(paths: list[str]) -> str | None:
    """像授權的檔：最上層那一個 LICENSE 以外，任何一段（檔名或資料夾名）NFKC＋casefold 之後含關鍵字的路徑，
    回走到那一段為止的路徑；沒有回 None。最上層有兩個以上 LICENSE 類的檔，回第二個。"""
    for path in sorted(paths):
        if is_license_file(path):
            continue
        parts = path.split("/")
        for i, part in enumerate(parts):
            if any(word in _folded(part) for word in LOOKALIKE_WORDS):
                return "/".join(parts[:i + 1])
    top = sorted(p for p in paths if is_license_file(p))
    return top[1] if len(top) > 1 else None


def earliest_user(sha: str, registry_data: dict) -> str | None:
    """registry 裡最早（registry.json 的先後）用這份 LICENSE 的模組名；現在沒有人用就回 None。"""
    for entry in registry_data.values():
        cp = entry.get("copyright")
        if cp and digest(cp) == sha:
            return entry["name"]
    return None


def _install(unpacked: Unpacked, dropped: list[str], raw: bytes) -> Unpacked:
    """把 LICENSE 寫進暫存的資料夾，上傳的 LICENSE 類的檔拿掉，並更新檔案清單（place 與 index 核對都看這份清單）。"""
    for path in dropped:
        (unpacked.folder / path).unlink()
    (unpacked.folder / "LICENSE").write_bytes(raw)
    record = File("LICENSE", len(raw), hashlib.sha256(raw).hexdigest())
    files = tuple(sorted((*(f for f in unpacked.files if f.path not in (*dropped, "LICENSE")), record),
                         key=lambda f: f.path))
    return Unpacked(unpacked.name, unpacked.folder, files, unpacked.skipped)


def apply(unpacked: Unpacked, user_id: int, login: str, year: int, current: Copyright, licenses: dict,
          registry_data: dict) -> tuple[Unpacked, tuple[str, ...], Copyright] | Refusal:
    """回 (換上機器人產生的 LICENSE 的 Unpacked, 要放進回覆的話, 新的版權人清單)，或拒收的那一句（在寫任何檔之前）。
    清單 = registry 原本的 current ＋（zip 的 LICENSE 是機器人產生過的那一份時）它的版權人 ＋ 上傳者。"""
    paths = [f.path for f in unpacked.files]
    if bad := lookalike(paths):
        return refuse("license_like", path=bad)
    mine = [[year, holder(user_id, login)]]
    given = [p for p in paths if is_license_file(p)]
    if not given:
        copyright = merge(current, mine)
        remarks = (REMARK_ADDED,)
    else:
        sha = next(f.sha256 for f in unpacked.files if f.path == given[0])
        theirs = licenses.get(sha)
        if theirs is None:
            return refuse("license_unknown")
        copyright = merge(merge(current, theirs), mine)
        name = earliest_user(sha, registry_data)
        remarks = (REMARK_KEPT.format(name=code(name)) if name else REMARK_KEPT_UNNAMED,)
    return _install(unpacked, given, render(copyright).encode("utf-8")), remarks, copyright
