"""上傳一律以 MIT 授權公開：表單那一格、版權人（registry 的 copyright）、機器人產生的 LICENSE（licenses.json 記雜湊）、
像授權的檔不收。機器人不解讀上傳者寫的授權文字。"""

import json
from pathlib import Path

import build
import gh
import licensing
import pytest
import receive
import registry
from conftest import FakeApi, form_body
from say import SAY, refuse
from test_receive import NOW, PUBLISHED, REFUSED, att, git, module_zip, received, run, seed, up

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


def test_fork_of_field_is_read_from_the_form():
    assert gh.parse_body(form_body(fork_of="原版")).fork_of == "原版"
    assert gh.parse_body(form_body(fork_of="  原版 \n")).fork_of == "原版"


@pytest.mark.parametrize("body", [form_body(fork_of=""), form_body()])
def test_empty_or_missing_fork_of_is_empty(body):
    form = gh.parse_body(body)
    assert form.fork_of == "" and form.agreed and form.licensed and form.notes == ""


def test_fork_of_does_not_leak_into_the_notes_or_the_other_way():
    form = gh.parse_body(form_body(notes="改了一點", fork_of="原版"))
    assert (form.notes, form.fork_of) == ("改了一點", "原版")
    forged = f"### {gh.HEADING_FORK}\n\n別人的模組"
    form = gh.parse_body(form_body(notes=forged, fork_of="真的"))
    assert form.fork_of == "真的" and "別人的模組" in form.notes


def test_a_fork_of_heading_typed_after_the_agree_box_does_not_count():
    body = form_body().replace(gh.LICENSE_TEXT, gh.LICENSE_TEXT + f"\n\n### {gh.HEADING_FORK}\n\n原版")
    assert gh.parse_body(body).fork_of == ""


# --- 版權人在 registry（用帳號 id 認）、LICENSE 由機器人產生 ---------------------------------------------------

RA_ID = 71483597
RA = "Wei-Heng Chien (簡偉恆)"
YEAR = NOW.year
BODY = licensing.MIT_BODY
ROOT = Path(__file__).resolve().parents[1]
SOMEONE = ("someone", 222)
AUTHOR = ("author", 111)


def person(login, user_id, year=YEAR):
    """清單裡的一筆：[年份, 顯示名, 帳號 id]。"""
    return [year, licensing.holder(user_id, login), user_id]


def entry_of(repo, name="整理桌面"):
    return registry.read_json_strict(repo / "registry.json")[registry.key(name)]


def licenses_of(repo):
    return registry.read_json_strict(repo / "licenses.json")


def upload(repo, python310, tmp_path, n, *, name="整理桌面", login="someone", user_id=222, iplot=None, fork_of=None,
           **extra):
    """傳一份、收到了；回 (api, 這個模組的 LICENSE 位元組)。"""
    api = FakeApi([up(n, login=login, user_id=user_id, body=form_body(att(n), fork_of=fork_of))])
    kwargs = {} if iplot is None else {"iplot": iplot}
    assert run(repo, api, {att(n): module_zip(tmp_path, name, **kwargs, **extra)}, python310) == 0
    assert api.patches == [(n, PUBLISHED)], api.comments
    return api, (folder_of(repo, name) / "LICENSE").read_bytes()


def refused(repo, python310, tmp_path, n, text, *, name="整理桌面", login="someone", user_id=222, fork_of=None,
            **extra):
    """傳一份、被拒收，回覆是 text；modules/ 裡沒有、received 裡沒有，licenses.json、registry.json 沒有變。"""
    before = (repo / "licenses.json").read_bytes(), (repo / "registry.json").read_bytes()
    existed = folder_of(repo, name).exists()
    api = FakeApi([up(n, login=login, user_id=user_id, body=form_body(att(n), fork_of=fork_of))])
    assert run(repo, api, {att(n): module_zip(tmp_path, name, **extra)}, python310) == 0
    assert api.comments[n] == [text], api.comments
    assert api.patches == [(n, REFUSED)]
    assert str(n) not in received(repo)
    assert ((repo / "licenses.json").read_bytes(), (repo / "registry.json").read_bytes()) == before
    assert folder_of(repo, name).exists() == existed
    return api


def like(path):
    return refuse("license_like", path=path).text


UNKNOWN = SAY["license_unknown"]


