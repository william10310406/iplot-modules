"""第三輪審查（c89d6a0）的重現檔，照新規則改寫：每一個例子要嘛「擋得住」，要嘛「刻意放行，而且 repo 裡的 LICENSE 仍是機器人產生的」。
測試名字跟審查的重現檔一一對得上；回報最後一節列每一個的結果。"""

import licensing
import pytest
import registry
from conftest import FakeApi
from say import SAY, refuse
from test_license import (
    RA,
    RA_ID,
    YEAR,
    entry_of,
    folder_of,
    like,
    person,
    refused,
    upload,
)
from test_receive import att, module_zip, run, seed, up

GPL = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n"


def received_as_is(repo, python310, tmp_path, n, path, content=GPL, **kw):
    upload(repo, python310, tmp_path, n, **{path: content}, **kw)
    stored = folder_of(repo, kw.get("name", "整理桌面")) / path
    return stored.exists() and stored.read_text(encoding="utf-8") == content


def license_is_still_generated(repo, name="整理桌面"):
    entry = entry_of(repo, name)
    return (folder_of(repo, name) / "LICENSE").read_bytes() == licensing.render(entry["copyright"]).encode("utf-8")


# --- 3. 像授權的檔名 --------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "LİCENSE", "LІCENSE", "LICΕNSE", "LIĆENSE", "LICEɴSE",     # 同形字：刻意放行
    "AUTHORS", "LEGAL.txt", "MIT.txt", "Apache-2.0.txt",       # 不是標準名字：刻意放行
    "LIZENZ", "授權條款.txt",                                    # 別的語言：刻意放行
    "vendor/LİCENSE",                                          # 子資料夾：刻意放行
])
def test_lookalike_names_that_get_in_are_now_deliberately_let_through(repo, python310, tmp_path, path):
    assert received_as_is(repo, python310, tmp_path, 1, path)
    assert license_is_still_generated(repo)


@pytest.mark.parametrize("path", ["COPYRIGHT", "COPYRIGHT.txt"])
def test_copyright_at_the_top_level_is_now_refused(repo, python310, tmp_path, path):
    refused(repo, python310, tmp_path, 1, like(path), **{path: GPL})


@pytest.mark.parametrize("path", ["ggplot.mplstyle", "notice_board.py", "gplot.py"])
def test_ordinary_names_that_were_refused_are_now_received(repo, python310, tmp_path, path):
    assert received_as_is(repo, python310, tmp_path, 1, path, "x")
    assert license_is_still_generated(repo)


# --- 1. LICENSE 本身：render 檢查版權人 ---------------------------------------------------------------------

def test_render_checks_holders():
    with pytest.raises(licensing.BadCopyright):
        licensing.render([[2026, "@a\n\nAdditional terms: no commercial use.", 1]])
    with pytest.raises(licensing.BadCopyright):
        licensing.render([[2026, "@a (GitHub user 1)\n\nAdditional terms: no commercial use.", 1]])


def test_a_hand_edited_registry_holder_does_not_flow_into_the_next_generated_license(repo, python310, tmp_path):
    _, before = upload(repo, python310, tmp_path, 1)
    data = registry.read_json_strict(repo / "registry.json")
    data[registry.key("整理桌面")]["copyright"] = [[2026, "@someone\nNo commercial use.", 222]]
    seed(repo, data)
    api = FakeApi([up(2)])
    assert run(repo, api, {att(2): module_zip(tmp_path, iplot='"""說明"""\n# 2\n')}, python310) == 0
    assert api.comments[2] == [SAY["stuck"]]
    assert (folder_of(repo) / "LICENSE").read_bytes() == before
    assert b"No commercial use" not in (folder_of(repo) / "LICENSE").read_bytes()


# --- 2. 版權人：帳號改名後被別人註冊 --------------------------------------------------------------------------

