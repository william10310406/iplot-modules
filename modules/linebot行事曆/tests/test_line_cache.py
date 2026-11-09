"""LINE 的快取（docs/01_設計.md 第 4.7 節）：按「段」存、保留每筆的 id、較新的一段優先、壞檔當空的、原子寫、權限 0600。"""

import json
import stat

import pytest
from support import all_day_event, event, jot, line_payload, log, mood, task

import line_cache
import line_data
import settings

T0 = 1_800_000_000.0  # 2027-01-15 08:00 +08:00
DAY = 86400.0


def parsed(from_, to, **sections):
    payload = line_payload(range={"from": from_, "to": to})
    for name in ("events", "tasks", "logs", "moods", "jots"):
        payload[name] = sections.get(name, [])
    return line_data.parse(payload)


@pytest.fixture
def path(tmp_path):
    return tmp_path / "line_cache.json"


def test_roundtrip_keeps_ids_and_every_known_field(path):
    cache = line_cache.Cache(account="abc123def456")
    cache.add_slice(line_data.parse(line_payload()), T0)
    cache.record(True, None, "", T0)
    cache.retry_until = T0 + 60
    line_cache.save(path, cache)

    again = line_cache.load(path)
    assert again.account == "abc123def456"
    assert again.merged().to_payload() == line_data.parse(line_payload()).to_payload()
    assert [e["id"] for e in again.merged().events] == ["e1", "e2"] and [j["id"] for j in again.merged().jots] == ["j2", "j1"]
    assert again.last == {"at": T0, "ok": True, "kind": None, "message": ""} and again.retry_until == T0 + 60
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["version"] == 1 and "e1" in path.read_text(encoding="utf-8")  # id 真的存在檔案裡


def test_corrupt_unreadable_or_future_version_loads_as_empty(path, tmp_path):
    assert line_cache.load(path).slices == []                      # 不存在
    path.write_text("{壞掉", encoding="utf-8")
    assert line_cache.load(path).slices == []
    path.write_bytes(b"\xff\xfe\x00")
    assert line_cache.load(path).slices == []
    path.write_text("[1, 2]", encoding="utf-8")
    assert line_cache.load(path).slices == []
    path.write_text(json.dumps({"version": 99, "slices": [{"fetched_at": "x", "data": {}}]}), encoding="utf-8")
    assert line_cache.load(path).slices == []
    assert line_cache.load(tmp_path).slices == []                  # 是資料夾，讀不了


def test_one_bad_slice_is_skipped_and_the_others_survive(path):
    cache = line_cache.Cache()
    cache.add_slice(parsed("2026-10-01", "2026-10-10", events=[event(startDate="2026-10-05", endDate="2026-10-05",
                                                                    start=None, end=None, allDay=True)]), T0)
    cache.add_slice(parsed("2026-11-01", "2026-11-10"), T0 + 1)
    line_cache.save(path, cache)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["slices"][1]["data"]["events"] = "壞掉"
    path.write_text(json.dumps(data), encoding="utf-8")
    again = line_cache.load(path)
    assert [(s.range_from, s.range_to) for s in again.slices] == [("2026-10-01", "2026-10-10")]