def hashlib_sha(raw: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def test_missing_license_is_generated_with_the_uploader(repo, python310, tmp_path):
    api, raw = upload(repo, python310, tmp_path, 1)
    holder = "@someone (GitHub user 222)"
    assert raw == licensing.render([[YEAR, holder, 222]]).encode("utf-8")
    assert raw.decode("utf-8").startswith(f"MIT License\n\nCopyright (c) {YEAR} {holder}\n\nPermission is hereby")
    assert entry_of(repo)["copyright"] == [[YEAR, holder, 222]]
    assert f"Copyright (c) {YEAR} {holder}" in api.comments[1][0]


def test_research_assistant_is_known_by_account_id_not_login(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1, login="whoever", user_id=RA_ID)
    assert entry_of(repo)["copyright"] == [[YEAR, RA, RA_ID]]
    assert "@whoever" not in (folder_of(repo) / "LICENSE").read_text(encoding="utf-8")


def test_same_login_but_another_id_is_an_ordinary_uploader(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1, login="william10310406", user_id=999)
    text = (folder_of(repo) / "LICENSE").read_text(encoding="utf-8")
    assert f"Copyright (c) {YEAR} @william10310406 (GitHub user 999)" in text and "簡偉恆" not in text


def test_the_same_list_always_makes_the_same_bytes():
    cp = [[2025, "@a (GitHub user 1)", 1], [2026, RA, RA_ID]]
    assert licensing.render(cp) == licensing.render([list(x) for x in cp])
    assert licensing.digest(cp) == licensing.digest(tuple(tuple(x) for x in cp))
    assert licensing.render(cp) == (
        f"MIT License\n\nCopyright (c) 2025 @a (GitHub user 1)\nCopyright (c) 2026 {RA}\n\n{BODY}")
    assert licensing.digest(cp) != licensing.digest(cp[::-1])


def test_two_modules_with_the_same_list_have_identical_license_files(repo, python310, tmp_path):
    _, first = upload(repo, python310, tmp_path, 1, name="甲")
    _, second = upload(repo, python310, tmp_path, 2, name="乙")
    assert first == second
    assert list(licenses_of(repo)) == [licensing.digest([person(*SOMEONE)])]


def test_every_generated_license_is_recorded_by_its_hash(repo, python310, tmp_path):
    _, raw = upload(repo, python310, tmp_path, 1)
    assert licenses_of(repo) == {hashlib_sha(raw): [person(*SOMEONE)]}
    assert hashlib_sha(raw) == licensing.digest([person(*SOMEONE)])
    stat = git(repo, "show", "--stat", "--format=", "HEAD")
    assert "licenses.json" in stat and "registry.json" in stat


def test_the_uploaded_license_is_never_what_gets_stored(repo, python310, tmp_path):
    _, generated = upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    for n, filename in ((2, "LICENSE"), (3, "LICENSE.md"), (4, "LICENSE.txt"), (5, "license")):
        _, raw = upload(repo, python310, tmp_path, n, name=f"改{n}", **{filename: generated})
        assert sorted(p.name for p in folder_of(repo, f"改{n}").iterdir()) == ["LICENSE", "iplot.py"]
        assert raw.decode("utf-8").count("Copyright (c)") == 2


def test_update_without_license_keeps_the_list_and_adds_nobody(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1)
    upload(repo, python310, tmp_path, 2, iplot='"""說明"""\n# 改了一點\n')
    assert entry_of(repo)["copyright"] == [person(*SOMEONE)]
    assert entry_of(repo)["version"] == "0.0.2"
    assert licenses_of(repo) == {licensing.digest([person(*SOMEONE)]): [person(*SOMEONE)]}


def test_a_seed_without_copyright_gets_the_uploader(repo, python310, tmp_path):
    seed(repo, {registry.key("整理桌面"): {"name": "整理桌面", "owner_id": 222, "owner": "someone",
                                         "version": "0.0.1", "notes": "", "issue": 3, "updated": "2026-10-01"}})
    upload(repo, python310, tmp_path, 8)
    entry = entry_of(repo)
    assert entry["copyright"] == [person(*SOMEONE)] and entry["license"] == "MIT"


# --- 認人只認帳號 id ---------------------------------------------------------------------------------------

def test_merge_is_by_id_keeps_order_and_the_first_display_name_and_never_removes():
    base = [person("a", 1, 2025), person("b", 2, 2026)]
    again = [[2030, "@renamed (GitHub user 2)", 2], person("c", 3, 2027)]
    assert licensing.merge(base, again, [[2031, "@a (GitHub user 1)", 1]]) == [*base, person("c", 3, 2027)]
    assert licensing.merge([], [person("c", 3)]) == [person("c", 3)]
    assert licensing.merge(base, []) == base and base == [person("a", 1, 2025), person("b", 2, 2026)]


def test_the_same_display_name_with_two_ids_is_two_people():
    cp = licensing.merge([person("author", 111)], [person("author", 999)])
    assert [item[2] for item in cp] == [111, 999]


def test_a_renamed_account_uploading_again_changes_nothing(repo, python310, tmp_path):
    _, first = upload(repo, python310, tmp_path, 1, login="old-name", user_id=111)
    _, second = upload(repo, python310, tmp_path, 2, login="new-name", user_id=111, iplot='"""說明"""\n# 2\n')
    assert entry_of(repo)["copyright"] == [person("old-name", 111)]
    assert second == first and b"new-name" not in second
    assert entry_of(repo)["owner"] == "new-name"  # registry 的 owner（現在的帳號名）照舊會更新，版權人不動


def test_a_renamed_account_forking_its_own_module_is_not_added_twice(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1, name="原版", login="old-name", user_id=111)
    upload(repo, python310, tmp_path, 2, name="改版", login="new-name", user_id=111, fork_of="原版")
    assert entry_of(repo, "改版")["copyright"] == [person("old-name", 111)]


def test_a_reused_login_is_a_different_person_not_the_original_author(repo, python310, tmp_path):
    # author（id 111）上傳原版，之後改名；另一個人（id 999）註冊了 author 這個名字，附原版的 LICENSE 改了再傳
    _, original = upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    upload(repo, python310, tmp_path, 2, name="冒名", login="author", user_id=999, LICENSE=original)
    assert entry_of(repo, "冒名")["copyright"] == [person("author", 111), person("author", 999)]
    text = (folder_of(repo, "冒名") / "LICENSE").read_text(encoding="utf-8")
    assert "@author (GitHub user 111)" in text and "@author (GitHub user 999)" in text


# --- 清單不合格就不寫入 -------------------------------------------------------------------------------------

@pytest.mark.parametrize("item", [
    [2026, "@a\n\nAdditional terms: no commercial use. (GitHub user 1)", 1],  # 顯示名夾帶換行與條款
    [2026, "@a (GitHub user 1)\nNo commercial use.", 1],
    [2026, "@a (GitHub user 1)\n", 1],
    [2026, "@a (GitHub user 2)", 1],             # 數字不等於 id
    [2026, "@a (GitHub user 1) and others", 1],
    [2026, "@a (GitHub user ١)", 1],              # 非 ASCII 的數字
    [2026, "@" + "a" * 40 + " (GitHub user 1)", 1],  # 帳號名超過 39 個字
    [2026, "@ (GitHub user 1)", 1],
    [2026, "@a_b (GitHub user 1)", 1],
    [2026, "a (GitHub user 1)", 1],
    [2026, "@a", 1],                              # 舊格式（沒有 id 的那一句）
    [2026, "Someone Else", 1],
    [2026, RA + " ", RA_ID],
    [2026, "@a (GitHub user 1)", 0],
    [2026, "@a (GitHub user -1)", -1],
    [2026, "@a (GitHub user 1)", True],
    [2026, "@a (GitHub user 1)", "1"],
    [2026, "@a (GitHub user 1)", 1.0],
    [2026, "@a (GitHub user 1)", None],
    ["2026", "@a (GitHub user 1)", 1],
    [2026.5, "@a (GitHub user 1)", 1],
    [999, "@a (GitHub user 1)", 1],
    [10000, "@a (GitHub user 1)", 1],
    [2026, 5, 1],
    [2026, "@a (GitHub user 1)"],                # 舊的兩欄
    [2026, "@a (GitHub user 1)", 1, "extra"],
    "Copyright (c) 2026 x",
    None,
])
def test_render_refuses_a_bad_entry(item):
    with pytest.raises(licensing.BadCopyright):
        licensing.render([person("ok", 5), item])
    with pytest.raises(licensing.BadCopyright):
        licensing.merge([item], [])
    with pytest.raises(licensing.BadCopyright):
        licensing.merge([], [item])


@pytest.mark.parametrize("bad", ["x", 5, None, {"a": 1}])
def test_render_refuses_a_list_that_is_not_a_list(bad):
    with pytest.raises(licensing.BadCopyright):
        licensing.render(bad)


@pytest.mark.parametrize("item", [
    [2026, RA, RA_ID], [1000, "@a (GitHub user 1)", 1], [9999, "@a-b (GitHub user 123456789)", 123456789],
    [2026, "@" + "a" * 39 + " (GitHub user 7)", 7], [2026, "@A (GitHub user 7)", 7],
])
def test_render_takes_good_entries(item):
    assert item[1] in licensing.render([item])


def test_bad_exception_is_not_a_zip_error():
    assert not issubclass(licensing.BadCopyright, receive.KNOWN)


def stuck_with(repo, python310, tmp_path, n):
    api = FakeApi([up(n)])
    assert run(repo, api, {att(n): module_zip(tmp_path, iplot='"""說明"""\n# 新的一版\n')}, python310) == 0
    assert api.comments[n] == [SAY["stuck"]]
    assert api.patches == [(n, {"labels": ["卡住"]})]
    assert str(n) not in received(repo)
    assert git(repo, "status", "--porcelain") == ""
    return api


def test_a_hand_edited_registry_holder_is_never_written_into_a_license(repo, python310, tmp_path):
    _, before = upload(repo, python310, tmp_path, 1)
    data = registry.read_json_strict(repo / "registry.json")
    data[registry.key("整理桌面")]["copyright"] = [[2026, "@someone\nNo commercial use.", 222]]
    seed(repo, data)
    registry_before = (repo / "registry.json").read_bytes()
    stuck_with(repo, python310, tmp_path, 2)
    assert (folder_of(repo) / "LICENSE").read_bytes() == before            # 沒有被換掉
    assert (repo / "registry.json").read_bytes() == registry_before
    assert b"No commercial use" not in (repo / "licenses.json").read_bytes()


@pytest.mark.parametrize("bad", [[[2026, "@someone (GitHub user 222)"]], [[2026, "@x (GitHub user 9)", 8]], "text", 5])
def test_every_kind_of_broken_copyright_in_the_registry_is_stuck_not_written(repo, python310, tmp_path, bad):
    upload(repo, python310, tmp_path, 1)
    data = registry.read_json_strict(repo / "registry.json")
    data[registry.key("整理桌面")]["copyright"] = bad
    seed(repo, data)
    stuck_with(repo, python310, tmp_path, 2)


def test_a_broken_entry_in_licenses_json_is_stuck_when_it_is_used(repo, python310, tmp_path):
    _, original = upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    (repo / "licenses.json").write_text(json.dumps({hashlib_sha(original): [[2026, "@evil\nterms", 111]]}),
                                        encoding="utf-8")
    git(repo, "add", "licenses.json")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "x")
    api = FakeApi([up(2)])
    assert run(repo, api, {att(2): module_zip(tmp_path, LICENSE=original)}, python310) == 0
    assert api.comments[2] == [SAY["stuck"]]


