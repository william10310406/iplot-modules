"""改別人的模組再上傳：原作者從 .origin、表單的 fork_of、zip 裡的 LICENSE 併進來（用帳號 id 去重）。"""

import json
import unicodedata

import build
import licensing
import pytest
import registry
import zipcheck
from conftest import FakeApi, form_body, make_zip
from iplot_rules import url as site_url
from say import SAY, refuse
from test_license import (
    AUTHOR,
    REFUSED,
    SOMEONE,
    entry_of,
    folder_of,
    licenses_of,
    person,
    refused,
    upload,
)
from test_receive import att, git, module_zip, received, run, seed, up


def origin_of(name, **fields):
    """工作坊真的會寫的 .origin：一行一個「key: value」，網址是 iplot_rules.url 寫出來的（中文寫成 %XX）。"""
    data = {"url": site_url(build.BASE_URL, build.MODULES, f"{name}.zip"), "version": "0.0.1",
            "sha256": "0" * 64, "digest": "1" * 64, "files": "iplot.py", **fields}
    return "".join(f"{key}: {value}\n" for key, value in data.items()).encode("utf-8")


def stage_original(repo, python310, tmp_path, name="原版", who=AUTHOR, n=1):
    return upload(repo, python310, tmp_path, n, name=name, login=who[0], user_id=who[1])


# --- .origin ----------------------------------------------------------------------------------------------

def test_a_fork_with_origin_and_without_license_keeps_the_original_author(repo, python310, tmp_path):
    stage_original(repo, python310, tmp_path)
    api, raw = upload(repo, python310, tmp_path, 2, **{".origin": origin_of("原版")})
    expected = [person(*AUTHOR), person(*SOMEONE)]
    assert entry_of(repo)["copyright"] == expected
    assert raw == licensing.render(expected).encode("utf-8")
    assert "@author (GitHub user 111)" in api.comments[2][0]
    assert not (folder_of(repo) / ".origin").exists()  # .origin 不寫進 repo
    assert ".origin" in api.comments[2][0]              # 照舊列在略過的檔裡


def test_origin_is_read_even_though_it_is_skipped(repo, python310, tmp_path):
    stage_original(repo, python310, tmp_path)
    upload(repo, python310, tmp_path, 2, **{".origin": origin_of("原版")})
    assert sorted(p.name for p in folder_of(repo).iterdir()) == ["LICENSE", "iplot.py"]


def test_the_json_form_is_read_too(repo, python310, tmp_path):
    stage_original(repo, python310, tmp_path)
    url = site_url(build.BASE_URL, build.MODULES, "原版.zip")
    upload(repo, python310, tmp_path, 2, **{".origin": json.dumps({"url": url, "version": "0.0.1"})})
    assert entry_of(repo)["copyright"] == [person(*AUTHOR), person(*SOMEONE)]


def test_an_unquoted_url_and_a_capitalised_file_name_work(repo, python310, tmp_path):
    stage_original(repo, python310, tmp_path, name="Guide")
    raw = f"url: {build.BASE_URL}/模組/Guide.zip\n".encode()
    upload(repo, python310, tmp_path, 2, **{".Origin": raw})
    assert entry_of(repo)["copyright"] == [person(*AUTHOR), person(*SOMEONE)]


def test_the_name_in_the_url_is_looked_up_like_a_registry_key(repo, python310, tmp_path):
    stage_original(repo, python310, tmp_path, name="Guide")
    upload(repo, python310, tmp_path, 2, **{".origin": origin_of("GUIDE")})
    assert entry_of(repo)["copyright"] == [person(*AUTHOR), person(*SOMEONE)]


def test_the_workshop_writes_the_format_this_reads(iplot_next_door, tmp_path):
    """對著隔壁 iPLoT 的 workshop.write_origin：它寫出來的 .origin，這裡讀得出網址與名稱。"""
    from conftest import load_iplot

    workshop = load_iplot("modules/工作坊/workshop.py", "iplot_workshop_probe")
    folder = tmp_path / "m"
    folder.mkdir()
    url = site_url(build.BASE_URL, build.MODULES, "整理 桌面.zip")
    workshop.write_origin(folder, {"url": url, "version": "1", "sha256": "a", "digest": "b", "files": "iplot.py"})
    raw = (folder / ".origin").read_bytes()
    assert licensing.origin_url(raw) == url and licensing.origin_name(url) == "整理 桌面"


