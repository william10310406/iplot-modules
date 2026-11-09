"""diary.snapshot／save_day 的強制快照（docs/01_設計.md L07）：複製進日記之前一定要存一份，才找得回「複製之前」的原文。

不加參數時行為跟行事曆 0.1.1 一樣（同一個欄位的上一份快照不到 10 分鐘就不存）。"""

import datetime

import pytest

import diary

DATE = "2026-11-06"


@pytest.fixture
def clock(monkeypatch):
    now = [datetime.datetime(2026, 11, 7, 9, 0, 0)]
    monkeypatch.setattr(diary, "_now", lambda: now[0])

    def advance(**kw):
        now[0] += datetime.timedelta(**kw)

    return advance


def history(root, field="行程"):
    folder = diary.day_folder(root, DATE) / diary.HISTORY
    return sorted(folder.glob(f"{field}-*.txt")) if folder.exists() else []


def contents(root, field="行程"):
    return [p.read_text(encoding="utf-8") for p in history(root, field)]


def save(root, text, keep=20, **kw):
    return diary.save_day(root, DATE, {"行程": text}, keep, **kw)


def test_snapshot_without_force_skips_when_last_is_under_10_minutes(root, clock):
    save(root, "v1")
    save(root, "v2")                      # 蓋掉 v1 之前存 v1
    assert contents(root) == ["v1"]
    clock(minutes=5)
    save(root, "v3")                      # 上一份不到 10 分鐘：不存
    assert contents(root) == ["v1"]
    clock(minutes=6)
    save(root, "v4")                      # 距離上一份 11 分鐘：存（v3）
    assert contents(root) == ["v1", "v3"]


def test_snapshot_with_force_always_saves(root, clock):
    save(root, "v1")
    save(root, "v2")
    clock(minutes=2)
    save(root, "v3", force_snapshot=True)   # 才 2 分鐘，但強制：把 v2（複製之前的內容）存下來
    assert contents(root) == ["v1", "v2"]
    assert (diary.day_folder(root, DATE) / "行程.txt").read_text(encoding="utf-8") == "v3"


def test_force_saves_even_in_the_same_second_without_overwriting_earlier_snapshots(root, clock):
    save(root, "v1")
    save(root, "v2", force_snapshot=True)
    save(root, "v3", force_snapshot=True)
    save(root, "v4", force_snapshot=True)
    assert sorted(contents(root)) == ["v1", "v2", "v3"]  # 同一秒：-2、-3，不會互相蓋掉


def test_force_still_respects_the_keep_limit(root, clock):
    save(root, "v0")
    for n in range(1, 6):
        clock(seconds=1)
        save(root, f"v{n}", keep=2, force_snapshot=True)
    assert contents(root) == ["v3", "v4"]  # 只留最新的 2 份


def test_force_with_nothing_to_snapshot_is_harmless(root, clock):
    save(root, "first", force_snapshot=True)  # 檔案還不存在：沒有東西可存
    assert history(root) == []
    assert (diary.day_folder(root, DATE) / "行程.txt").read_text(encoding="utf-8") == "first"


def test_save_day_without_the_flag_behaves_exactly_as_before(root, clock):
    result = save(root, "a")
    assert result == {"changed": ["行程"], "unreadable": {}}
    assert save(root, "a") == {"changed": [], "unreadable": {}}       # 沒變就不寫
    assert save(root, "") == {"changed": ["行程"], "unreadable": {}}  # 存成空的就刪檔
    assert not (diary.day_folder(root, DATE) / "行程.txt").exists()
    assert contents(root) == ["a"]


def test_snapshot_signature_keeps_force_optional_and_last():
    import inspect
    params = inspect.signature(diary.snapshot).parameters
    assert list(params) == ["path", "keep", "force"] and params["force"].default is False
    save_params = inspect.signature(diary.save_day).parameters
    assert list(save_params)[-1] == "force_snapshot" and save_params["force_snapshot"].default is False