def test_a_broken_entry_of_the_module_forked_from_is_stuck(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    data = registry.read_json_strict(repo / "registry.json")
    data[registry.key("原版")]["copyright"] = [[2026, "@author\nterms", 111]]
    seed(repo, data)
    api = FakeApi([up(2, body=form_body(att(2), fork_of="原版"))])
    assert run(repo, api, {att(2): module_zip(tmp_path)}, python310) == 0
    assert api.comments[2] == [SAY["stuck"]]
    assert not folder_of(repo).exists()


# --- 改別人的模組（fork）：LICENSE 用雜湊認 -------------------------------------------------------------

def fork_via_license(repo, python310, tmp_path, n=2, **extra):
    """author 上傳「原版」，someone 把它的 LICENSE 原樣放進「整理桌面」再傳。回 (api, 原版的 LICENSE)。"""
    _, original = upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    api, _ = upload(repo, python310, tmp_path, n, LICENSE=original, **extra)
    return api, original


def test_a_fork_by_license_keeps_the_original_authors_and_adds_the_uploader(repo, python310, tmp_path):
    api, original = fork_via_license(repo, python310, tmp_path)
    expected = [person("author", 111), person(*SOMEONE)]
    assert entry_of(repo)["copyright"] == expected
    assert (folder_of(repo) / "LICENSE").read_bytes() == licensing.render(expected).encode("utf-8")
    assert licenses_of(repo)[licensing.digest(expected)] == expected
    assert (folder_of(repo, "原版") / "LICENSE").read_bytes() == original
    assert entry_of(repo, "原版")["copyright"] == [person("author", 111)]


def test_the_reply_lists_the_final_holders_in_a_code_block_and_names_no_module(repo, python310, tmp_path):
    api, _ = fork_via_license(repo, python310, tmp_path)
    reply = api.comments[2][0]
    lines = licensing.lines_of([person("author", 111), person(*SOMEONE)])
    assert "\n```\n" + "\n".join(lines) + "\n```\n" in reply
    assert "原版" not in reply and "跟「" not in reply and "一樣" not in reply


def test_a_fork_by_the_same_person_adds_nobody_twice(repo, python310, tmp_path):
    _, original = upload(repo, python310, tmp_path, 1, name="原版")
    upload(repo, python310, tmp_path, 2, LICENSE=original)
    assert entry_of(repo)["copyright"] == [person(*SOMEONE)]


def test_a_fork_of_a_fork_keeps_everyone_in_order(repo, python310, tmp_path):
    fork_via_license(repo, python310, tmp_path)
    second = (folder_of(repo) / "LICENSE").read_bytes()
    upload(repo, python310, tmp_path, 3, name="三代", login="third", user_id=333, LICENSE=second)
    assert entry_of(repo, "三代")["copyright"] == [person("author", 111), person(*SOMEONE), person("third", 333)]


def test_new_versions_never_lose_the_original_authors(repo, python310, tmp_path):
    fork_via_license(repo, python310, tmp_path)
    full = [person("author", 111), person(*SOMEONE)]
    expected = licensing.render(full).encode("utf-8")
    new = '"""說明"""\n# 第二版\n'
    upload(repo, python310, tmp_path, 3, iplot=new)  # 不附 LICENSE
    assert (folder_of(repo) / "LICENSE").read_bytes() == expected
    upload(repo, python310, tmp_path, 4, iplot=new + "# 3\n", LICENSE=expected)  # 附自己原本的那一份
    assert (folder_of(repo) / "LICENSE").read_bytes() == expected
    # 附一份只有自己的（機器人產生過的）：原作者還在，因為清單只增不刪
    _, mine = upload(repo, python310, tmp_path, 9, name="別的")
    assert mine == licensing.render([person(*SOMEONE)]).encode("utf-8")
    upload(repo, python310, tmp_path, 5, iplot=new + "# 4\n", LICENSE=mine)
    assert (folder_of(repo) / "LICENSE").read_bytes() == expected
    assert entry_of(repo)["copyright"] == full


@pytest.mark.parametrize("make", [
    lambda raw: raw.replace(b"@author", b"@somebody"),
    lambda raw: raw.replace(b"@author (GitHub user 111)\n", b"@author (GitHub user 111)\nCopyright (c) 2026 @x\n"),
    lambda raw: raw + b"\n",
    lambda raw: raw.replace(b"\n", b"\r\n"),
    lambda raw: b"\xef\xbb\xbf" + raw,
    lambda raw: raw.replace(b"2026", b"2019"),
    lambda raw: raw.replace(b"Permission is hereby", b"Permission is not"),
    lambda raw: b"",
    lambda raw: b"\xff\xfe",
])
def test_an_edited_license_is_refused_and_nothing_changes(repo, python310, tmp_path, make):
    _, original = upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    upload(repo, python310, tmp_path, 2)
    before = (folder_of(repo) / "LICENSE").read_bytes()
    refused(repo, python310, tmp_path, 3, UNKNOWN, LICENSE=make(original))
    assert (folder_of(repo) / "LICENSE").read_bytes() == before
    assert entry_of(repo)["version"] == "0.0.1"


@pytest.mark.parametrize("content", [
    "2026 This software is licensed under GPL-3.0-only; the text below does not apply.",
    "Copyright (c) 2026 x. NON-COMMERCIAL USE ONLY. Commercial use requires a paid license.",
    "0000 All rights reserved. No permission is granted, notwithstanding the text below.",
    "Copyright (c) 2026 ‮LPG rednu desneciL",
])
def test_a_header_line_cannot_carry_terms(repo, python310, tmp_path, content):
    refused(repo, python310, tmp_path, 1, UNKNOWN, LICENSE=f"MIT License\n\n{content}\n\n{BODY}")


def test_two_hundred_extra_header_lines_are_refused(repo, python310, tmp_path):
    extra = "".join(f"{2000 + i} clause {i}: you must pay the author 1 USD per copy.\n" for i in range(200))
    refused(repo, python310, tmp_path, 1, UNKNOWN, LICENSE="MIT License\n\n" + extra + "\n" + BODY)


def test_a_license_that_looks_like_the_workshops_but_was_never_generated_is_refused(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1)
    refused(repo, python310, tmp_path, 2, UNKNOWN, name="乙", LICENSE=licensing.render([person("made-up", 5)]))


def test_a_license_with_only_the_uploaders_own_line_is_also_refused_unless_generated(repo, python310, tmp_path):
    refused(repo, python310, tmp_path, 1, UNKNOWN, LICENSE=licensing.render([person(*SOMEONE)]))


def test_any_published_license_adds_its_holders(repo, python310, tmp_path):
    _, theirs = upload(repo, python310, tmp_path, 1, name="不相干", login="stranger", user_id=444)
    upload(repo, python310, tmp_path, 2, name="我的")
    upload(repo, python310, tmp_path, 3, name="我的", iplot='"""說明"""\n# 2\n', LICENSE=theirs)
    assert entry_of(repo, "我的")["copyright"] == [person(*SOMEONE), person("stranger", 444)]


def test_a_symlink_named_license_is_skipped_and_the_bot_writes_its_own(repo, python310, tmp_path):
    from conftest import make_zip

    z = make_zip(tmp_path / "s.zip", {"整理桌面/iplot.py": '"""說明"""\n'}, symlinks={"整理桌面/LICENSE": "/etc/passwd"})
    api = FakeApi([up(1)])
    run(repo, api, {att(1): z}, python310)
    assert (folder_of(repo) / "LICENSE").read_bytes() == licensing.render([person(*SOMEONE)]).encode()


# --- 標準授權檔名：只擋最上層 ----------------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "COPYING", "copying", "COPYING.txt", "COPYING.LESSER", "COPYING-3.0", "LICENCE", "Licence.md", "licence.txt",
    "LICENCE-MIT", "COPYRIGHT", "COPYRIGHT.txt", "Copyright.md", "copyright-notes", "UNLICENSE", "unlicense.txt",
    "UNLICENSE-2", "LICENSE-MIT", "LICENSE-APACHE", "LICENSE.GPL", "LICENSE.docx", "license.md.bak",
    "ＬＩＣＥＮＳＥ", "Ｌicense.txt", "ＣＯＰＹＩＮＧ", "ＬＩＣＥＮＳＥ.md",  # NFKC 之後是標準名字
])
def test_standard_license_names_at_the_top_level_are_refused(repo, python310, tmp_path, path):
    refused(repo, python310, tmp_path, 1, like(path), **{path: "x"})


