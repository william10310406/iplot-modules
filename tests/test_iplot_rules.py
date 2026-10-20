"""tools/iplot_rules.py：iPLoT 規則的抄本。抄得對不對，最後一個測試拿隔壁的 iPLoT 直接比。"""

import dataclasses
import json
import zipfile

import iplot_rules
import pytest
from conftest import load_iplot
from test_rules_table import BAD_NAMES, NEWER

# 設計第 10 節「名稱不合規則」那一句＝core/text.py 的 T["bad_name"] 原文
CORE_BAD_NAME = ("名稱不能是空白、以 . 開頭、結尾是 . 或空白、含 / \\ : * ? \" < > |，"
                 "也不能是 CON、NUL 這類 Windows 保留字（模組要能複製到任何系統）")
LATEST_ERRORS = ("不是 UTF-8 的文字檔", "裡面沒有「## [1.0.0] - 日期」這樣的一節", "最上面那一節的版本「")
ENTRY = {"name": "m", "version": "1.0", "zip_url": "https://x/m.zip", "sha256": "ab"}


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def _zip(path, names):
    with zipfile.ZipFile(path, "w") as z:
        for name in names:
            z.writestr(name, "" if name.endswith("/") else "x = 1\n")
    return path


def test_bad_name_text_is_the_core_sentence():
    assert iplot_rules.BAD_NAME_TEXT == CORE_BAD_NAME


def test_read_meta_reads_title_icon_and_first_paragraph(tmp_path):
    f = _write(tmp_path / "iplot.py", '"""整理桌面\n把檔案分類。\n\n第二段不算。"""\n'
                                      'TITLE = "整理"\nICON = "🧹"\n\ndef run():\n    pass\n')
    meta = iplot_rules.read_meta(f)
    assert meta == iplot_rules.Meta("整理", "整理桌面\n把檔案分類。", True, False, None, "🧹")


def test_read_meta_syntax_error_has_the_line(tmp_path):
    meta = iplot_rules.read_meta(_write(tmp_path / "iplot.py", "x = (\n"))
    assert meta.error.startswith("第 1 行：")


@pytest.mark.parametrize("data", [b"x = 1\x00\n", b"x = '\xe9'\n"])
def test_read_meta_without_a_line_is_plain(tmp_path, data):
    f = tmp_path / "iplot.py"
    f.write_bytes(data)
    meta = iplot_rules.read_meta(f)
    assert meta.error is not None
    assert not meta.error.startswith("第 ")


def test_read_meta_lets_memory_error_through(tmp_path):
    # read_meta 跟 iPLoT 一樣不接 MemoryError：呼叫的人（Task 4）要自己包
    with pytest.raises(MemoryError):
        iplot_rules.read_meta(_write(tmp_path / "iplot.py", "-" * 100000))


def test_latest_reads_the_top_section_and_first_paragraph(tmp_path):
    log = tmp_path / "CHANGELOG.md"
    log.write_text("﻿# Changelog\n\n## [Unreleased]\n\n- 還沒發\n\n## [1.3.0] - 2026-10-01\n\n摘要。\n\n- 細節\n\n"
                   "## [1.2.0] - 2026-09-01\n\n舊的。\n", encoding="utf-8")
    assert iplot_rules.latest(log) == ("1.3.0", "摘要。")


@pytest.mark.parametrize("log", ["## [1.0.0]\n\n中文\n".encode("big5"), "# Changelog\n\n沒有任何一版。\n".encode(),
                                 b"## [v1.0.0] - x\n", b"## [1.0.0-beta.1]\n"])
def test_latest_refuses_unreadable_changelogs(tmp_path, log):
    f = tmp_path / "CHANGELOG.md"
    f.write_bytes(log)
    with pytest.raises(ValueError) as exc:
        iplot_rules.latest(f)
    assert str(exc.value).startswith(LATEST_ERRORS)


def test_latest_accepts_full_width_digits(tmp_path):
    # publish.latest 的 \d 收全形數字：所以 Task 3 另外用 VERSION_RE 擋
    f = _write(tmp_path / "CHANGELOG.md", "## [１.０.０]\n\n摘要\n")
    assert iplot_rules.latest(f) == ("１.０.０", "摘要")


def test_latest_without_the_file_is_none(tmp_path):
    assert iplot_rules.latest(tmp_path / "CHANGELOG.md") == (None, "")


def test_url_quotes_every_part():
    assert (iplot_rules.url("https://x/y/", "模組", "C#工具.zip")
            == "https://x/y/%E6%A8%A1%E7%B5%84/C%23%E5%B7%A5%E5%85%B7.zip")
    assert iplot_rules.url("https://x/y", "a%20b.zip").endswith("/a%2520b.zip")


def test_read_listing_prefers_uploads_even_when_empty():
    assert iplot_rules.read_listing({"modules": [ENTRY], "uploads": []}) == ([], "")


def test_read_listing_falls_back_to_modules():
    assert iplot_rules.read_listing({"modules": [ENTRY]}) == ([ENTRY], "")


