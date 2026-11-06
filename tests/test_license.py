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

def test_missing_license_is_added_with_the_uploader(repo, python310, tmp_path):
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 0
    text = (folder_of(repo) / "LICENSE").read_text(encoding="utf-8")
    assert text == licensing.license_text("someone", YEAR)
    assert f"Copyright (c) {YEAR} @someone" in text and licensing.is_mit(text.encode())
    assert licensing.REMARK_ADDED in api.comments[1][0] and "LICENSE" in api.comments[1][0]


def test_research_assistant_gets_the_name_not_the_login(repo, python310, tmp_path):
    api = FakeApi([up(1, login="william10310406", user_id=71483597)])
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 0
    text = (folder_of(repo) / "LICENSE").read_text(encoding="utf-8")
    assert f"Copyright (c) {YEAR} Wei-Heng Chien (簡偉恆)" in text and "@william10310406" not in text


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


@pytest.mark.parametrize("filename", ["LICENSE", "LICENSE.md", "LICENSE.txt"])
def test_mit_license_is_kept_as_is(repo, python310, tmp_path, filename):
    mine = "MIT License\n\nCopyright (c) 1999 某人\n\n" + licensing.MIT_BODY.replace("\n", "\r\n")
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path, **{filename: mine})}, python310) == 0
    folder = folder_of(repo)
    assert (folder / filename).read_bytes() == mine.encode()
    assert sorted(p.name for p in folder.iterdir()) == sorted([filename, "iplot.py"])  # 沒有再補一份
    assert licensing.REMARK_ADDED not in api.comments[1][0]


@pytest.mark.parametrize("content", [
    "", "\n  \n", "隨便寫寫", "Apache License\nVersion 2.0, January 2004\n",
    "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n",
    "MIT License\n\nCopyright (c) 2026 x\n\n" + licensing.MIT_BODY + "\nAnd you owe me lunch.\n",
    licensing.MIT_BODY.replace("free of charge", "for a fee"),
])
def test_other_licenses_empty_and_gibberish_are_refused(repo, python310, tmp_path, content):
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path, LICENSE=content)}, python310) == 0
    assert api.comments[1] == [SAY["bad_license"]]
    assert api.patches == [(1, REFUSED)]
    assert not folder_of(repo).exists()
    assert "1" not in received(repo)


def test_not_utf8_license_is_refused(repo, python310, tmp_path):
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path, LICENSE=b"\xff\xfe\x00")}, python310) == 0
    assert api.comments[1] == [SAY["bad_license"]]


def test_every_license_file_must_be_mit(repo, python310, tmp_path):
    zips = {att(1): module_zip(tmp_path, LICENSE=licensing.MIT_BODY, **{"LICENSE.md": "GPL"})}
    api = FakeApi([up(1)])
    assert run(repo, api, zips, python310) == 0
    assert api.comments[1] == [SAY["bad_license"]]


def test_license_in_a_subfolder_does_not_count(repo, python310, tmp_path):
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path, **{"資料/LICENSE": "GPL"})}, python310) == 0
    assert (folder_of(repo) / "LICENSE").is_file()


# --- licensing 本身 ---------------------------------------------------------------------------------

def test_is_mit_ignores_blank_lines_whitespace_title_and_copyright():
    squeezed = " ".join(licensing.MIT_BODY.split())
    assert licensing.is_mit(licensing.license_text("x", 2026).encode())
    assert licensing.is_mit(("\n\n  Copyright (c) 2001 A\n\n" + squeezed + "\n").encode())
    assert licensing.is_mit(("The MIT License (MIT)\n" + licensing.MIT_BODY).encode("utf-8-sig"))


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