@pytest.mark.parametrize("path, shown", [
    ("COPYING/a.txt", "COPYING"), ("licence/MIT.txt", "licence"), ("copyright-notes/a.md", "copyright-notes"),
    ("LICENSE/a.txt", "LICENSE"), ("license/a.txt", "license"), ("LICENSE.md/a.txt", "LICENSE.md"),
])
def test_a_top_level_folder_with_a_standard_name_is_refused_too(repo, python310, tmp_path, path, shown):
    api = refused(repo, python310, tmp_path, 1, like(shown), **{path: "x"})
    assert "壞了" not in api.comments[1][0]


def test_the_refusal_tells_the_uploader_what_to_remove():
    assert "拿掉 `COPYING` 再傳" in like("COPYING")


def test_a_standard_name_is_refused_even_next_to_a_good_license(repo, python310, tmp_path):
    _, original = upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    refused(repo, python310, tmp_path, 2, like("COPYING"), LICENSE=original, COPYING="GPL")


@pytest.mark.parametrize("names", [("LICENSE", "LICENSE.txt"), ("LICENSE", "LICENSE.md"),
                                   ("LICENSE.md", "LICENSE.txt"), ("LICENSE", "license")])
def test_two_top_level_licenses_are_refused(repo, python310, tmp_path, names):
    _, original = upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    # 兩個名字只差大小寫的 zip 會先因為「只差大小寫」被擋成 bad_path；其他的是這一句
    api = FakeApi([up(2)])
    run(repo, api, {att(2): module_zip(tmp_path, **{n: original for n in names})}, python310)
    expected = {like(sorted(names)[1]), refuse("bad_path", path=f"整理桌面/{names[1]}").text}
    assert api.comments[2][0] in expected and api.patches == [(2, REFUSED)]
    assert not folder_of(repo).exists()