def test_write_is_atomic_and_mode_0600(path, monkeypatch):
    cache = line_cache.Cache()
    cache.add_slice(parsed("2026-10-01", "2026-10-10"), T0)
    line_cache.save(path, cache)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    before = path.read_text(encoding="utf-8")

    def broken(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(settings.os, "replace", broken)
    cache.record(False, "timeout", "x", T0 + 1)
    with pytest.raises(OSError, match="disk full"):
        line_cache.save(path, cache)
    assert path.read_text(encoding="utf-8") == before
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_newer_slice_wins_per_id_and_per_date_and_older_items_outside_it_stay():
    cache = line_cache.Cache()
    old = parsed("2026-10-01", "2026-10-31",
                 events=[event(id="e1", title="舊標題", start="2026-10-10T10:00:00+08:00", end="2026-10-10T11:00:00+08:00",
                               startDate="2026-10-10", endDate="2026-10-10"),
                         event(id="e9", title="十月底", start="2026-10-25T10:00:00+08:00", end="2026-10-25T11:00:00+08:00",
                               startDate="2026-10-25", endDate="2026-10-25")],
                 moods=[mood(date="2026-10-10", face="smile"), mood(date="2026-10-25", face="grin")],
                 jots=[jot(id="j1", date="2026-10-10", text="舊小記")])
    new = parsed("2026-10-05", "2026-10-20",
                 events=[event(id="e1", title="新標題", start="2026-10-10T10:00:00+08:00", end="2026-10-10T11:00:00+08:00",
                               startDate="2026-10-10", endDate="2026-10-10")],
                 moods=[mood(date="2026-10-10", face="cry")], jots=[jot(id="j1", date="2026-10-10", text="新小記")])
    cache.add_slice(old, T0)
    cache.add_slice(new, T0 + 10)
    merged = cache.merged()
    assert {e["id"]: e["title"] for e in merged.events} == {"e1": "新標題", "e9": "十月底"}
    assert {m["date"]: m["face"] for m in merged.moods} == {"2026-10-10": "cry", "2026-10-25": "grin"}
    assert [j["text"] for j in merged.jots] == ["新小記"]


def test_item_deleted_in_line_disappears_after_refetching_its_range():
    cache = line_cache.Cache()
    both = [task(id="t1", dueDate="2026-10-10"), task(id="t2", dueDate="2026-10-12")]
    cache.add_slice(parsed("2026-10-01", "2026-10-31", tasks=both), T0)
    cache.add_slice(parsed("2026-10-08", "2026-10-14", tasks=[task(id="t2", dueDate="2026-10-12")]), T0 + 5)  # t1 在 LINE 被刪了
    assert [t["id"] for t in cache.merged().tasks] == ["t2"]


def test_event_is_anchored_on_its_first_day_so_a_multi_day_event_is_not_duplicated():
    cache = line_cache.Cache()
    trip = all_day_event(id="trip", startDate="2026-10-09", endDate="2026-10-12")
    cache.add_slice(parsed("2026-10-01", "2026-10-10", events=[trip]), T0)
    cache.add_slice(parsed("2026-10-11", "2026-10-20", events=[trip]), T0 + 5)
    assert [e["id"] for e in cache.merged().events] == ["trip"]


def test_undated_tasks_come_only_from_the_newest_slice():
    cache = line_cache.Cache()
    cache.add_slice(parsed("2026-10-01", "2026-10-10", tasks=[task(id="u1", dueDate=None, dueTime=None)]), T0)
    cache.add_slice(parsed("2026-12-01", "2026-12-10", tasks=[task(id="u2", dueDate=None, dueTime=None)]), T0 + 5)
    assert [t["id"] for t in cache.merged().tasks] == ["u2"]


def test_slice_fully_covered_by_newer_one_is_dropped():
    cache = line_cache.Cache()
    cache.add_slice(parsed("2026-10-05", "2026-10-10"), T0)
    cache.add_slice(parsed("2026-10-01", "2026-10-31"), T0 + 5)
    assert [(s.range_from, s.range_to) for s in cache.slices] == [("2026-10-01", "2026-10-31")]
    cache.add_slice(parsed("2026-10-10", "2026-10-20"), T0 + 9)   # 只蓋住一部分：兩段都留
    assert len(cache.slices) == 2


def test_at_most_12_slices_oldest_dropped():
    cache = line_cache.Cache()
    for n in range(15):
        cache.add_slice(parsed(f"2026-{n % 9 + 1:02d}-01", f"2026-{n % 9 + 1:02d}-02", jots=[]), T0 + n)
    assert len(cache.slices) <= 12
    fresh = line_cache.Cache()
    for n in range(14):
        day = f"2026-01-{n + 1:02d}"
        fresh.add_slice(parsed(day, day), T0 + n)
    assert len(fresh.slices) == 12 and fresh.slices[0].range_from == "2026-01-03" and fresh.slices[-1].range_from == "2026-01-14"


def test_slices_older_than_400_days_are_dropped():
    cache = line_cache.Cache()
    cache.add_slice(parsed("2025-01-01", "2025-01-10"), T0)
    cache.add_slice(parsed("2026-10-01", "2026-10-10"), T0 + 1)
    cache.prune("2026-11-08")                 # 今天（台北）：2026-11-08 的 400 天前是 2025-10-04
    assert [s.range_from for s in cache.slices] == ["2026-10-01"]
    cache.add_slice(parsed("2025-02-01", "2025-02-02"), T0 + 2, today="2026-11-08")   # add_slice 也會順便丟
    assert [s.range_from for s in cache.slices] == ["2026-10-01"]


def test_covers_within_24h_and_not_after():
    cache = line_cache.Cache()
    cache.add_slice(parsed("2026-10-01", "2026-10-31"), T0)
    assert cache.covers("2026-10-05", "2026-10-20", now=T0 + DAY - 1) is True
    assert cache.covers("2026-10-05", "2026-10-20", now=T0 + DAY + 1) is False
    assert cache.covers("2026-10-05", "2026-11-02", now=T0 + 10) is False      # 超出一天
    assert cache.covers("2026-10-05", "2026-10-20", now=T0 + 10, ttl=0.5) is False  # ttl 可調


def test_missing_returns_only_the_uncovered_part():
    cache = line_cache.Cache()
    cache.add_slice(parsed("2026-10-01", "2026-10-10"), T0)
    cache.add_slice(parsed("2026-10-15", "2026-10-31"), T0)
    assert cache.missing("2026-10-05", "2026-11-05", now=T0 + 10) == [("2026-10-11", "2026-10-14"), ("2026-11-01", "2026-11-05")]
    assert cache.missing("2026-10-02", "2026-10-09", now=T0 + 10) == []
    assert cache.missing("2026-12-01", "2026-12-31", now=T0 + 10) == [("2026-12-01", "2026-12-31")]
    assert cache.missing("2026-10-05", "2026-10-20", now=T0 + DAY + 10) == [("2026-10-05", "2026-10-20")]  # 過期＝沒有


def test_missing_with_adjacent_slices_has_no_gap():
    cache = line_cache.Cache()
    cache.add_slice(parsed("2026-10-01", "2026-10-10"), T0)
    cache.add_slice(parsed("2026-10-11", "2026-10-20"), T0)
    assert cache.missing("2026-10-01", "2026-10-20", now=T0) == []


def test_account_mismatch_means_the_cache_is_not_used(path):
    cache = line_cache.Cache(account="aaaaaaaaaaaa")
    cache.add_slice(line_data.parse(line_payload()), T0)
    line_cache.save(path, cache)
    assert len(line_cache.load(path, account="aaaaaaaaaaaa").slices) == 1
    other = line_cache.load(path, account="bbbbbbbbbbbb")
    assert other.slices == [] and other.account == "bbbbbbbbbbbb"
    assert len(line_cache.load(path).slices) == 1   # 不指定帳號就是原樣


def test_latest_fetch_and_record_and_clear():
    cache = line_cache.Cache()
    assert cache.latest_fetch() is None
    cache.add_slice(parsed("2026-10-01", "2026-10-02"), T0)
    cache.add_slice(parsed("2026-11-01", "2026-11-02"), T0 + 50)
    assert cache.latest_fetch() == T0 + 50
    cache.record(False, "not_found", "找不到", T0 + 99)
    assert cache.last == {"at": T0 + 99, "ok": False, "kind": "not_found", "message": "找不到"}
    cache.clear_data()
    assert cache.slices == [] and cache.merged().events == [] and cache.latest_fetch() is None


def test_merge_does_not_modify_slices_and_is_stable():
    cache = line_cache.Cache()
    cache.add_slice(line_data.parse(line_payload()), T0)
    first = cache.merged()
    first.events[0]["title"] = "被改了"           # 改了合併的結果
    assert cache.merged().events[0]["title"] == "開會"
    assert cache.merged().to_payload() == cache.merged().to_payload()


def test_empty_cache_merges_to_empty_parsed():
    merged = line_cache.Cache().merged()
    assert (merged.events, merged.tasks, merged.logs, merged.moods, merged.jots) == ([], [], [], [], [])


def test_logs_for_the_same_date_survive_when_they_are_different_private_or_group_records():
    cache = line_cache.Cache()
    mine = log(date="2026-10-10", private=True, items=[{"title": "私", "details": None}])
    work = log(date="2026-10-10", private=False, group="工作群", items=[{"title": "公", "details": None}])
    cache.add_slice(parsed("2026-10-01", "2026-10-31", logs=[mine, work]), T0)
    assert len(cache.merged().logs) == 2
