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