@pytest.mark.parametrize("filename", ["LICENSE", "LICENSE.md", "LICENSE.txt", "license", "License.TXT"])
def test_the_one_generated_license_in_any_of_the_three_names_is_fine(repo, python310, tmp_path, filename):
    _, original = upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    upload(repo, python310, tmp_path, 2, **{filename: original})
    assert entry_of(repo)["copyright"] == [person("author", 111), person(*SOMEONE)]


def test_the_module_name_itself_is_not_checked(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1, name="notice")
    upload(repo, python310, tmp_path, 2, name="GPL計算")


@pytest.mark.parametrize("char", ["​", "‌", "‍", "‎", "‏", "‪", "‮", "⁦",
                                  "⁩", "﻿", "­", "⁠"])
@pytest.mark.parametrize("make", ["LICENSE{c}", "a{c}b.py", "資料{c}/a.txt", "{c}LICENSE.md"])
def test_format_characters_anywhere_in_a_path_are_refused(repo, python310, tmp_path, char, make):
    path = make.format(c=char)
    refused(repo, python310, tmp_path, 1, refuse("bad_path", path=f"整理桌面/{path}").text, **{path: "x"})


def test_format_characters_are_refused_by_bad_path_itself():
    from zipcheck import bad_path

    assert bad_path("m/a​b") and bad_path("m/‮LICENSE") and bad_path("⁦m/a")
    assert not bad_path("m/a b.py") and not bad_path("m/資料/說明.txt")