@pytest.mark.parametrize("raw", [
    b"", b"\xff\xfe\x00", b"hello", b"{", b"[]", b'"url"', b'{"url": 5}', b'{"url": null}', b"url:", b"url: ",
    b"url:https://william10310406.github.io/iplot-modules/%E6%A8%A1%E7%B5%84/%E5%8E%9F%E7%89%88.zip\n",  # 沒有空白
    b"URL: https://william10310406.github.io/iplot-modules/%E6%A8%A1%E7%B5%84/%E5%8E%9F%E7%89%88.zip\n",
    b"x" * (licensing.MAX_ORIGIN + 1),
    # 網址不在工作坊
    "url: https://evil.example/iplot-modules/模組/原版.zip\n".encode(),
    "url: http://william10310406.github.io/iplot-modules/模組/原版.zip\n".encode(),
    "url: https://william10310406.github.io.evil.example/iplot-modules/模組/原版.zip\n".encode(),
    "url: https://william10310406.github.io:8443/iplot-modules/模組/原版.zip\n".encode(),
    "url: https://user@william10310406.github.io/iplot-modules/模組/原版.zip\n".encode(),
    "url: https://william10310406.github.io/other/模組/原版.zip\n".encode(),
    "url: https://william10310406.github.io/iplot-modules/原版.zip\n".encode(),
    "url: https://william10310406.github.io/iplot-modules/模組/原版.tar\n".encode(),
    "url: https://william10310406.github.io/iplot-modules/模組/原版.zip?x=1\n".encode(),
    "url: https://william10310406.github.io/iplot-modules/模組/原版.zip#x\n".encode(),
    "url: https://william10310406.github.io/iplot-modules/模組/甲/原版.zip\n".encode(),
    "url: https://william10310406.github.io/iplot-modules/模組/.zip\n".encode(),
    "url: file:///Users/x/iplot-modules/模組/原版.zip\n".encode(),
    "url: https://william10310406.github.io/iplot-modules/模組/不存在.zip\n".encode(),  # 名稱找不到
    b"url: https://william10310406.github.io/iplot-modules/%E6%A8%A1%E7%B5%84/%FF.zip\n",  # 壞的 %XX
])
def test_an_origin_that_is_unreadable_or_points_elsewhere_is_ignored_and_the_upload_is_received(
        repo, python310, tmp_path, raw):
    stage_original(repo, python310, tmp_path)
    api, _ = upload(repo, python310, tmp_path, 2, **{".origin": raw})
    assert entry_of(repo)["copyright"] == [person(*SOMEONE)]
    assert api.comments[2][0].startswith("收到了")


def test_an_origin_in_a_subfolder_or_a_symlink_is_not_read(repo, python310, tmp_path):
    stage_original(repo, python310, tmp_path)
    upload(repo, python310, tmp_path, 2, **{"資料/.origin": origin_of("原版")})
    assert entry_of(repo)["copyright"] == [person(*SOMEONE)]
    z = make_zip(tmp_path / "s.zip", {"整理桌面/iplot.py": '"""說明"""\n'}, symlinks={"整理桌面/.origin": "/etc/passwd"})
    api = FakeApi([up(3)])
    assert run(repo, api, {att(3): z}, python310) == 0
    assert api.comments[3][0].startswith("收到了")


def test_an_origin_naming_a_reserved_or_unlicensed_module_adds_nobody(repo, python310, tmp_path):
    seed(repo, {registry.key("作業系統"): {"name": "作業系統", "reserved": True},
                registry.key("車車"): {"name": "車車", "owner_id": 71483597, "owner": "william10310406"}})
    upload(repo, python310, tmp_path, 1, **{".origin": origin_of("作業系統")})
    upload(repo, python310, tmp_path, 2, name="改車", **{".origin": origin_of("車車")})
    assert entry_of(repo)["copyright"] == [person(*SOMEONE)]
    assert entry_of(repo, "改車")["copyright"] == [person(*SOMEONE)]


def test_origin_pointing_at_the_modules_own_name_adds_nobody_twice(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1)
    upload(repo, python310, tmp_path, 2, iplot='"""說明"""\n# 2\n', **{".origin": origin_of("整理桌面")})
    assert entry_of(repo)["copyright"] == [person(*SOMEONE)]


