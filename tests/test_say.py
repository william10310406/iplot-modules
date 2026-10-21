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


def test_received_reply_lists_paths_in_a_block():
    reply = say.received_reply("整理桌面", "1.0.0", ["iplot.py", "a/b.txt"], {}, [])
    assert reply.startswith("收到了：「`整理桌面`」`1.0.0`，2 個檔。網站更新之後（通常幾分鐘）在 iPLoT 按「工作坊」就看得到；"
                            "超過一小時還沒有，在這裡留言。")
    assert "公開的檔（誰都看得到、下載得到）：\n```\n整理桌面/iplot.py\n整理桌面/a/b.txt\n```" in reply
    assert "略過的檔" not in reply
    assert reply.endswith(say.MARK_RECEIVED)


def test_received_reply_counts_skipped_by_group():
    reply = say.received_reply("m", "1.0.0", ["iplot.py"], {".venv/": 2144, "__MACOSX/": 19}, ["說明被截短了"])
    assert "略過的檔（不公開，也不會裝到別人的電腦上）：\n```\n.venv/ 2144 個\n__MACOSX/ 19 個\n```" in reply
    assert "\n- 說明被截短了\n" in reply
    assert reply.index("略過的檔") < reply.index("- 說明被截短了") < reply.index(say.MARK_RECEIVED)


def test_received_reply_explains_git_names():
    reply = say.received_reply("m", "1.0.0", ["iplot.py"], {".git/": 3, ".gitignore": 1}, [])
    assert "名字以 .git 開頭的檔與資料夾（.gitignore、.github…）一律不收：它們會讓 git 少收或改掉檔。" in reply


def test_received_reply_stays_under_20000_with_2000_files():
    files = [f"d{i:04d}/" + "x" * 94 for i in range(2000)]
    reply = say.received_reply("m", "1.0.0", files, {".venv/": 5}, [])
    assert len(reply) <= say.MAX_REPLY
    assert "還有 " in reply
    assert reply.endswith(say.MARK_RECEIVED)
    short = say.received_reply("m", "1.0.0", files[:300], {}, [])
    assert "還有 200 個" in short


def test_received_reply_keeps_odd_names_in_code():
    for name in ("@someone", "#1", "a`b"):
        reply = say.received_reply(name, "#1 @v", ["```", "@x/#1"], {}, [])
        bare = outside_code(reply)
        assert "@" not in bare
        assert "#1" not in bare
        assert "````\n" in reply  # 檔名 ``` 讓圍欄變成四個
        assert f"{name}/```" in reply


def test_short_reply():
    reply = say.short_reply("@x", "1.0.0", 3)
    assert "`@x`" in reply and "3 個檔" in reply and reply.endswith(say.MARK_RECEIVED)
    assert "個檔" not in say.short_reply("@x", "1.0.0", None)
    assert "@" not in outside_code(reply)


def test_code_never_contains_a_line_break():
    shown = say.code("a\n\n@octocat [x](https://evil.example) #1\n\nb")
    assert "\n" not in shown
    assert "\\n" in shown
    bare = outside_code(shown)
    assert "@" not in bare
    assert "#1" not in bare
    for ch, esc in (("\r", "\\r"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029"), ("\x85", "\\x85"),
                    ("\x00", "\\x00"), ("\u200b", "\\u200b"), ("\t", "\\t")):
        out = say.code(f"a{ch}b")
        assert ch not in out
        assert esc in out
    assert "\\U000e0041" in say.code("a\U000e0041b")  # Cf，超過 U+FFFF
    assert say.code("a b") == "a b".join("``")  # 一般空白不動


def test_code_is_clipped():
    inner = say.code("a" * 10_000).strip("`")
    assert len(inner) == say.MAX_CODE
    assert inner.endswith("…")
    assert say.code("a" * say.MAX_CODE) == "`" + "a" * say.MAX_CODE + "`"


def test_code_escapes_lone_surrogates():
    for ch, esc in (("\ud800", "\\ud800"), ("\udfff", "\\udfff")):
        out = say.code(f"a{ch}b")
        assert ch not in out
        assert esc in out
        out.encode("utf-8")  # 落單的代理字元編不成 UTF-8：留言送不出去


def test_code_fence_is_counted_after_clipping():
    shown = say.code("`" * 10_000)
    assert len(shown) <= 3 * say.MAX_CODE + 2
    assert max(len(run) for run in re.findall("`+", shown)) <= say.MAX_CODE + 1
    for text in ("\n" * 1000, "\U000e0041" * 1000):  # 先跳脫再截
        assert len(say.code(text).strip("`")) == say.MAX_CODE


def test_every_refusal_with_parameters_stays_on_one_line():
    import string
    nasty = "a\n\n@octocat [x](https://evil.example)\n\n" * 5000
    checked = 0
    for key, sentence in say.SAY.items():
        names = [f for _, f, _, _ in string.Formatter().parse(sentence) if f]
        if not names:
            continue
        params = {n: 3 if n in ("n", "line") else nasty for n in names}
        text = say.refuse(key, **params).text
        assert text.count("\n") == 0, key  # 不用 in：失敗時 pytest 會對兩萬多行做 diff，跑好幾分鐘
        assert outside_code(text).count("@") == 0, key
        assert len(text) <= len(sentence) + len(names) * (say.MAX_CODE + 10), key
        checked += 1
    assert checked > 10