def test_standard_license_name_unit():
    f = licensing.standard_license_name
    assert f(["iplot.py", "LICENSE", "LICENSE.md"]) == "LICENSE.md"      # 兩個
    assert f(["iplot.py", "LICENSE"]) is None and f(["iplot.py", "license.TXT"]) is None
    assert f(["iplot.py", "a/COPYING", "a/b/LICENCE.txt", "a/licenses/MIT.txt"]) is None  # 只看最上層
    assert f(["iplot.py", "gplot.py", "notice_board.py", "ggplot.mplstyle", "licenses.json"]) is None
    assert f(["iplot.py", "LICENSES/MIT.txt", "license_check.py", "licensee.py"]) is None
    assert f(["iplot.py", "ＮＯＴＩＣＥ", "Ｇｐｌ.txt"]) is None          # 不是標準名字
    assert f(["iplot.py", "ＣＯＰＹＩＮＧ"]) == "ＣＯＰＹＩＮＧ"
    assert not licensing.is_license_file("ＬＩＣＥＮＳＥ") and not licensing.is_license_file("a/LICENSE")


# --- 刻意不管的名字：照收，repo 裡的 LICENSE 仍是機器人產生的 -----------------------------------------------------

GPL = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n"


@pytest.mark.parametrize("path", [
    "LİCENSE", "LІCENSE", "LICΕNSE", "LIĆENSE", "LICEɴSE",            # 同形字
    "AUTHORS", "LEGAL.txt", "MIT.txt", "Apache-2.0.txt", "NOTICE", "EULA.txt", "GPL-3.0.txt", "LICENSE_GPL",
    "LICENSES/MIT.txt", "COPYRIGHT_NOTES.txt",                        # 不是「標準名字加 . 或 -」
    "LIZENZ", "授權條款.txt", "著作權", "ライセンス",                      # 別的語言
    "vendor/LİCENSE", "vendor/COPYING", "資料/LICENSE", "vendor/foo/LICENSE.txt", "a/b/NOTICE.md",  # 子資料夾
    "gplot.py", "notice_board.py", "ggplot.mplstyle", "license_check.py", "licensee.py", "eula.py", "gpl.py",
])
def test_names_the_bot_does_not_look_at_are_received_and_the_license_is_still_generated(repo, python310, tmp_path,
                                                                                         path):
    upload(repo, python310, tmp_path, 1, **{path: GPL})
    stored = folder_of(repo) / path
    assert stored.read_text(encoding="utf-8") == GPL
    assert (folder_of(repo) / "LICENSE").read_bytes() == licensing.render([person(*SOMEONE)]).encode("utf-8")
    assert entry_of(repo)["copyright"] == [person(*SOMEONE)] and entry_of(repo)["license"] == "MIT"


