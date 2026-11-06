"""上傳一律以 MIT 授權公開：表單那一格、版權人（registry 的 copyright）、機器人產生的 LICENSE（licenses.json 記雜湊）、
像授權的檔不收。機器人不解讀上傳者寫的授權文字。"""

import json
from pathlib import Path

import gh
import licensing
import pytest
import registry
from conftest import FakeApi, form_body
from say import SAY, code, refuse
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


# --- 版權人在 registry、LICENSE 由機器人產生 ----------------------------------------------------------

RA_ID = 71483597
RA = "Wei-Heng Chien (簡偉恆)"
YEAR = NOW.year
BODY = licensing.MIT_BODY
ROOT = Path(__file__).resolve().parents[1]


def entry_of(repo, name="整理桌面"):
    return registry.read_json_strict(repo / "registry.json")[registry.key(name)]


def licenses_of(repo):
    return registry.read_json_strict(repo / "licenses.json")


def upload(repo, python310, tmp_path, n, *, name="整理桌面", login="someone", user_id=222, iplot=None, **extra):
    """傳一份、收到了；回 (api, 這個模組的 LICENSE 位元組)。"""
    api = FakeApi([up(n, login=login, user_id=user_id)])
    kwargs = {} if iplot is None else {"iplot": iplot}
    assert run(repo, api, {att(n): module_zip(tmp_path, name, **kwargs, **extra)}, python310) == 0
    assert api.patches == [(n, PUBLISHED)], api.comments
    return api, (folder_of(repo, name) / "LICENSE").read_bytes()


def refused(repo, python310, tmp_path, n, text, *, name="整理桌面", login="someone", user_id=222, **extra):
    """傳一份、被拒收，回覆是 text；modules/ 裡沒有、received 裡沒有，licenses.json 沒有變。"""
    before = (repo / "licenses.json").read_bytes(), (repo / "registry.json").read_bytes()
    existed = folder_of(repo, name).exists()
    api = FakeApi([up(n, login=login, user_id=user_id)])
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


def test_missing_license_is_generated_with_the_uploader(repo, python310, tmp_path):
    api, raw = upload(repo, python310, tmp_path, 1)
    assert raw == licensing.render([[YEAR, "@someone"]]).encode("utf-8")
    assert raw.decode("utf-8").startswith(f"MIT License\n\nCopyright (c) {YEAR} @someone\n\nPermission is hereby")
    assert entry_of(repo)["copyright"] == [[YEAR, "@someone"]]
    assert licensing.REMARK_ADDED in api.comments[1][0]


def test_research_assistant_is_known_by_account_id_not_login(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1, login="whoever", user_id=RA_ID)
    assert entry_of(repo)["copyright"] == [[YEAR, RA]]
    assert "@whoever" not in (folder_of(repo) / "LICENSE").read_text(encoding="utf-8")


def test_same_login_but_another_id_is_an_ordinary_uploader(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1, login="william10310406", user_id=999)
    text = (folder_of(repo) / "LICENSE").read_text(encoding="utf-8")
    assert f"Copyright (c) {YEAR} @william10310406" in text and "簡偉恆" not in text


def test_the_same_list_always_makes_the_same_bytes():
    cp = [[2025, "@a"], [2026, RA]]
    assert licensing.render(cp) == licensing.render([list(x) for x in cp])
    assert licensing.digest(cp) == licensing.digest(tuple(tuple(x) for x in cp))
    assert licensing.render(cp) == f"MIT License\n\nCopyright (c) 2025 @a\nCopyright (c) 2026 {RA}\n\n{BODY}"
    assert licensing.digest(cp) != licensing.digest(cp[::-1])


def test_two_modules_with_the_same_list_have_identical_license_files(repo, python310, tmp_path):
    _, first = upload(repo, python310, tmp_path, 1, name="甲")
    _, second = upload(repo, python310, tmp_path, 2, name="乙")
    assert first == second
    assert list(licenses_of(repo)) == [licensing.digest([[YEAR, "@someone"]])]


def test_every_generated_license_is_recorded_by_its_hash(repo, python310, tmp_path):
    _, raw = upload(repo, python310, tmp_path, 1)
    assert licenses_of(repo) == {hashlib_sha(raw): [[YEAR, "@someone"]]}
    assert hashlib_sha(raw) == licensing.digest([[YEAR, "@someone"]])
    stat = git(repo, "show", "--stat", "--format=", "HEAD")
    assert "licenses.json" in stat and "registry.json" in stat


