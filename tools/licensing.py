"""模組的授權：上傳一律以 MIT 公開（iplot 主 repo 的 D122）。

模組最上層只認 LICENSE、LICENSE.md、LICENSE.txt 其中一個（要是檔案）；沒有就補一份 LICENSE；有就要是 MIT：
「Permission is hereby granted」那一行之前只准有空行、標題、SPDX、版權行，那一行起到檔尾要跟 MIT 全文一字不差。
收下的檔裡沒有上傳者的版權行就加一行，原有的版權行一行不動。上傳的東西只讀不執行。
"""

import codecs
import hashlib
import re
import unicodedata

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
LICENSE_NAMES = frozenset({"license", "license.md", "license.txt"})
LOOKALIKE_PREFIXES = ("licence", "copying", "unlicense", "copyright", "license-", "license.")
TITLE_RE = re.compile(r"(the )?mit license( \(mit\))?", re.IGNORECASE)
SPDX_RE = re.compile(r"spdx-license-identifier: mit", re.IGNORECASE)
COPYRIGHT_RE = re.compile(
    r"(copyright\s*)?((\(c\)|©)\s*)?\d{4}([-–,]\s*\d{4})*\s+(?P<holder>\S.{0,99})", re.IGNORECASE)
CURLY = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})
PERMISSION = "Permission is hereby granted"
MAX_LICENSE = 64 * 1024
OWNER_RA_ID = 71483597
RA_HOLDER = "Wei-Heng Chien (簡偉恆)"
REMARK_ADDED = "模組裡沒有 LICENSE：已補上 MIT 的 LICENSE。"
REMARK_LINE_ADDED = "LICENSE 已加上你的版權行；原本的版權行都保留了。"


def _words(text: str) -> str:
    return " ".join(text.split())


def _line(raw: str) -> str:
    """比對用的一行：NFC、彎引號換直引號、去掉開頭的 #、前後空白、連續空白當一個。"""
    text = unicodedata.normalize("NFC", raw).translate(CURLY)
    return _words(text.strip().lstrip("#"))


MIT_NORMALIZED = _words(" ".join(_line(line) for line in MIT_BODY.splitlines()))


def holder(user_id: int, login: str) -> str:
    """版權人：用帳號 id 認研究助理（login 可以改名、可以被別人搶註），其他人是 @帳號。"""
    return RA_HOLDER if user_id == OWNER_RA_ID else f"@{login}"


def review(raw: bytes, who: str, year: int) -> tuple[bytes, bool] | None:
    """是 MIT 就回 (內容, 有沒有加一行)：沒有 who 的版權行就在最後一行版權行之後（沒有就在標題之後）加
    `Copyright (c) <year> <who>`，原有的每一行不動。不是 MIT 回 None。"""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    lines = text.splitlines(keepends=True)
    norm = [_line(line) for line in lines]
    start = next((i for i, line in enumerate(norm) if line.startswith(PERMISSION)), None)
    if start is None:
        return None
    if _words(" ".join(norm[start:])) != MIT_NORMALIZED:
        return None
    title, copyrights, holders = None, [], set()
    for i, line in enumerate(norm[:start]):
        if not line:
            continue
        if TITLE_RE.fullmatch(line):
            title = i if title is None else title
        elif SPDX_RE.fullmatch(line):
            continue
        elif found := COPYRIGHT_RE.fullmatch(line):
            copyrights.append(i)
            holders.add(found["holder"].casefold())
        else:
            return None
    if _words(who).casefold() in holders:
        return raw, False
    eol = "\r\n" if "\r\n" in text else "\n"
    mine = f"Copyright (c) {year} {who}{eol}"
    if copyrights:
        at, add = copyrights[-1] + 1, [mine]
    elif title is not None:
        at = title + 1
        add = [eol, mine] if not norm[at] else [eol, mine, eol]
    else:
        at, add = 0, [mine] if not norm[0] else [mine, eol]
    lines[at:at] = add
    bom = codecs.BOM_UTF8 if raw.startswith(codecs.BOM_UTF8) else b""
    return bom + "".join(lines).encode("utf-8"), True


def is_mit(raw: bytes) -> bool:
    return review(raw, "", 0) is not None


def _top_level(files: tuple[File, ...]) -> tuple[list[str], list[str]]:
    """最上層的名字分成 (可以當授權檔的檔, 不能收的：資料夾叫 LICENSE、或名字像授權檔)。"""
    tops: dict[str, bool] = {}  # 名字 → 是不是資料夾
    for f in files:
        top, _, rest = f.path.partition("/")
        tops[top] = tops.get(top, False) or bool(rest)
    ok, bad = [], []
    for top in sorted(tops):
        low = top.casefold()
        if low in LICENSE_NAMES:
            (bad if tops[top] else ok).append(top)
        elif low.startswith(LOOKALIKE_PREFIXES):
            bad.append(top)
    return ok, bad


def license_text(user_id: int, login: str, year: int) -> str:
    return f"MIT License\n\nCopyright (c) {year} {holder(user_id, login)}\n\n{MIT_BODY}"


def _with(unpacked: Unpacked, path: str, raw: bytes) -> Unpacked:
    """把這個檔寫進暫存的資料夾，並更新檔案清單（place 與 index 核對都看這份清單）。"""
    (unpacked.folder / path).write_bytes(raw)
    record = File(path, len(raw), hashlib.sha256(raw).hexdigest())
    files = tuple(sorted((*(f for f in unpacked.files if f.path != path), record), key=lambda f: f.path))
    return Unpacked(unpacked.name, unpacked.folder, files, unpacked.skipped)


def apply(unpacked: Unpacked, user_id: int, login: str, year: int) -> tuple[Unpacked, tuple[str, ...]] | Refusal:
    """最上層的授權檔：不合規矩就回拒收的那一句（在寫任何檔之前）；沒有就補一份；有就核 MIT，缺上傳者的版權行就加。
    回 (新的 Unpacked, 要放進回覆的話)。"""
    ok, bad = _top_level(unpacked.files)
    if bad:
        return refuse("bad_license", name=bad[0])
    if len(ok) > 1:
        return refuse("bad_license", name=ok[0])
    who = holder(user_id, login)
    if not ok:
        return _with(unpacked, "LICENSE", license_text(user_id, login, year).encode("utf-8")), (REMARK_ADDED,)
    path = ok[0]
    size = next(f.size for f in unpacked.files if f.path == path)
    result = review((unpacked.folder / path).read_bytes(), who, year) if size <= MAX_LICENSE else None
    if result is None:
        return refuse("bad_license", name=path)
    raw, inserted = result
    if not inserted:
        return unpacked, ()
    return _with(unpacked, path, raw), (REMARK_LINE_ADDED,)