# --- licensing 本身 ------------------------------------------------------------------------------------------

def test_there_is_no_license_text_parser_left():
    for gone in ("review", "is_mit", "COPYRIGHT_RE", "_normalized", "license_text", "MAX_LICENSE", "TITLE_RE",
                 "LOOKALIKE_WORDS", "lookalike", "earliest_user", "REMARK_KEPT", "REMARK_ADDED"):
        assert not hasattr(licensing, gone), gone


def test_the_workshop_url_is_the_one_build_uses():
    assert licensing.WORKSHOP_URL == build.BASE_URL + "/" and licensing.ORIGIN_DIR == build.MODULES


def test_the_repo_license_is_the_generated_format():
    raw = (ROOT / "LICENSE").read_bytes()
    assert raw == licensing.render([[2026, RA, RA_ID]]).encode("utf-8")


# --- registry、遷移 -------------------------------------------------------------------------------------------

def test_new_upload_is_recorded_as_mit_with_its_issue(repo, python310, tmp_path):
    api = FakeApi([up(7, body=form_body(att(7)))])
    assert run(repo, api, {att(7): module_zip(tmp_path)}, python310) == 0
    entry = entry_of(repo)
    assert (entry["license"], entry["license_issue"]) == ("MIT", 7)


def test_update_keeps_other_fields(repo, python310, tmp_path):
    old = {"name": "整理桌面", "owner_id": 222, "owner": "someone", "version": "0.0.1", "notes": "", "issue": 3,
           "updated": "2026-10-01", "license": "MIT", "license_issue": 3, "copyright": [person("someone", 222, 2025)],
           "warning": "手動的", "unknown": [1]}
    seed(repo, {registry.key("整理桌面"): old})
    upload(repo, python310, tmp_path, 8)
    entry = entry_of(repo)
    assert entry["version"] == "0.0.2" and entry["issue"] == 8
    assert (entry["license"], entry["license_issue"]) == ("MIT", 8)
    assert entry["copyright"] == [person("someone", 222, 2025)]
    assert entry["warning"] == "手動的" and entry["unknown"] == [1]
    assert "Copyright (c) 2025 @someone (GitHub user 222)" in (folder_of(repo) / "LICENSE").read_text(encoding="utf-8")


