"""iPLoT 與 iplot-modules 共用的對照表：名稱合不合規則、哪個版本比較新、略過哪些名字、名稱不合規則的那一句。

兩邊的 tests/test_rules_table.py 各貼一次，從「對照表開始」那一行到「對照表結束」那一行一字不差；
改的時候兩邊一起改（docs/07 第 11 節）。這一份測 iplot-modules 的 tools/iplot_rules.py。
"""

from pathlib import Path

import iplot_rules
import pytest
from conftest import IPLOT

# ---- 對照表開始：iPLoT 與 iplot-modules 兩邊一字不差（docs/07 第 11 節）----
# (名稱, bad_name 的答案)：True ＝ 不合規則（核心的 ＋ 不收）。看不見的字、相容字、西里爾字母一律寫成 \u 跳脫
BAD_NAMES = [
    ("整理桌面", False),
    ("整理 桌面", False),
    ("開Terminal", False),
    ("中 間", False),
    (" 開頭空白", False),
    ("a.b", False),
    ("a..b", False),
    ("a`b", False),
    ("C#工具", False),
    ("a%20b", False),
    ("@someone", False),
    ("#1", False),
    ("notice", False),
    ("COM0", False),
    ("COM10", False),
    ("LPT10", False),
    ("CONSOLE", False),
    ("CONTEXT", False),
    ("CON-1", False),
    ("nul2", False),
    ("git~1", False),
    ("a\x7fb", False),  # DEL 不算：核心只擋 < 32 的控制字元
    ("開工\u200b", False),  # 零寬空格：核心收，機器人另外擋
    ("開Ｔｅｒｍｉｎａｌ", False),  # 全形英文：核心收
    ("更新\u3000", False),  # 結尾全形空白：rstrip(". ") 只拿掉 ASCII 的點與空白
    ("更\u00a0新", False),  # 中間 NBSP
    ("開\u0422erminal", False),  # 西里爾字母 \u0422
    ("\uf901新", False),  # 相容表意字「更」
    ("", True),
    (" ", True),
    ("\u3000", True),  # 只有全形空白：strip() 拿得掉
    (".藏起來", True),
    (".git", True),
    ("..", True),
    ("結尾點.", True),
    ("結尾空白 ", True),
    ("a/b", True),
    ("a\\b", True),
    ("a:b", True),
    ("a*b", True),
    ("a?b", True),
    ('a"b', True),
    ("a<b", True),
    ("a>b", True),
    ("a|b", True),
    ("a\tb", True),
    ("a\nb", True),
    ("a\x1fb", True),
    ("Icon\r", True),
    ("CON", True),
    ("con", True),
    ("Con.txt", True),
    ("nul.tar.gz", True),
    ("PRN", True),
    ("AUX", True),
    ("COM1", True),
    ("com9", True),
    ("LPT1", True),
    ("LPT9", True),
]
# (現在的版本, 清單上的版本, newer 的答案)
NEWER = [
    ("0.5.1", "0.5.2", True),
    ("0.5.2", "0.5.1", False),
    ("0.5.2", "0.5.2", False),
    ("0.9.9", "0.10.0", True),
    ("0.10.0", "0.9.9", False),
    ("0.5", "0.5.1", True),
    ("1.0", "1.0.0", True),  # 段數多的算新
    ("1.0.0", "1.0", False),
    ("1.1", "1.01", False),  # 一樣大
    ("1.01", "1.1", False),
    ("2", "10", True),
    ("1.2.3.4.5", "1.2.3.4.6", True),
    ("1.0.0", "v1.1.0", False),  # 看不懂一律 False
    ("abc", "1.0", False),
    ("0.5.0", "x", False),
    ("0.5.0", None, False),
    ("1.0", "", False),
    ("", "1.0", False),
    ("1.0", "1..1", False),
    ("1.0.0-beta", "1.0.1", False),
    ("1.0.0", "1.0.1-beta", False),
    ("0.0.1", "\uff10.\uff10.\uff12", True),  # int() 收全形數字
    ("9.0", "1_0.0", True),  # int() 收底線
    ("1.0", "1.1 ", True),  # int() 拿掉頭尾空白
    ("0.0.1", "9" * 5000, False),  # 3.10.7 起 int() 超過 4300 位丟 ValueError
]
SKIP_NAMES = {".history", ".origin", ".unconfirmed", "__pycache__", ".ds_store"}
BAD_NAME_TEXT = ("名稱不能是空白、以 . 開頭、結尾是 . 或空白、含 / \\ : * ? \" < > |，"
                 "也不能是 CON、NUL 這類 Windows 保留字（模組要能複製到任何系統）")
# ---- 對照表結束 ----


def _table_lines(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("# ---- 對照表開始"))
    end = next(i for i, line in enumerate(lines) if line.startswith("# ---- 對照表結束"))
    return lines[start:end + 1]


@pytest.mark.parametrize("name, bad", BAD_NAMES)
def test_bad_name_matches_the_table(name, bad):
    assert iplot_rules.bad_name(name) == bad


@pytest.mark.parametrize("current, latest, newer", NEWER)
def test_newer_matches_the_table(current, latest, newer):
    assert iplot_rules.newer(current, latest) == newer


def test_skip_matches_the_table():
    assert iplot_rules.SKIP == SKIP_NAMES


def test_bad_name_text_matches_the_table():
    assert iplot_rules.BAD_NAME_TEXT == BAD_NAME_TEXT


def test_table_is_word_for_word_the_same_in_iplot(iplot_next_door):
    theirs = IPLOT / "tests" / "test_rules_table.py"
    if not theirs.is_file():
        pytest.skip("iPLoT 那一段還沒加")
    assert _table_lines(theirs) == _table_lines(Path(__file__))
