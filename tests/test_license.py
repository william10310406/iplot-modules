"""上傳一律以 MIT 授權公開：表單那一格、機器人核的 LICENSE、registry 與 index.json 的 license。"""

import gh
import licensing
import pytest
import registry
from conftest import FakeApi, form_body
from say import SAY
from test_receive import NOW, REFUSED, att, module_zip, received, run, up

YEAR = NOW.year


def folder_of(repo, name="整理桌面"):
    return repo / "modules" / name


# --- 表單那一格 ---------------------------------------------------------------------------------

def test_form_with_the_box_checked_is_licensed():
    form = gh.parse_body(form_body())
    assert form.licensed is True and gh.form_refusal(form) is None


@pytest.mark.parametrize("body", [form_body(licensed=False), form_body(licensed=None)])
def test_unchecked_or_missing_box_is_refused(body):
    form = gh.parse_body(body)
    assert form.licensed is False
    assert gh.form_refusal(form).key == "not_licensed"


def test_capital_x_counts_and_wrong_sentence_does_not():
    assert gh.parse_body(form_body().replace("[x] " + gh.LICENSE_TEXT, "[X] " + gh.LICENSE_TEXT)).licensed is True
    assert gh.parse_body(form_body().replace(gh.LICENSE_TEXT, "我同意")).licensed is False


def test_a_checked_box_typed_into_the_notes_does_not_count():
    notes = f"### 授權\n\n- [x] {gh.LICENSE_TEXT}"
    form = gh.parse_body(form_body(notes=notes, licensed=False))
    assert form.licensed is False


def test_the_agree_box_is_not_taken_from_the_license_section():
    body = form_body(agreed=False).replace(gh.LICENSE_TEXT, gh.LICENSE_TEXT + "\n- [x] " + gh.AGREE_TEXT)
    assert gh.parse_body(body).agreed is False


def test_refused_before_anything_is_downloaded(repo, python310, tmp_path):
    api = FakeApi([up(1, body=form_body(att(1), licensed=None))])
    fetched = []

    def fetch(url, dest):
        fetched.append(url)
        raise AssertionError("不該下載")

    assert run(repo, api, {}, python310, fetch=fetch) == 0
    assert fetched == []
    assert api.comments[1] == [SAY["not_licensed"]]
    assert api.patches == [(1, REFUSED)]
    assert not folder_of(repo).exists()


def test_unchecked_box_is_refused_even_with_a_good_module(repo, python310, tmp_path):
    api = FakeApi([up(1, body=form_body(att(1), licensed=False))])
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 0
    assert api.comments[1] == [SAY["not_licensed"]]
    assert not folder_of(repo).exists()


def test_checked_box_is_received(repo, python310, tmp_path):
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 0
    assert "收到了" in api.comments[1][0]


# --- 模組裡的 LICENSE -----------------------------------------------------------------------------

RA_ID = 71483597
BODY = licensing.MIT_BODY
OSI = BODY.replace('"Software"', "\u201cSoftware\u201d").replace('"AS IS"', "\u201cAS IS\u201d")  # opensource.org 的彎引號版


def mit(*head: str, body: str = BODY) -> str:
    return "".join(f"{line}\n" for line in head) + body


def refused_with(repo, api, name):
    assert api.comments[1] == [SAY["bad_license"].format(name=f"`{name}`")]
    assert api.patches == [(1, REFUSED)]
    assert not folder_of(repo).exists()
    assert "1" not in received(repo)


def test_missing_license_is_added_with_the_uploader(repo, python310, tmp_path):
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 0
    text = (folder_of(repo) / "LICENSE").read_text(encoding="utf-8")
    assert text == licensing.license_text(222, "someone", YEAR)
    assert f"Copyright (c) {YEAR} @someone" in text and licensing.is_mit(text.encode())
    assert licensing.REMARK_ADDED in api.comments[1][0] and "LICENSE" in api.comments[1][0]


def test_research_assistant_is_known_by_account_id_not_login(repo, python310, tmp_path):
    api = FakeApi([up(1, login="whoever", user_id=RA_ID)])
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 0
    text = (folder_of(repo) / "LICENSE").read_text(encoding="utf-8")
    assert f"Copyright (c) {YEAR} Wei-Heng Chien (簡偉恆)" in text and "@whoever" not in text


