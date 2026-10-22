import shutil
import subprocess
from pathlib import Path

import pytest
import source
from registry import key
from say import SAY, Refusal, code
from source import (
    MAX_DESCRIPTION,
    MAX_ICON,
    MAX_IPLOT,
    PY310,
    PY310_CODE,
    Python310Missing,
    Source,
    TooComplex,
    check_source,
    find_python310,
    syntax_310,
)
from test_registry import ME, make_registry

needs310 = pytest.mark.skipif(shutil.which("python3.10") is None, reason="沒有 python3.10")
FAKE_PY = "/fake/python3.10"


def fine(*args, **kwargs):
    """假的 3.10：什麼都說可以。"""
    return subprocess.CompletedProcess(args[0], 0, b"", b"")


def put(tmp_path: Path, source_text: bytes | str, folder: str = "Foo") -> Path:
    d = tmp_path / folder
    d.mkdir()
    data = source_text.encode("utf-8") if isinstance(source_text, str) else source_text
    (d / "iplot.py").write_bytes(data)
    return d


def check(folder: Path, name: str = "Foo", python: str = FAKE_PY, run=fine, registry=None):
    return check_source(folder, name, ME, registry if registry is not None else make_registry(), python, run)


def test_iplot_over_1mb_is_refused(tmp_path):
    d = put(tmp_path, b"#" * (MAX_IPLOT + 1))
    result = check(d)
    assert isinstance(result, Refusal) and result.key == "iplot_big"


def test_syntax_error_reports_the_line(tmp_path):
    result = check(put(tmp_path, "def f(:\n"))
    assert isinstance(result, Refusal) and result.key == "syntax"
    assert "iplot.py 第 1 行：" in result.text


def test_long_dash_line_is_too_complex(tmp_path):
    result = check(put(tmp_path, "-" * 100_000))
    assert isinstance(result, Refusal) and result.key == "too_complex"


def test_deep_nesting_is_too_complex(tmp_path):
    result = check(put(tmp_path, "x = " + "not " * 100_000 + "1"))
    assert isinstance(result, Refusal) and result.key == "too_complex"


def test_latin1_with_a_coding_cookie_is_not_utf8(tmp_path):
    result = check(put(tmp_path, b"# -*- coding: latin-1 -*-\nx = '\xe9'\n"))
    assert isinstance(result, Refusal) and result.key == "not_utf8"


def test_nul_byte_is_not_utf8(tmp_path):
    result = check(put(tmp_path, b"x = 1\x00\n"))
    assert isinstance(result, Refusal) and result.key == "not_utf8"


def test_bom_is_fine(tmp_path):
    result = check(put(tmp_path, "\ufeff" + '"""說明"""\nTITLE = "Foo"\n'))
    assert isinstance(result, Source)
    assert result.title == "Foo" and result.description == "說明"


@needs310
@pytest.mark.parametrize("src, line", [('d = {"a": 1}\nx = f"{d["a"]}"\n', 2), ("type X = int\n", 1),
                                       ("def f[T](): pass\n", 1),
                                       ("try:\n    pass\nexcept* ValueError:\n    pass\n", 3)])
def test_python310_only_syntax_is_refused(tmp_path, src, line):
    result = check(put(tmp_path, src), python=shutil.which("python3.10"), run=subprocess.run)
    assert isinstance(result, Refusal) and result.key == "syntax_310"
    assert f"第 {line} 行" in result.text
    assert "iPLoT 要能在 Python 3.10 跑" in result.text


def test_python310_check_gets_the_source_on_stdin(tmp_path):
    raw = "\ufeffx = 1\n".encode()
    calls = []

    def spy(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    assert syntax_310(raw, FAKE_PY, spy) is None
    [(argv, kwargs)] = calls
    assert argv == [FAKE_PY, "-I", "-c", PY310_CODE]
    assert kwargs["input"] == raw
    assert kwargs["capture_output"] is True and kwargs["timeout"] == source.PY310_TIMEOUT
    result = check(put(tmp_path, raw), run=spy)
    assert isinstance(result, Source)
    assert calls[-1][0] == [FAKE_PY, "-I", "-c", PY310_CODE] and calls[-1][1]["input"] == raw


@needs310
def test_python310_check_never_runs_the_module(tmp_path):
    ran = tmp_path / "ran"
    src = (f'open({str(ran)!r}, "w").close()\n'
           f'if __name__ == "__main__":\n    open({str(ran)!r}, "w").close()\n')
    result = check(put(tmp_path, src), python=shutil.which("python3.10"), run=subprocess.run)
    assert isinstance(result, Source)
    assert not ran.exists()


def test_python310_crash_or_timeout_is_too_complex(tmp_path):
    def crashed(argv, **kwargs):
        return subprocess.CompletedProcess(argv, -9, b"", b"")

    def odd_json(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, b'"nope"', b"")

    def timed_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 60)

    for run in (crashed, odd_json, timed_out):
        with pytest.raises(TooComplex):
            syntax_310(b"x = 1\n", FAKE_PY, run)
        folder = put(tmp_path, "x = 1\n", folder=f"Foo{run.__name__}")
        result = check(folder, run=run)
        assert isinstance(result, Refusal) and result.key == "too_complex"


