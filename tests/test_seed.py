from pathlib import Path

import build
import pytest
import receive
import registry
from iplot_rules import read_listing

ROOT = Path(__file__).resolve().parents[1]
RA_ID = 71483597  # Task 0 探針：GET /users/william10310406
SEEDS = ("開工", "打開核心原始碼", "開Terminal", "重新啟動", "互通", "主控面板", "行事曆", "科學計算", "上傳")
NOTICE = "這裡的模組是大家上傳的，沒有人審查。裝進來的模組第一次執行前 iPLoT 會先問；按確定之前，在面板上右鍵「打開程式碼」看一眼。"


def seed() -> dict:
    return registry.read_json_strict(ROOT / "registry.json")


def test_seed_registry_reads_strictly_and_keys_are_nfc_casefold():
    data = seed()
    assert data
    for k, entry in data.items():
        assert k == registry.key(entry["name"])


def test_reserved_three_have_only_name_and_reserved():
    data = seed()
    for name in ("作業系統", "更新", "工作坊"):
        assert data[registry.key(name)] == {"name": name, "reserved": True}


def test_seeds_belong_to_the_research_assistant():
    data = seed()
    assert len(data) == 12
    for name in SEEDS:
        entry = data[registry.key(name)]
        assert set(entry) == {"name", "owner_id", "owner"}
        assert entry["name"] == name
        assert entry["owner_id"] == RA_ID
        assert entry["owner"] == "william10310406"


def test_ghost_is_nowhere_in_the_registry():
    for entry in seed().values():
        assert entry.get("owner_id") != receive.GHOST_ID
        assert entry.get("owner") != "ghost"


def test_received_starts_empty():
    assert registry.read_json_strict(ROOT / "received.json") == {}
    assert (ROOT / "received.json").read_text(encoding="utf-8") == "{}\n"


def test_notice_is_the_design_sentence():
    assert (ROOT / "notice.txt").read_text(encoding="utf-8") == NOTICE + "\n"


def test_seed_registry_builds_an_empty_listing(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    for name in ("registry.json", "notice.txt"):
        (root / name).write_bytes((ROOT / name).read_bytes())
    out = tmp_path / "site"
    assert build.main([str(out)], root=root) == 0
    import json

    assert read_listing(json.loads((out / "index.json").read_text(encoding="utf-8"))) == ([], NOTICE)


@pytest.mark.parametrize("name, key", [("重新啟動", "taken"), ("上傳", "taken"), ("開Ｔｅｒｍｉｎａｌ", "similar"),
                                       ("工作坊", "reserved"), ("開 工", "similar")])
def test_seed_names_cannot_be_taken_or_imitated(name, key):
    data = seed()
    refusal = registry.check_name(name, 222, data) or registry.owner_refusal(name, 222, data)
    assert refusal is not None
    assert refusal.key == key


def test_research_assistant_can_upload_a_seed():
    data = seed()
    assert registry.check_name("開工", RA_ID, data) is None
    assert registry.owner_refusal("開工", RA_ID, data) is None
