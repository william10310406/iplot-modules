"""模組的授權：上傳一律以 MIT 公開（iplot 主 repo 的 D122）。

模組最上層有 LICENSE、LICENSE.md、LICENSE.txt 的話，每一份都要是 MIT；一份都沒有，機器人補一份 LICENSE。
上傳的東西只讀不執行。
"""

import hashlib
import re

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
TITLE_RE = re.compile(r"(the )?mit license( \(mit\))?", re.IGNORECASE)
OWNER_RA = "william10310406"
RA_HOLDER = "Wei-Heng Chien (簡偉恆)"
REMARK_ADDED = "模組裡沒有 LICENSE：已補上 MIT 的 LICENSE。"


def _words(text: str) -> str:
    return " ".join(text.split())


def _normalized(text: str) -> str:
    """去掉空白行、版權那一行（與開頭的「MIT License」標題）之後，連續空白當一個空格。"""
    kept = [line for line in text.splitlines() if line.strip() and not line.strip().casefold().startswith("copyright")]
    if kept and TITLE_RE.fullmatch(kept[0].strip()):
        kept = kept[1:]
    return _words("\n".join(kept))


MIT_NORMALIZED = _normalized(MIT_BODY)


def is_mit(raw: bytes) -> bool:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return _normalized(text) == MIT_NORMALIZED


def license_files(files: tuple[File, ...]) -> list[File]:
    return [f for f in files if f.path.casefold() in LICENSE_NAMES]


def refused(unpacked: Unpacked) -> bool:
    """最上層有授權檔，而且有一份不是 MIT。"""
    return any(not is_mit((unpacked.folder / f.path).read_bytes()) for f in license_files(unpacked.files))


def license_text(login: str, year: int) -> str:
    holder = RA_HOLDER if login == OWNER_RA else f"@{login}"
    return f"MIT License\n\nCopyright (c) {year} {holder}\n\n{MIT_BODY}"


def add_license(unpacked: Unpacked, login: str, year: int) -> Unpacked:
    """沒有授權檔就在暫存的資料夾寫一份 LICENSE，並把它放進檔案清單（place 與 index 核對都看這份清單）。"""
    raw = license_text(login, year).encode("utf-8")
    (unpacked.folder / "LICENSE").write_bytes(raw)
    added = File("LICENSE", len(raw), hashlib.sha256(raw).hexdigest())
    files = tuple(sorted((*unpacked.files, added), key=lambda f: f.path))
    return Unpacked(unpacked.name, unpacked.folder, files, unpacked.skipped)
