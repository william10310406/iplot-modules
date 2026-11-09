"""沒動的檔：pages.py、photos.py 要跟複製來源（行事曆 0.1.1）逐位元組相同（docs/01_設計.md 第 3.1 節）。

兩邊會重建同一批日記網頁，內容一樣才不打架；「pages 不含 LINE」也靠它沒被改過。"""

import ast
import hashlib
import json

import pytest
import support

COPIED = {
    "pages.py": "34fc6855176388317d7ebcf4388f661af74fe31971583ef737ed850030f4431e",
    "photos.py": "58d24b4f4686800cb3646906e005c71580c137a6d37393d565fcef23d442db54",
}


def test_pages_and_photos_are_byte_identical_to_the_copy():
    for name, expected in COPIED.items():
        assert hashlib.sha256((support.MODULE / name).read_bytes()).hexdigest() == expected, name


ORIGINAL = json.loads((support.MODULE / "tests" / "original_functions.json").read_text(encoding="utf-8"))
# 這一版改過的函式（其餘每個函式的原始碼要跟行事曆 0.1.1 一字不差；tests/original_functions.json 是複製當天量的）
CHANGED = {
    "diary.py": {"save_root", "snapshot", "save_day"},
    "iplot.py": {"running_pid", "open_or_focus", "Api.__init__", "Api.month", "Api.year", "Api.day"},
}


def _functions(name: str) -> dict[str, str]:
    source = (support.MODULE / name).read_text(encoding="utf-8")
    found = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef):
                    found[f"{node.name}.{sub.name}"] = ast.get_source_segment(source, sub)
        elif isinstance(node, ast.FunctionDef):
            found[node.name] = ast.get_source_segment(source, node)
    return found


@pytest.mark.parametrize("name", ["diary.py", "iplot.py"])
def test_changes_are_only_the_listed_functions(name):
    now = {fn: hashlib.sha256(text.encode()).hexdigest() for fn, text in _functions(name).items()}
    for fn, digest in ORIGINAL[name].items():
        assert fn in now, f"{fn} 被拿掉了"
        if fn not in CHANGED[name]:
            assert now[fn] == digest, f"{fn} 被改了，但不在 CHANGED 清單上"
    assert CHANGED[name] <= set(ORIGINAL[name])


def test_changed_functions_really_changed():
    """清單不能放著沒改的函式（不然這份清單就變成假的說明）。"""
    for name, listed in CHANGED.items():
        now = {fn: hashlib.sha256(text.encode()).hexdigest() for fn, text in _functions(name).items()}
        for fn in listed:
            assert now[fn] != ORIGINAL[name][fn], f"{name} 的 {fn} 其實沒改"