def test_same_login_but_another_id_is_an_ordinary_uploader(repo, python310, tmp_path):
    api = FakeApi([up(1, login="william10310406", user_id=999)])
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 0
    text = (folder_of(repo) / "LICENSE").read_text(encoding="utf-8")
    assert f"Copyright (c) {YEAR} @william10310406" in text and "簡偉恆" not in text


def test_year_is_the_first_upload_not_this_one(repo, python310, tmp_path):
    first = {"name": "整理桌面", "version": "0.0.1", "owner_id": 222, "at": "2025-03-04T00:00:00Z"}
    reg = registry.read_json_strict(repo / "received.json")
    reg["50"] = first
    registry.write_json(repo / "received.json", reg)
    api = FakeApi([up(1)])
    from test_receive import git, seed
    git(repo, "add", "received.json")
    git(repo, "-c", "user.name=測試", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "r")
    seed(repo, {registry.key("整理桌面"): {"name": "整理桌面", "owner_id": 222, "owner": "someone", "version": "0.0.1",
                                         "notes": "", "issue": 50, "updated": "2025-03-04"}})
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 0
    assert "Copyright (c) 2025 @someone" in (folder_of(repo) / "LICENSE").read_text(encoding="utf-8")


@pytest.mark.parametrize("filename", ["LICENSE", "LICENSE.md", "LICENSE.txt", "license", "License.TXT"])
def test_mit_license_with_the_uploaders_line_is_kept_byte_for_byte(repo, python310, tmp_path, filename):
    mine = "MIT License\r\n\r\nCopyright (c) 1999 @someone\r\n\r\n" + BODY.replace("\n", "\r\n")
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path, **{filename: mine})}, python310) == 0
    folder = folder_of(repo)
    assert (folder / filename).read_bytes() == mine.encode()
    assert sorted(p.name for p in folder.iterdir()) == sorted([filename, "iplot.py"])  # 沒有再補一份
    assert licensing.REMARK_ADDED not in api.comments[1][0] and licensing.REMARK_LINE_ADDED not in api.comments[1][0]


def test_a_fork_keeps_the_original_line_and_gets_the_uploaders_after_it(repo, python310, tmp_path):
    theirs = mit("MIT License", "", "Copyright (c) 2019 Someone Else", "Copyright (c) 2021 Third Person", "")
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path, LICENSE=theirs)}, python310) == 0
    text = (folder_of(repo) / "LICENSE").read_text(encoding="utf-8")
    assert text == mit("MIT License", "", "Copyright (c) 2019 Someone Else", "Copyright (c) 2021 Third Person",
                       f"Copyright (c) {YEAR} @someone", "")
    assert "已加上你的版權行" in api.comments[1][0] and "原本的版權行都保留了" in api.comments[1][0]
    assert sorted(p.name for p in folder_of(repo).iterdir()) == ["LICENSE", "iplot.py"]
    [entry] = [f for f in registry.read_json_strict(repo / "registry.json").values()]
    assert entry["license"] == "MIT"


def test_the_stored_file_record_matches_the_edited_license(repo, python310, tmp_path, monkeypatch):
    import receive
    seen = []
    monkeypatch.setattr(receive, "may_publish", lambda u: (seen.append(u), (False, "停"))[1])
    api = FakeApi([up(1)])
    run(repo, api, {att(1): module_zip(tmp_path, LICENSE=mit("MIT License", "", "Copyright (c) 2019 A", ""))},
        python310)
    [upload] = seen
    [lic] = [f for f in upload.files if f.path == "LICENSE"]
    import hashlib
    expected = mit("MIT License", "", "Copyright (c) 2019 A", f"Copyright (c) {YEAR} @someone", "").encode()
    assert (lic.size, lic.sha256) == (len(expected), hashlib.sha256(expected).hexdigest())


@pytest.mark.parametrize("text", [
    OSI,  # 彎引號、沒有版權行以外的東西
    mit("MIT License", "", "Copyright (c) 2026 x", "", body=OSI),
    "".join(f"# {line}\n" if line else "#\n"
            for line in mit("The MIT License (MIT)", "", "Copyright (c) 2026 x", "").splitlines()),
    mit("SPDX-License-Identifier: MIT", "", "Copyright (c) 2026 x", ""),
    mit("# SPDX-License-Identifier: MIT", "# Copyright (c) 2026 x", ""),
    mit("(c) 2026 x", ""),
    mit("\u00a9 2026 x", ""),
    mit("Copyright \u00a9 2020-2026 x", "copyright (C) 2019, 2021 y", ""),
    mit("  Copyright   (c)  2026   Some  One  ", ""),
])
def test_ordinary_ways_of_writing_mit_are_accepted(text):
    assert licensing.is_mit(text.encode())