def test_licenses_json_must_be_readable_before_anything_is_received(repo, python310, tmp_path, capsys):
    (repo / "licenses.json").write_text('{"a": 1, "a": 2}', encoding="utf-8")
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 1
    assert "licenses.json" in capsys.readouterr().err and api.comments == {}


SEEDS = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
OLD_HASH = "aeed872b5d5403c775876f5459a2c7705e9ceb4e575fba6286c2d0e40d7b48a0"  # 遷移前就在 licenses.json 的那一個


def test_migrated_seeds_have_three_field_copyright_license_files_and_hashes():
    licenses = json.loads((ROOT / "licenses.json").read_text(encoding="utf-8"))
    with_license = {k: e for k, e in SEEDS.items() if "license" in e}
    assert len(with_license) == 10
    for k, entry in with_license.items():
        assert entry["copyright"] == [[2026, RA, RA_ID]], k
        licensing.render(entry["copyright"])  # 合格
        assert licenses[licensing.digest(entry["copyright"])] == entry["copyright"]
        folder = ROOT / "modules" / entry["name"]
        if folder.exists():
            raw = (folder / "LICENSE").read_bytes()
            assert raw == licensing.render(entry["copyright"]).encode("utf-8"), k
            assert hashlib_sha(raw) in licenses
    assert len(list((ROOT / "modules").glob("*/LICENSE"))) == 6


def test_the_old_hash_is_kept_so_a_fork_with_the_old_license_is_still_known():
    licenses = json.loads((ROOT / "licenses.json").read_text(encoding="utf-8"))
    assert licenses[OLD_HASH] == [[2026, RA, RA_ID]]
    assert licensing.digest(licenses[OLD_HASH]) == OLD_HASH  # 研究助理的顯示名沒變，LICENSE 的位元組一樣，所以新舊雜湊是同一個
    assert list(licenses) == [OLD_HASH]


def test_every_entry_in_licenses_json_and_registry_json_is_valid():
    for cp in json.loads((ROOT / "licenses.json").read_text(encoding="utf-8")).values():
        licensing.validate(cp)
    for entry in SEEDS.values():
        if "copyright" in entry:
            licensing.validate(entry["copyright"])


def test_modules_without_a_license_are_left_alone():
    for name in ("車車", "同事測試"):
        entry = SEEDS[registry.key(name)]
        assert "copyright" not in entry and "license" not in entry
    assert not (ROOT / "modules" / "車車" / "LICENSE").exists()
    for k, entry in SEEDS.items():
        assert ("copyright" in entry) == ("license" in entry), k


def test_no_module_in_the_repo_has_a_standard_license_name_besides_license():
    for folder in (ROOT / "modules").iterdir():
        paths = [p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()]
        assert licensing.standard_license_name(paths) is None, folder.name


@pytest.mark.parametrize("stuck_n, other_n", [(2, 3), (3, 2)], ids=["stuck-first", "stuck-last"])
def test_a_stuck_upload_does_not_stop_the_others_in_the_same_run(repo, python310, tmp_path, stuck_n, other_n):
    """版權人清單壞掉（BadCopyright）的那一份卡住；同一輪裡別人的上傳照樣收進去，不整輪停下來。"""
    upload(repo, python310, tmp_path, 1)
    data = registry.read_json_strict(repo / "registry.json")
    data[registry.key("整理桌面")]["copyright"] = [[2026, "@someone (GitHub user 222)"]]
    seed(repo, data)
    api = FakeApi([up(stuck_n), up(other_n, login="other", user_id=333, body=form_body(att(other_n)))])
    zips = {att(stuck_n): module_zip(tmp_path, iplot='"""說明"""\n# 新的一版\n'),
            att(other_n): module_zip(tmp_path, "別的")}
    assert run(repo, api, zips, python310) == 0
    assert api.comments[stuck_n] == [SAY["stuck"]]
    assert api.patches.count((stuck_n, {"labels": ["卡住"]})) == 1
    assert (other_n, PUBLISHED) in api.patches
    assert str(stuck_n) not in received(repo) and str(other_n) in received(repo)
    assert folder_of(repo, "別的").is_dir()
    assert entry_of(repo, "別的")["copyright"] == [person("other", 333)]
    assert git(repo, "status", "--porcelain") == ""