def test_inspect_hands_over_the_origin_bytes_and_still_skips_it(tmp_path):
    z = make_zip(tmp_path / "o.zip", {"m/iplot.py": "x", "m/.origin": b"url: x\n", "m/sub/.origin": b"other"})
    unpacked = zipcheck.inspect(z, tmp_path / "staging")
    assert unpacked.origin == b"url: x\n"
    assert [f.path for f in unpacked.files] == ["iplot.py"]
    assert unpacked.skipped == {".origin": 2}
    plain = zipcheck.inspect(make_zip(tmp_path / "p.zip", {"m/iplot.py": "x"}), tmp_path / "staging2")
    assert plain.origin is None


def test_a_huge_origin_is_not_read(tmp_path):
    z = make_zip(tmp_path / "o.zip", {"m/iplot.py": "x", "m/.origin": b"a" * (zipcheck.MAX_ORIGIN + 1)})
    assert zipcheck.inspect(z, tmp_path / "staging").origin is None


# --- fork_of ----------------------------------------------------------------------------------------------

def test_fork_of_with_a_right_name_keeps_the_original_author(repo, python310, tmp_path):
    stage_original(repo, python310, tmp_path)
    upload(repo, python310, tmp_path, 2, fork_of="原版")
    assert entry_of(repo)["copyright"] == [person(*AUTHOR), person(*SOMEONE)]


@pytest.mark.parametrize("typed", ["guíde", "GUÍDE", unicodedata.normalize("NFD", "Guíde")])
def test_fork_of_is_looked_up_with_the_registry_key_rule(repo, python310, tmp_path, typed):
    stage_original(repo, python310, tmp_path, name="Guíde")
    upload(repo, python310, tmp_path, 2, fork_of=typed)
    assert entry_of(repo)["copyright"] == [person(*AUTHOR), person(*SOMEONE)]


@pytest.mark.parametrize("typed", ["guide", "GUIDE", "Guide"])
def test_fork_of_ignores_case(repo, python310, tmp_path, typed):
    stage_original(repo, python310, tmp_path, name="Guide")
    upload(repo, python310, tmp_path, 2, fork_of=typed)
    assert entry_of(repo)["copyright"] == [person(*AUTHOR), person(*SOMEONE)]


@pytest.mark.parametrize("typed", ["不存在", "原版2", "x" * 700, "a\nb", "`原版`", "作業系統", "guide"])
def test_fork_of_with_a_wrong_name_is_refused_with_the_exact_sentence(repo, python310, tmp_path, typed):
    stage_original(repo, python310, tmp_path)
    seed(repo, {**registry.read_json_strict(repo / "registry.json"),
                registry.key("作業系統"): {"name": "作業系統", "reserved": True}})
    shown = typed.strip()
    text = refuse("fork_unknown", name=shown).text
    refused(repo, python310, tmp_path, 2, text, fork_of=typed)
    assert text.startswith("找不到「") and text.endswith("」這個模組：填工作坊清單上的名稱，或留空。")


def test_the_wrong_name_sentence_is_the_one_in_the_design():
    assert SAY["fork_unknown"] == "找不到「{name}」這個模組：填工作坊清單上的名稱，或留空。"
    assert refuse("fork_unknown", name="甲").text == "找不到「`甲`」這個模組：填工作坊清單上的名稱，或留空。"


def test_fork_of_is_refused_before_anything_is_written_even_with_a_good_license(repo, python310, tmp_path):
    _, original = stage_original(repo, python310, tmp_path)
    refused(repo, python310, tmp_path, 2, refuse("fork_unknown", name="不存在").text, fork_of="不存在", LICENSE=original)


@pytest.mark.parametrize("fork_of", ["", None])
def test_an_empty_or_missing_fork_of_is_fine(repo, python310, tmp_path, fork_of):
    stage_original(repo, python310, tmp_path)
    upload(repo, python310, tmp_path, 2, fork_of=fork_of)
    assert entry_of(repo)["copyright"] == [person(*SOMEONE)]


def test_fork_of_naming_an_unlicensed_module_adds_nobody(repo, python310, tmp_path):
    seed(repo, {registry.key("車車"): {"name": "車車", "owner_id": 71483597, "owner": "william10310406"}})
    upload(repo, python310, tmp_path, 1, fork_of="車車")
    assert entry_of(repo)["copyright"] == [person(*SOMEONE)]


def test_fork_of_naming_the_modules_own_name_adds_nobody_twice(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1)
    upload(repo, python310, tmp_path, 2, fork_of="整理桌面", iplot='"""說明"""\n# 2\n')
    assert entry_of(repo)["copyright"] == [person(*SOMEONE)]