def hashlib_sha(raw: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def test_the_uploaded_license_is_never_what_gets_stored(repo, python310, tmp_path):
    _, generated = upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    for n, filename in ((2, "LICENSE"), (3, "LICENSE.md"), (4, "LICENSE.txt"), (5, "license")):
        _, raw = upload(repo, python310, tmp_path, n, name=f"改{n}", **{filename: generated})
        assert sorted(p.name for p in folder_of(repo, f"改{n}").iterdir()) == ["LICENSE", "iplot.py"]
        assert raw.decode("utf-8").count("Copyright (c)") == 2


def test_update_without_license_keeps_the_list_and_adds_nobody(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1)
    upload(repo, python310, tmp_path, 2, iplot='"""說明"""\n# 改了一點\n')
    assert entry_of(repo)["copyright"] == [[YEAR, "@someone"]]
    assert entry_of(repo)["version"] == "0.0.2"
    assert licenses_of(repo) == {licensing.digest([[YEAR, "@someone"]]): [[YEAR, "@someone"]]}


def test_a_seed_without_copyright_gets_the_uploader(repo, python310, tmp_path):
    seed(repo, {registry.key("整理桌面"): {"name": "整理桌面", "owner_id": 222, "owner": "someone",
                                         "version": "0.0.1", "notes": "", "issue": 3, "updated": "2026-10-01"}})
    upload(repo, python310, tmp_path, 8)
    entry = entry_of(repo)
    assert entry["copyright"] == [[YEAR, "@someone"]] and entry["license"] == "MIT"


# --- 改別人的模組（fork）：LICENSE 用雜湊認 -------------------------------------------------------------

def fork_of(repo, python310, tmp_path, n=2, **extra):
    """author 上傳「原版」，someone 改了它的 LICENSE 原樣放進「整理桌面」再傳。回 (api, 原版的 LICENSE)。"""
    _, original = upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    api, _ = upload(repo, python310, tmp_path, n, LICENSE=original, **extra)
    return api, original


def test_a_fork_keeps_the_original_authors_and_adds_the_uploader(repo, python310, tmp_path):
    api, original = fork_of(repo, python310, tmp_path)
    expected = [[YEAR, "@author"], [YEAR, "@someone"]]
    assert entry_of(repo)["copyright"] == expected
    assert (folder_of(repo) / "LICENSE").read_bytes() == licensing.render(expected).encode("utf-8")
    assert licensing.REMARK_KEPT.format(name=code("原版")) in api.comments[2][0]
    assert licenses_of(repo)[licensing.digest(expected)] == expected
    assert (folder_of(repo, "原版") / "LICENSE").read_bytes() == original
    assert entry_of(repo, "原版")["copyright"] == [[YEAR, "@author"]]


def test_the_reply_names_the_earliest_module_that_uses_that_license(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1, name="先", login="author", user_id=111)
    _, same = upload(repo, python310, tmp_path, 2, name="後", login="author", user_id=111)
    api, _ = upload(repo, python310, tmp_path, 3, LICENSE=same)
    assert licensing.REMARK_KEPT.format(name=code("先")) in api.comments[3][0]


def test_a_fork_by_the_same_person_adds_nobody_twice(repo, python310, tmp_path):
    _, original = upload(repo, python310, tmp_path, 1, name="原版")
    upload(repo, python310, tmp_path, 2, LICENSE=original)
    assert entry_of(repo)["copyright"] == [[YEAR, "@someone"]]


def test_a_fork_of_a_fork_keeps_everyone_in_order(repo, python310, tmp_path):
    fork_of(repo, python310, tmp_path)
    second = (folder_of(repo) / "LICENSE").read_bytes()
    upload(repo, python310, tmp_path, 3, name="三代", login="third", user_id=333, LICENSE=second)
    assert entry_of(repo, "三代")["copyright"] == [[YEAR, "@author"], [YEAR, "@someone"], [YEAR, "@third"]]


def test_new_versions_never_lose_the_original_authors(repo, python310, tmp_path):
    fork_of(repo, python310, tmp_path)
    full = [[YEAR, "@author"], [YEAR, "@someone"]]
    expected = licensing.render(full).encode("utf-8")
    new = '"""說明"""\n# 第二版\n'
    # 不附 LICENSE
    upload(repo, python310, tmp_path, 3, iplot=new)
    assert (folder_of(repo) / "LICENSE").read_bytes() == expected
    # 附自己原本的那一份
    upload(repo, python310, tmp_path, 4, iplot=new + "# 3\n", LICENSE=expected)
    assert (folder_of(repo) / "LICENSE").read_bytes() == expected
    # 附一份只有自己的（機器人產生過的）：原作者還在，因為清單只增不刪
    _, mine = upload(repo, python310, tmp_path, 9, name="別的")
    assert mine == licensing.render([[YEAR, "@someone"]]).encode("utf-8")
    upload(repo, python310, tmp_path, 5, iplot=new + "# 4\n", LICENSE=mine)
    assert (folder_of(repo) / "LICENSE").read_bytes() == expected
    assert entry_of(repo)["copyright"] == full


@pytest.mark.parametrize("make", [
    lambda raw: raw.replace(b"@author", b"@somebody"),           # 換掉原作者的名字
    lambda raw: raw.replace(b"@author\n", b"@author\nCopyright (c) 2026 @x\n"),  # 多一行
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
    "1999 Additional terms: you may not use this software to train AI models.",
    "0000 All rights reserved. No permission is granted, notwithstanding the text below.",
    "Copyright (c) 2026 \u202eLPG rednu desneciL",
])
def test_a_header_line_cannot_carry_terms(repo, python310, tmp_path, content):
    text = f"MIT License\n\n{content}\n\n{BODY}"
    refused(repo, python310, tmp_path, 1, UNKNOWN, LICENSE=text)


def test_two_hundred_extra_header_lines_are_refused(repo, python310, tmp_path):
    extra = "".join(f"{2000 + i} clause {i}: you must pay the author 1 USD per copy.\n" for i in range(200))
    refused(repo, python310, tmp_path, 1, UNKNOWN, LICENSE="MIT License\n\n" + extra + "\n" + BODY)


def test_a_license_that_looks_like_the_workshops_but_was_never_generated_is_refused(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1)
    refused(repo, python310, tmp_path, 2, UNKNOWN, name="乙", LICENSE=licensing.render([[YEAR, "@made-up"]]))


def test_a_license_with_only_the_uploaders_own_line_is_also_refused_unless_generated(repo, python310, tmp_path):
    refused(repo, python310, tmp_path, 1, UNKNOWN, LICENSE=licensing.render([[YEAR, "@someone"]]))


# --- 像授權的檔 ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path, shown", [
    ("LICENSE_GPL", "LICENSE_GPL"),
    ("LICENSES/GPL-3.0-only.txt", "LICENSES"),
    ("GPL-3.0.txt", "GPL-3.0.txt"),
    ("NOTICE", "NOTICE"),
    ("EULA.txt", "EULA.txt"),
    ("ＬＩＣＥＮＳＥ", "ＬＩＣＥＮＳＥ"),
    ("Ｌicense.txt", "Ｌicense.txt"),
    ("COPYING", "COPYING"),
    ("COPYING.LESSER", "COPYING.LESSER"),
    ("LICENCE", "LICENCE"),
    ("UNLICENSE", "UNLICENSE"),
    ("unlicense.txt", "unlicense.txt"),
    ("LICENSE-MIT", "LICENSE-MIT"),
    ("LICENSE.GPL", "LICENSE.GPL"),
    ("licenses/MIT.txt", "licenses"),
    ("資料/LICENSE", "資料/LICENSE"),
    ("資料/COPYING", "資料/COPYING"),
    ("資料/third_party/NOTICE.md", "資料/third_party/NOTICE.md"),
    ("vendor/foo/LICENSE.txt", "vendor/foo/LICENSE.txt"),
    ("gpl.py", "gpl.py"),
    ("說明/Eula 條款.txt", "說明/Eula 條款.txt"),
])
def test_files_that_look_like_licenses_are_refused(repo, python310, tmp_path, path, shown):
    refused(repo, python310, tmp_path, 1, like(shown), **{path: "x"})