def test_a_reused_login_is_not_merged_into_the_original_author(repo, python310, tmp_path):
    _, original = upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    api, raw = upload(repo, python310, tmp_path, 2, name="冒名", login="author", user_id=999, LICENSE=original)
    # 999 是另一個人：兩個 id 都在，各自一行；原作者沒有被當成 999，999 也沒有被當成原作者
    assert entry_of(repo, "冒名")["copyright"] == [person("author", 111), person("author", 999)]
    assert raw != original
    assert (folder_of(repo, "原版") / "LICENSE").read_bytes() == original


def test_only_the_owner_can_update_a_module(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    api = FakeApi([up(2, login="mallory", user_id=999)])
    run(repo, api, {att(2): module_zip(tmp_path, "原版")}, python310)
    assert "已經是別的帳號" in api.comments[2][0]
    assert entry_of(repo, "原版")["copyright"] == [person("author", 111)]


def test_a_fork_without_any_source_still_cannot_know_the_original_author(repo, python310, tmp_path):
    # 沒有 LICENSE、沒有 .origin、沒有填 fork_of：機器人無從知道（刻意不處理）；有其中一個就會保留，見 test_license_forks
    upload(repo, python310, tmp_path, 1, name="原版", login="author", user_id=111)
    upload(repo, python310, tmp_path, 2, name="改版")
    assert entry_of(repo, "改版")["copyright"] == [person("someone", 222)]


# --- 4. licenses.json：附別的模組的 LICENSE -----------------------------------------------------------------

def test_any_published_license_adds_its_holders(repo, python310, tmp_path):
    # 刻意放行：附一份機器人產生過的 LICENSE＝聲明那是原作者；機器人分不出真假，只保證版權人只增不減
    _, theirs = upload(repo, python310, tmp_path, 1, name="不相干", login="stranger", user_id=444)
    upload(repo, python310, tmp_path, 2, name="我的")
    upload(repo, python310, tmp_path, 3, name="我的", iplot='"""說明"""\n# 2\n', LICENSE=theirs)
    assert entry_of(repo, "我的")["copyright"] == [person("someone", 222), person("stranger", 444)]


def test_the_reply_no_longer_names_a_module(repo, python310, tmp_path):
    upload(repo, python310, tmp_path, 1, name="甲", login="w", user_id=RA_ID)
    _, from_b = upload(repo, python310, tmp_path, 2, name="乙", login="w", user_id=RA_ID)
    api, _ = upload(repo, python310, tmp_path, 3, name="改乙", LICENSE=from_b)
    assert entry_of(repo, "改乙")["copyright"] == [[YEAR, RA, RA_ID], person("someone", 222)]
    reply = api.comments[3][0]
    assert "甲" not in reply and "乙" not in reply.replace("改乙", "") and "跟「" not in reply
    assert f"Copyright (c) {YEAR} {RA}" in reply


def test_the_repo_has_one_hash_for_every_ra_module():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    data = registry.read_json_strict(root / "registry.json")
    hashes = {licensing.digest(e["copyright"]) for e in data.values() if e.get("copyright")}
    assert hashes == set(registry.read_json_strict(root / "licenses.json"))
    assert len(hashes) == 1


def test_a_symlink_named_license_is_skipped_and_the_bot_writes_its_own(repo, python310, tmp_path):
    from conftest import make_zip

    z = make_zip(tmp_path / "s.zip", {"整理桌面/iplot.py": '"""說明"""\n'}, symlinks={"整理桌面/LICENSE": "/etc/passwd"})
    api = FakeApi([up(1)])
    run(repo, api, {att(1): z}, python310)
    assert (folder_of(repo) / "LICENSE").read_bytes() == licensing.render([person("someone", 222)]).encode()


def test_the_refusal_sentence_for_a_standard_name_asks_to_remove_it():
    assert refuse("license_like", path="COPYRIGHT").text.endswith("拿掉 `COPYRIGHT` 再傳。")