@pytest.mark.parametrize("text", [
    mit("Copyright (c) 2026 x", "", body=BODY + "Copyright (c) 2027 evil\n"),  # 檔尾的版權行
    BODY.replace("copies of the Software, and", "copies of the Software,\nCopyright (c) 2001 evil\nand"),  # 中間夾一行
    BODY.replace("THE SOFTWARE IS PROVIDED", "Copyright (c) 2001 evil\nTHE SOFTWARE IS PROVIDED"),
    mit("Copyright (c) 2026 x", "和平", ""),  # 開頭有一行不是版權行
    mit("Copyright (c) 2026 x", "All rights reserved.", ""),
    mit("Copyright (c) <year> <copyright holders>", ""),  # 沒有年份
    mit("Copyright (c) x", ""),
    mit("Copyright (c) 2026", ""),  # 沒有版權人
    mit(f"Copyright (c) 2026 {'x' * 101}", ""),  # 版權人超過 100 字
    mit("MIT License", "", "Copyright (c) 2026 x", "", body=BODY + "\nAnd you owe me lunch.\n"),
    mit("Copyright (c) 2026 x", "", body=BODY.replace("free of charge", "for a fee")),
    "Copyright (c) 2026 x\n",  # 沒有 Permission 那一行
    "",
])
def test_anything_else_is_not_mit(text):
    assert not licensing.is_mit(text.encode())


def test_the_copyright_holder_may_be_exactly_100_characters():
    assert licensing.is_mit(mit(f"Copyright (c) 2026 {'x' * 100}", "").encode())


def test_curly_quotes_are_only_forgiven_not_swapped_for_other_words():
    assert not licensing.is_mit(OSI.replace("\u201cSoftware\u201d", "\u201cProduct\u201d").encode())


def test_review_inserts_after_the_title_when_there_is_no_copyright_line():
    out, inserted = licensing.review(mit("MIT License", "").encode(), "@u", 2026)
    assert inserted and out.decode() == mit("MIT License", "", "Copyright (c) 2026 @u", "")


def test_review_inserts_at_the_top_without_title_or_copyright_and_keeps_bom_and_crlf():
    raw = b"\xef\xbb\xbf" + BODY.replace("\n", "\r\n").encode()
    out, inserted = licensing.review(raw, "@u", 2026)
    assert inserted
    assert out == b"\xef\xbb\xbf" + b"Copyright (c) 2026 @u\r\n\r\n" + BODY.replace("\n", "\r\n").encode()


def test_review_does_not_add_a_second_line_for_the_same_holder_whatever_the_year_or_case():
    text = mit("Copyright (c) 2001-2005 @U", "")
    out, inserted = licensing.review(text.encode(), "@u", 2026)
    assert not inserted and out == text.encode()


def test_review_returns_none_for_text_that_is_not_mit():
    assert licensing.review(b"GPL", "@u", 2026) is None
    assert licensing.review(b"\xff\xfe", "@u", 2026) is None


def test_holder_is_chosen_by_id():
    assert licensing.holder(RA_ID, "x") == "Wei-Heng Chien (簡偉恆)"
    assert licensing.holder(1, "william10310406") == "@william10310406"


@pytest.mark.parametrize("content", [
    "", "\n  \n", "隨便寫寫", "Apache License\nVersion 2.0, January 2004\n",
    "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n",
    mit("MIT License", "", "Copyright (c) 2026 x", "", body=BODY + "\nAnd you owe me lunch.\n"),
    mit("Copyright (c) 2026 x", "和平", ""),
    mit("", body=BODY + "Copyright (c) 2026 x\n"),
    BODY.replace("free of charge", "for a fee"),
])
def test_other_licenses_empty_gibberish_and_lines_in_the_wrong_place_are_refused(repo, python310, tmp_path, content):
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path, LICENSE=content)}, python310) == 0
    refused_with(repo, api, "LICENSE")


def test_not_utf8_license_is_refused(repo, python310, tmp_path):
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path, LICENSE=b"\xff\xfe\x00")}, python310) == 0
    refused_with(repo, api, "LICENSE")


def test_two_license_files_are_refused_even_if_both_are_mit(repo, python310, tmp_path):
    zips = {att(1): module_zip(tmp_path, LICENSE=BODY, **{"LICENSE.md": BODY})}
    api = FakeApi([up(1)])
    assert run(repo, api, zips, python310) == 0
    refused_with(repo, api, "LICENSE")