@pytest.mark.parametrize("notice, shown", [("x", "x"), (5, ""), (None, ""), (["x"], "")])
def test_read_listing_notice_must_be_a_string(notice, shown):
    assert iplot_rules.read_listing({"notice": notice, "uploads": []}) == ([], shown)


@pytest.mark.parametrize("data", [
    [], "x", None, {"mods": []}, {"uploads": None}, {"uploads": "x"}, {"modules": "x"}, {"uploads": ["x"]},
    *({"uploads": [{k: v for k, v in ENTRY.items() if k != missing}]} for missing in iplot_rules.NEEDED),
    *({"uploads": [{**ENTRY, key: 1}]} for key in ("name", "zip_url", "sha256")),
])
def test_read_listing_checks_like_read_index(data):
    with pytest.raises(ValueError):
        iplot_rules.read_listing(data)


def test_read_listing_turns_versions_into_text_and_keeps_the_first():
    entries, _ = iplot_rules.read_listing({"uploads": [{**ENTRY, "version": 2}, {**ENTRY, "version": "9"}]})
    assert entries == [{**ENTRY, "version": "2"}]


@pytest.mark.parametrize("name, names, problem", [
    ("m", ["m/", "m/iplot.py", "m/a/b.txt"], None),
    ("m", ["m/iplot.py", "m/.history/x.py", "m/.DS_Store"], None),
    (".m", [".m/iplot.py"], "索引裡的模組名稱不是單純的資料夾名"),
    ("a/b", ["a/b/iplot.py"], "索引裡的模組名稱不是單純的資料夾名"),
    ("m", ["x/iplot.py"], "zip 的最上層不是「m/」"),
    ("m", ["m/iplot.py", "n/iplot.py"], "zip 的最上層不是「m/」"),
    ("m", ["m/iplot.py", "m/../x.py"], "zip 的最上層不是「m/」"),
    ("m", ["m/", "m/main.py"], "包裡沒有 iplot.py"),
    ("m", ["m/.history/iplot.py"], "包裡沒有 iplot.py"),
    ("m", ["m/IPLOT.py"], "包裡沒有 iplot.py"),
    ("m", ["m/sub/iplot.py"], "包裡沒有 iplot.py"),
])
def test_install_shape_matches_workshop_install(tmp_path, name, names, problem):
    assert iplot_rules.install_shape(_zip(tmp_path / "p.zip", names), name) == problem


def test_header_names_every_source():
    doc = iplot_rules.__doc__
    for source in ("core/create.py", "core/text.py", "core/types.py", "core/meta.py", "tools/publish.py",
                   "modules/工作坊/workshop.py"):
        assert source in doc


SAMPLES = [
    '"""說明\n第二行\n\n不算"""\nTITLE = "t"\nICON = "i"\ndef run():\n    pass\ndef on_files(p):\n    pass\n',
    '"""沒有 run"""\nTITLE = 1\nICON = f"x"\n',
    "def f(:\n",
]
LISTINGS = [
    {"modules": [ENTRY], "uploads": []},
    {"modules": [ENTRY]},
    {"notice": "公告", "uploads": [ENTRY, {**ENTRY, "version": 3}]},
    {"notice": 5, "uploads": [{**ENTRY, "version": 2}]},
    {"uploads": None},
    {"uploads": [{**ENTRY, "sha256": 1}]},
    [],
]


def _outcome(call):
    try:
        return call()
    except ValueError:
        return "ValueError"


def test_copies_agree_with_iplot_next_door(iplot_next_door, tmp_path):
    create = load_iplot("core/create.py", "core.create")
    text = load_iplot("core/text.py", "core.text")
    meta = load_iplot("core/meta.py", "core.meta")
    publish = load_iplot("tools/publish.py", "iplot_publish")
    workshop = load_iplot("modules/工作坊/workshop.py", "iplot_workshop")

    assert iplot_rules.FORBIDDEN_CHARS == create.FORBIDDEN_CHARS
    assert iplot_rules.RESERVED == create.RESERVED
    assert text.T["bad_name"] == iplot_rules.BAD_NAME_TEXT
    assert text.T["syntax_error"] == iplot_rules.SYNTAX_ERROR
    assert iplot_rules.SKIP == workshop.SKIP == publish.SKIP
    assert iplot_rules.NEEDED == workshop.NEEDED
    for name, _ in BAD_NAMES:
        assert iplot_rules.bad_name(name) == create._bad_name(name), name
    for current, latest, _ in NEWER:
        assert iplot_rules.newer(current, latest) == workshop._newer(current, latest), (current, latest)
    for i, source in enumerate(SAMPLES):
        f = _write(tmp_path / f"iplot{i}.py", source)
        assert dataclasses.astuple(iplot_rules.read_meta(f)) == dataclasses.astuple(meta.read_meta(f))

    if not hasattr(workshop, "read_listing"):
        return  # iPLoT 的 Task 12 還沒做：read_listing 那一段之後再比
    for i, data in enumerate(LISTINGS):
        f = _write(tmp_path / f"index{i}.json", json.dumps(data, ensure_ascii=False))
        assert _outcome(lambda d=data: iplot_rules.read_listing(d)) == _outcome(
            lambda f=f: workshop.read_listing(f.as_uri())), data