def test_a_lookalike_is_refused_even_next_to_a_good_license(repo, python310, tmp_path):
    _, original = upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    refused(repo, python310, tmp_path, 2, like("COPYING"), LICENSE=original, COPYING="GPL")


def test_a_folder_named_license_gets_the_lookalike_sentence_not_a_broken_zip(repo, python310, tmp_path):
    api = refused(repo, python310, tmp_path, 1, like("LICENSE"), **{"LICENSE/a.txt": "x"})
    assert "壞了" not in api.comments[1][0]


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
    assert entry_of(repo)["copyright"] == [[YEAR, "@author"], [YEAR, "@someone"]]


def test_the_module_name_itself_is_not_checked_for_lookalike_words(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1, name="notice")


@pytest.mark.parametrize("char", ["\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u202a", "\u202e", "\u2066",
                                  "\u2069", "\ufeff", "\u00ad", "\u2060"])
@pytest.mark.parametrize("make", ["LICENSE{c}", "a{c}b.py", "資料{c}/a.txt", "{c}LICENSE.md"])
def test_format_characters_anywhere_in_a_path_are_refused(repo, python310, tmp_path, char, make):
    path = make.format(c=char)
    refused(repo, python310, tmp_path, 1, refuse("bad_path", path=f"整理桌面/{path}").text, **{path: "x"})


def test_format_characters_are_refused_by_bad_path_itself():
    from zipcheck import bad_path

    assert bad_path("m/a\u200bb") and bad_path("m/\u202eLICENSE") and bad_path("\u2066m/a")
    assert not bad_path("m/a b.py") and not bad_path("m/資料/說明.txt")


