"""上傳的 iplot.py 的檢查：長度、read_meta 的三種錯、Python 3.10 的語法、落單的代理字元、TITLE。

上傳的東西只讀不執行：這裡沒有 import、exec、eval、compile 上傳的檔。3.10 那一道只 ast.parse，
原始碼走 stdin、argv 是清單、帶 -I。
"""

import json
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from iplot_rules import read_meta
from registry import invisible, key, similar_to
from say import Refusal, clip, refuse

MAX_IPLOT = 1024 * 1024
MAX_DESCRIPTION = 500
MAX_ICON = 16
PY310 = "python3.10"
PY310_TIMEOUT = 60
PY310_CODE = """import ast, json, sys
try:
    ast.parse(sys.stdin.buffer.read().decode('utf-8-sig'))
except SyntaxError as e:
    print(json.dumps([e.lineno or 0, e.msg]))
    sys.exit(1)
"""

DESCRIPTION_REMARK = f"說明超過 {MAX_DESCRIPTION} 字，清單上只顯示前 {MAX_DESCRIPTION} 字。"
ICON_REMARK = f"ICON 超過 {MAX_ICON} 個字，清單上只顯示前 {MAX_ICON} 個。"


class TooComplex(Exception):
    """解析不了（太複雜、子程序當掉或逾時）。"""


class Python310Missing(Exception):
    """找不到 python3.10。"""


@dataclass(frozen=True)
class Source:
    title: str | None
    description: str
    icon: str
    remarks: tuple[str, ...]


def find_python310() -> str | None:
    return shutil.which(PY310)


def syntax_310(source: bytes, python: str, run=subprocess.run) -> tuple[int, str] | None:
    """用 3.10 只 ast.parse 一次；沒事回 None，語法錯回（行, 訊息），其他狀況丟 TooComplex。"""
    try:
        done = run([python, "-I", "-c", PY310_CODE], input=source, capture_output=True, timeout=PY310_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise TooComplex from None
    if done.returncode == 0:
        return None
    if done.returncode == 1:
        try:
            found = json.loads(done.stdout)
        except ValueError:
            raise TooComplex from None
        if (isinstance(found, list) and len(found) == 2 and type(found[0]) is int
                and isinstance(found[1], str)):
            return found[0], found[1]
    raise TooComplex


def has_lone_surrogate(text: str) -> bool:
    """有沒有落單的代理字元（類別 Cs）：iplot.py 裡寫 "\\ud800" 這種跳脫，解析出來就是一個，編不成 UTF-8。"""
    return any(unicodedata.category(ch) == "Cs" for ch in text)


def title_refusal(title: str | None, name: str, uploader_id: int, registry: dict) -> Refusal | None:
    if title is None or key(title) == key(name):
        return None
    if invisible(title) or key(title) in registry or similar_to(title, uploader_id, registry):
        return refuse("title_taken", title=title)
    return None


def check_source(folder: Path, name: str, uploader_id: int, registry: dict, python310: str,
                 run=subprocess.run) -> Source | Refusal:
    file = folder / "iplot.py"
    if file.stat().st_size > MAX_IPLOT:
        return refuse("iplot_big")
    try:
        meta = read_meta(file)
    except (MemoryError, RecursionError):
        return refuse("too_complex")
    if meta.error is not None:
        found = re.fullmatch(r"第 (\d+) 行：(.*)", meta.error, re.S)
        if found:
            return refuse("syntax", line=int(found.group(1)), message=found.group(2))
        return refuse("not_utf8")
    try:
        bad = syntax_310(file.read_bytes(), python310, run)
    except TooComplex:
        return refuse("too_complex")
    if bad:
        return refuse("syntax_310", line=bad[0], message=bad[1])
    if any(has_lone_surrogate(text) for text in (meta.title or "", meta.description, meta.icon or "")):
        return refuse("surrogate")
    if refusal := title_refusal(meta.title, name, uploader_id, registry):
        return refusal
    remarks = []
    description, cut = clip(meta.description, MAX_DESCRIPTION)
    if cut:
        remarks.append(DESCRIPTION_REMARK)
    icon, cut = clip(meta.icon or "", MAX_ICON)
    if cut:
        remarks.append(ICON_REMARK)
    return Source(meta.title, description, icon, tuple(remarks))
