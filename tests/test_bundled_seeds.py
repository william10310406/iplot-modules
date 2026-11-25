"""隨附模組的名字都要在 registry.json 裡：保留的，或登記給研究助理（D103）。拿隔壁的 iPLoT 的 git ls-files 核對。

要隨附、iPLoT 那邊還沒合進來的名字寫在 PLANNED：名字要在它公開之前先登記好（iPLoT M8 的「回報與討論」，
評估見 iPLoT 的 docs/plans/2026-10-24-M8-名字保留-評估.md）。iPLoT 合進來之後就可以從 PLANNED 拿掉。"""

import subprocess
import unicodedata
from pathlib import Path

import registry

ROOT = Path(__file__).resolve().parents[1]
RA_ID = 71483597  # Task 0 探針：GET /users/william10310406（跟 test_seed.py 同一個）
PLANNED = ("回報與討論",)


def missing(names: set[str]) -> list[str]:
    """names 裡在 registry.json 既不是保留的、也不是研究助理的那幾個。"""
    data = registry.read_json_strict(ROOT / "registry.json")
    return sorted(n for n in names
                  if not (data.get(registry.key(n), {}).get("reserved")
                          or data.get(registry.key(n), {}).get("owner_id") == RA_ID))


def test_every_module_tracked_in_iplot_next_door_is_reserved_or_seeded(iplot_next_door):
    out = subprocess.run(["git", "-C", str(iplot_next_door), "ls-files", "-z", "--", "modules"],
                         capture_output=True, check=True).stdout.decode("utf-8")
    tracked = {unicodedata.normalize("NFC", p.split("/")[1]) for p in out.split("\0") if p.count("/") >= 2}
    assert tracked and not missing(tracked), missing(tracked)


def test_planned_bundled_modules_are_seeded_before_iplot_ships_them():
    assert not missing(set(PLANNED)), missing(set(PLANNED))


def shipped(iplot):
    """iPLoT 的核心的包帶的模組：git 追蹤的 modules/ 底下、沒有標 export-ignore 的（跟 iPLoT 的 tools/bundled_hashes.py 一樣）。"""
    out = subprocess.run(["git", "-C", str(iplot), "ls-files", "-z", "--", "modules"],
                         capture_output=True, check=True).stdout.decode("utf-8")
    tops = sorted({p.split("/")[1] for p in out.split("\0") if p.count("/") >= 2})
    attrs = subprocess.run(["git", "-C", str(iplot), "check-attr", "-z", "export-ignore", "--", *(f"modules/{n}/" for n in tops)],
                           capture_output=True, check=True).stdout.decode("utf-8").split("\0")
    ignored = {attrs[i].split("/")[1] for i in range(0, len(attrs) - 2, 3) if attrs[i + 2] == "set"}
    return {unicodedata.normalize("NFC", n) for n in tops if n not in ignored}


def test_bundled_flags_are_exactly_the_modules_iplot_ships(iplot_next_door):
    """清單上標 bundled 的（D166：工作坊不給覆蓋）＝iPLoT 的包帶的、這裡有登記給研究助理的那幾個。保留的名字不發，不用標。"""
    data = registry.read_json_strict(ROOT / "registry.json")
    flagged = {v["name"] for v in data.values() if v.get("bundled") is True}
    expected = {n for n in shipped(iplot_next_door) if data.get(registry.key(n), {}).get("owner_id") == RA_ID}
    assert {registry.key(n) for n in flagged} == {registry.key(n) for n in expected}


def test_the_listing_carries_the_bundled_flag(tmp_path):
    import build

    folder = tmp_path / "modules" / "甲"
    folder.mkdir(parents=True)
    (folder / "iplot.py").write_text('"""甲"""\ndef run(app):\n    pass\n', encoding="utf-8")
    entry = {"name": "甲", "version": "1.0.0", "bundled": True, "license": "MIT"}
    made = build.make_entry(entry, tmp_path, tmp_path / "site", "https://example.invalid/", None, {})
    assert made["bundled"] is True
    assert "bundled" not in build.make_entry({**entry, "bundled": False}, tmp_path, tmp_path / "site2",
                                             "https://example.invalid/", None, {})