@pytest.mark.parametrize("other", ["COPYING", "COPYING.txt", "LICENCE", "licence.md", "UNLICENSE", "COPYRIGHT",
                                   "LICENSE-MIT", "LICENSE.APACHE", "LICENSE.rst", "copying.lesser"])
def test_license_lookalikes_are_refused_not_ignored(repo, python310, tmp_path, other):
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path, **{other: BODY})}, python310) == 0
    refused_with(repo, api, other)  # 不會「照收之後又補一份 LICENSE」


def test_a_lookalike_next_to_a_good_license_is_still_refused(repo, python310, tmp_path):
    api = FakeApi([up(1)])
    zips = {att(1): module_zip(tmp_path, LICENSE=BODY, COPYING="GPL")}
    assert run(repo, api, zips, python310) == 0
    refused_with(repo, api, "COPYING")


def test_a_folder_named_license_gets_the_license_sentence_not_a_broken_zip(repo, python310, tmp_path):
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path, **{"LICENSE/a.txt": "x"})}, python310) == 0
    refused_with(repo, api, "LICENSE")
    assert "壞了" not in api.comments[1][0]


def test_license_in_a_subfolder_does_not_count(repo, python310, tmp_path):
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path, **{"資料/LICENSE": "GPL", "資料/COPYING": "GPL"})},
               python310) == 0
    assert (folder_of(repo) / "LICENSE").is_file()


def test_names_are_compared_after_nfc_and_without_case(repo, python310, tmp_path):
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path, **{"Licence": BODY})}, python310) == 0
    refused_with(repo, api, "Licence")


def test_an_oversized_license_is_refused_without_reading_it(repo, python310, tmp_path):
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path, LICENSE=BODY + " " * (licensing.MAX_LICENSE + 1))},
               python310) == 0
    refused_with(repo, api, "LICENSE")


# --- licensing 本身 ---------------------------------------------------------------------------------

def test_is_mit_rejects_a_missing_sentence():
    assert not licensing.is_mit(licensing.MIT_BODY.replace("THE SOFTWARE IS PROVIDED", "").encode())


def test_the_repo_license_is_mit():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert licensing.is_mit((root / "LICENSE").read_bytes())
    assert "Copyright (c) 2026 Wei-Heng Chien (簡偉恆)" in (root / "LICENSE").read_text(encoding="utf-8")


# --- registry ---------------------------------------------------------------------------------------

def test_new_upload_is_recorded_as_mit_with_its_issue(repo, python310, tmp_path):
    api = FakeApi([up(7, body=form_body(att(7)))])
    assert run(repo, api, {att(7): module_zip(tmp_path)}, python310) == 0
    entry = registry.read_json_strict(repo / "registry.json")[registry.key("整理桌面")]
    assert (entry["license"], entry["license_issue"]) == ("MIT", 7)


def test_update_keeps_license_and_other_fields(repo, python310, tmp_path):
    from test_receive import seed
    old = {"name": "整理桌面", "owner_id": 222, "owner": "someone", "version": "0.0.1", "notes": "", "issue": 3,
           "updated": "2026-10-01", "license": "MIT", "license_issue": 3, "warning": "手動的", "unknown": [1]}
    seed(repo, {registry.key("整理桌面"): old})
    api = FakeApi([up(8)])
    assert run(repo, api, {att(8): module_zip(tmp_path)}, python310) == 0
    entry = registry.read_json_strict(repo / "registry.json")[registry.key("整理桌面")]
    assert entry["version"] == "0.0.2" and entry["issue"] == 8
    assert (entry["license"], entry["license_issue"]) == ("MIT", 8)
    assert entry["warning"] == "手動的" and entry["unknown"] == [1]


def test_update_of_a_seed_without_license_gets_one(repo, python310, tmp_path):
    from test_receive import seed
    seed(repo, {registry.key("整理桌面"): {"name": "整理桌面", "owner_id": 222, "owner": "someone",
                                         "version": "0.0.1", "notes": "", "issue": 3, "updated": "2026-10-01"}})
    api = FakeApi([up(8)])
    assert run(repo, api, {att(8): module_zip(tmp_path)}, python310) == 0
    entry = registry.read_json_strict(repo / "registry.json")[registry.key("整理桌面")]
    assert entry["license"] == "MIT"