def test_exceptions_are_plain_exceptions():
    assert TooComplex.__bases__ == (Exception,) and Python310Missing.__bases__ == (Exception,)


def test_description_and_icon_are_clipped_with_remarks(tmp_path):
    text = '"""' + "字" * 600 + '"""\nICON = "' + "圖" * 20 + '"\n'
    result = check(put(tmp_path, text))
    assert isinstance(result, Source)
    assert len(result.description) == MAX_DESCRIPTION and len(result.icon) == MAX_ICON
    assert result.remarks == ("說明超過 500 字，清單上只顯示前 500 字。", "ICON 超過 16 個字，清單上只顯示前 16 個。")


def test_title_owned_by_someone_else_is_refused(tmp_path):
    folder = put(tmp_path, 'TITLE = "更新"\nICON = "\u2b06\ufe0f"\n', folder="隨便取")
    result = check(folder, name="隨便取")
    assert isinstance(result, Refusal) and result.key == "title_taken"
    assert code("更新") in result.text


def test_title_equal_to_own_name_is_fine(tmp_path):
    result = check(put(tmp_path, 'TITLE = "FOO"\n'))
    assert isinstance(result, Source) and result.title == "FOO"
    assert result.description == "" and result.icon == "" and result.remarks == ()


def test_title_nobody_has_is_fine(tmp_path):
    result = check(put(tmp_path, 'TITLE = "A/B 測試"\n'))
    assert isinstance(result, Source) and result.title == "A/B 測試"


def test_title_none_is_fine(tmp_path):
    assert isinstance(check(put(tmp_path, "x = 1\n")), Source)


def test_title_too_similar_to_someone_elses_is_refused(tmp_path):
    result = check(put(tmp_path, 'TITLE = "整理 桌面"\n'))
    assert isinstance(result, Refusal) and result.key == "title_taken"
    assert key("整理桌面") in make_registry()


def test_title_with_invisible_characters_is_refused(tmp_path):
    result = check(put(tmp_path, 'TITLE = "開工\\u200b"\n'))
    assert isinstance(result, Refusal) and result.key == "title_taken"


@pytest.mark.parametrize("src", ['"""\\ud800 說明"""\n', 'ICON = "\\ud800"\n', 'TITLE = "\\ud800"\n',
                                 'TITLE = "\\udfff"\n'], ids=["description", "icon", "title", "title_low"])
def test_lone_surrogate_is_refused(tmp_path, src):
    """檔裡是 ASCII 的反斜線跳脫：解析出來的字串有落單的代理字元，編不成 UTF-8，index.json 寫不出來。"""
    folder = put(tmp_path, src)
    assert b"\\ud" in (folder / "iplot.py").read_bytes()  # 檔裡沒有代理字元本身（那根本編不成 UTF-8）
    result = check(folder)
    assert isinstance(result, Refusal) and result.key == "surrogate"
    assert result.text == SAY["surrogate"]


@needs310
def test_python310_syntax_is_reported_before_a_lone_surrogate(tmp_path):
    """兩樣都有：先說 3.10 的語法（行號、訊息），代理字元那一道排在它後面。"""
    folder = put(tmp_path, 'ICON = "\\ud800"\ntype X = int\n')  # 檔裡是 ASCII 的反斜線跳脫；第 2 行 3.12 收、3.10 不收
    assert b'"\\ud800"' in (folder / "iplot.py").read_bytes()
    result = check(folder, python=shutil.which("python3.10"), run=subprocess.run)
    assert isinstance(result, Refusal) and result.key == "syntax_310"
    assert "第 2 行" in result.text


def test_emoji_icon_is_not_a_lone_surrogate(tmp_path):
    result = check(put(tmp_path, 'ICON = "\U0001F600"\n'))  # 檔裡是真的表情符號（四個位元組的 UTF-8）
    assert isinstance(result, Source) and result.icon == "\U0001F600"


def test_find_python310_uses_which(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert find_python310() is None
    monkeypatch.setattr(shutil, "which", lambda name: FAKE_PY if name == PY310 else None)
    assert find_python310() == FAKE_PY