# --- licensing 本身 ------------------------------------------------------------------------------------------

def test_merge_keeps_order_adds_only_new_holders_and_never_removes():
    base = [[2025, "@a"], [2026, "@b"]]
    assert licensing.merge(base, [[2030, "@B"], [2027, "@c"]]) == [[2025, "@a"], [2026, "@b"], [2027, "@c"]]
    assert licensing.merge([], [[2027, "@c"]]) == [[2027, "@c"]]
    assert licensing.merge(base, []) == base and base == [[2025, "@a"], [2026, "@b"]]


def test_lookalike_words_are_compared_after_nfkc_and_casefold():
    assert licensing.lookalike(["iplot.py", "ＮＯＴＩＣＥ"]) == "ＮＯＴＩＣＥ"
    assert licensing.lookalike(["iplot.py", "LICENSE"]) is None
    assert licensing.lookalike(["iplot.py", "a/b/Ｇｐｌ.txt"]) == "a/b/Ｇｐｌ.txt"
    assert licensing.lookalike(["iplot.py", "ＬＩＣＥＮＳＥ"]) == "ＬＩＣＥＮＳＥ"  # 全形的不算那個 LICENSE


def test_there_is_no_license_text_parser_left():
    for gone in ("review", "is_mit", "COPYRIGHT_RE", "_normalized", "license_text", "MAX_LICENSE", "TITLE_RE"):
        assert not hasattr(licensing, gone), gone


def test_the_repo_license_is_the_generated_format():
    raw = (ROOT / "LICENSE").read_bytes()
    assert raw == licensing.render([[2026, RA]]).encode("utf-8")


# --- registry、遷移 -------------------------------------------------------------------------------------------

def test_new_upload_is_recorded_as_mit_with_its_issue(repo, python310, tmp_path):
    api = FakeApi([up(7, body=form_body(att(7)))])
    assert run(repo, api, {att(7): module_zip(tmp_path)}, python310) == 0
    entry = entry_of(repo)
    assert (entry["license"], entry["license_issue"]) == ("MIT", 7)


def test_update_keeps_other_fields(repo, python310, tmp_path):
    old = {"name": "整理桌面", "owner_id": 222, "owner": "someone", "version": "0.0.1", "notes": "", "issue": 3,
           "updated": "2026-10-01", "license": "MIT", "license_issue": 3, "copyright": [[2025, "@someone"]],
           "warning": "手動的", "unknown": [1]}
    seed(repo, {registry.key("整理桌面"): old})
    upload(repo, python310, tmp_path, 8)
    entry = entry_of(repo)
    assert entry["version"] == "0.0.2" and entry["issue"] == 8
    assert (entry["license"], entry["license_issue"]) == ("MIT", 8)
    assert entry["copyright"] == [[2025, "@someone"]]
    assert entry["warning"] == "手動的" and entry["unknown"] == [1]
    assert "Copyright (c) 2025 @someone" in (folder_of(repo) / "LICENSE").read_text(encoding="utf-8")


def test_licenses_json_must_be_readable_before_anything_is_received(repo, python310, tmp_path, capsys):
    (repo / "licenses.json").write_text('{"a": 1, "a": 2}', encoding="utf-8")
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 1
    assert "licenses.json" in capsys.readouterr().err and api.comments == {}


SEEDS = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))


def test_migrated_seeds_have_copyright_license_files_and_hashes():
    licenses = json.loads((ROOT / "licenses.json").read_text(encoding="utf-8"))
    with_license = {k: e for k, e in SEEDS.items() if "license" in e}
    assert len(with_license) == 10
    for k, entry in with_license.items():
        assert entry["copyright"] == [[2026, RA]], k
        assert licenses[licensing.digest(entry["copyright"])] == entry["copyright"]
        folder = ROOT / "modules" / entry["name"]
        if folder.exists():
            raw = (folder / "LICENSE").read_bytes()
            assert raw == licensing.render(entry["copyright"]).encode("utf-8"), k
            assert hashlib_sha(raw) in licenses
    assert len(list((ROOT / "modules").glob("*/LICENSE"))) == 6
    assert len(licenses) == 1


def test_modules_without_a_license_are_left_alone():
    for name in ("車車", "同事測試"):
        entry = SEEDS[registry.key(name)]
        assert "copyright" not in entry and "license" not in entry
    assert not (ROOT / "modules" / "車車" / "LICENSE").exists()
    for k, entry in SEEDS.items():
        assert ("copyright" in entry) == ("license" in entry), k


def test_no_module_in_the_repo_has_a_lookalike_file_besides_license():
    for folder in (ROOT / "modules").iterdir():
        paths = [p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()]
        assert licensing.lookalike(paths) is None, folder.name