# --- 三個來源取聯集 ----------------------------------------------------------------------------------------

def three_sources(repo, python310, tmp_path):
    """甲(id 111)、乙(333)、丙(444) 各傳一個模組；回甲的 LICENSE。"""
    _, a = upload(repo, python310, tmp_path, 1, name="甲", login="a", user_id=111)
    upload(repo, python310, tmp_path, 2, name="乙", login="b", user_id=333)
    upload(repo, python310, tmp_path, 3, name="丙", login="c", user_id=444)
    return a


def test_license_origin_and_fork_of_are_unioned_in_that_order_then_the_uploader(repo, python310, tmp_path):
    lic = three_sources(repo, python310, tmp_path)
    api, raw = upload(repo, python310, tmp_path, 4, fork_of="丙", LICENSE=lic, **{".origin": origin_of("乙")})
    expected = [person("a", 111), person("b", 333), person("c", 444), person(*SOMEONE)]
    assert entry_of(repo)["copyright"] == expected
    assert raw == licensing.render(expected).encode("utf-8")
    assert licenses_of(repo)[licensing.digest(expected)] == expected
    reply = api.comments[4][0]
    assert "\n```\n" + "\n".join(licensing.lines_of(expected)) + "\n```\n" in reply
    assert "跟「" not in reply and "一樣" not in reply


def test_the_same_id_from_three_places_appears_once(repo, python310, tmp_path):
    _, a = upload(repo, python310, tmp_path, 1, name="甲", login="a", user_id=111)
    upload(repo, python310, tmp_path, 2, name="乙", login="a", user_id=111)
    upload(repo, python310, tmp_path, 3, name="丙", login="renamed", user_id=111)
    upload(repo, python310, tmp_path, 4, fork_of="丙", LICENSE=a, **{".origin": origin_of("乙")})
    assert entry_of(repo)["copyright"] == [person("a", 111), person(*SOMEONE)]


def test_a_module_that_already_has_a_list_keeps_it_first(repo, python310, tmp_path):
    lic = three_sources(repo, python310, tmp_path)
    upload(repo, python310, tmp_path, 4, fork_of="丙")
    upload(repo, python310, tmp_path, 5, LICENSE=lic, **{".origin": origin_of("乙")}, iplot='"""說明"""\n# 2\n')
    assert entry_of(repo)["copyright"] == [person("c", 444), person(*SOMEONE), person("a", 111), person("b", 333)]


def test_an_unknown_license_is_still_refused_when_origin_and_fork_of_are_good(repo, python310, tmp_path):
    three_sources(repo, python310, tmp_path)
    refused(repo, python310, tmp_path, 4, SAY["license_unknown"], fork_of="丙", LICENSE="我自己寫的", **{".origin": origin_of("乙")})


def test_only_the_owner_can_update_a_module_and_nothing_is_merged_for_others(repo, python310, tmp_path):
    stage_original(repo, python310, tmp_path)
    api = FakeApi([up(2, login="mallory", user_id=999, body=form_body(att(2), fork_of="原版"))])
    run(repo, api, {att(2): module_zip(tmp_path, "原版", **{".origin": origin_of("原版")})}, python310)
    assert "已經是別的帳號" in api.comments[2][0] and api.patches == [(2, REFUSED)]
    assert entry_of(repo, "原版")["copyright"] == [person(*AUTHOR)]


def test_a_fork_with_nothing_to_go_on_cannot_name_the_original_author(repo, python310, tmp_path):
    # 沒有 LICENSE、沒有 .origin、沒有填 fork_of：機器人無從知道原作者
    stage_original(repo, python310, tmp_path)
    upload(repo, python310, tmp_path, 2, name="改版")
    assert entry_of(repo, "改版")["copyright"] == [person(*SOMEONE)]


def test_the_commit_has_only_the_files_it_should(repo, python310, tmp_path):
    stage_original(repo, python310, tmp_path)
    upload(repo, python310, tmp_path, 2, fork_of="原版", **{".origin": origin_of("原版")})
    changed = git(repo, "-c", "core.quotepath=off", "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(changed) == ["licenses.json", "modules/整理桌面/LICENSE", "modules/整理桌面/iplot.py",
                               "received.json", "registry.json"]
    assert "2" in received(repo)
