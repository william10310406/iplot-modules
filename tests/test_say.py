import re

import iplot_rules
import say

ROW_KEYS = {
    "not_user", "gone", "no_zip", "many_zips", "not_agreed", "download", "too_big", "not_zip", "broken", "shape",
    "bad_path", "names_not_utf8", "too_large", "too_many_files", "too_many_entries", "bad_name", "invisible",
    "similar", "reserved", "removed", "taken", "title_taken", "case", "too_many_uploads", "too_many_names", "full",
    "syntax", "syntax_310", "not_utf8", "too_complex", "changelog", "not_newer", "blocked", "retry", "stuck",
    "iplot_big", "bad_version", "not_writable", "held",
}


def outside_code(text: str) -> str:
    """照 CommonMark 的反引號規則，拿掉所有行內程式碼（一串 n 個反引號，到下一串剛好 n 個為止）。"""
    out, i = [], 0
    while i < len(text):
        if text[i] != "`":
            out.append(text[i])
            i += 1
            continue
        j = i
        while j < len(text) and text[j] == "`":
            j += 1
        n = j - i
        close = next((m for m in re.finditer(r"`+", text[j:]) if len(m.group()) == n), None)
        if close is None:
            out.append(text[i:j])
            i = j
        else:
            i = j + close.end()
    return "".join(out)


def test_code_wraps_backticks():
    assert say.code("@someone") == "`@someone`"
    assert say.code("a`b") == "``a`b``"
    assert say.code("`x") == "`` `x ``"
    assert say.code("```") == "```` ``` ````"


def test_block_fence_is_longer_than_any_backtick_run():
    assert say.block(["x"]).startswith("```\n")
    fenced = say.block(["a", "```"])
    assert fenced.startswith("````\n")
    assert fenced.endswith("\n````")


def test_refuse_keeps_names_in_code():
    text = say.refuse("taken", name="@someone", owner="someone").text
    assert "`@someone`" in text
    assert "`someone`" in text
    bare = outside_code(text)
    assert "@" not in bare
    assert "#1" not in bare
    assert "@" not in outside_code(say.refuse("taken", name="#1 @x", owner="o").text)


def test_say_has_every_row_of_section_10():
    assert set(say.SAY) == ROW_KEYS
    assert say.SAY["bad_name"] == iplot_rules.BAD_NAME_TEXT
    assert say.SAY["shape"] == ("zip 裡要剛好是一個資料夾（模組的資料夾），裡面有 iplot.py（檔名全小寫）："
                                "在 Finder 對著那個資料夾按右鍵「壓縮」。")
    assert say.SAY["bad_path"] == ("zip 裡有不能用的路徑：{path}（..、絕對路徑、反斜線、控制字元、Windows 不能用的字元與保留字、"
                                   "結尾是 . 或空白、空的一段、重複或只差大小寫、檔跟資料夾同名）。")
    assert say.SAY["full"] == "工作坊的空間快滿了，研究助理處理中；暫時不收新的名字。"


def test_refuse_int_params_are_plain():
    assert "已經傳了 10 份" in say.refuse("too_many_uploads", n=10).text


def test_clip():
    assert say.clip("a" * 600, 500) == ("a" * 499 + "…", True)
    assert say.clip("短", 500) == ("短", False)
