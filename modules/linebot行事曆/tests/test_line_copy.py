"""複製進日記（做法 A）與自動複製（docs/01_設計.md 第 7 節）：這是唯一會把 LINE 的內容寫進日記資料夾的地方。

格式、接在原文後面不覆蓋、強制先存快照、已複製的不重複、私人與公開日子的規則、digest；自動：開關、範圍、略過、停在正在看的那天。"""

import datetime
import json
import stat

import pytest
from support import all_day_event, event, jot, line_payload, log, mood, task

import diary
import line_copy
import line_data
import line_view
import settings

DATE = "2026-11-06"
NOW = datetime.datetime(2026, 11, 8, 21, 50)
HEADER = "── 從 LINE 複製 2026-11-08 21:50 ──"


def data(**sections):
    base = {"events": [], "tasks": [], "logs": [], "moods": [], "jots": []}
    return line_data.parse(line_payload(range={"from": "2026-08-01", "to": "2026-12-31"}, **{**base, **sections}))


def standard_day(date=DATE, **extra):
    return data(
        events=[event(id="e1", title="開會", start=f"{date}T10:00:00+08:00", end=f"{date}T11:00:00+08:00", startDate=date, endDate=date,
                      location="會議室", note="帶筆電"),
                all_day_event(id="e4", title="生日", startDate=date, endDate=date, location=None)],
        tasks=[task(id="t1", title="買牛奶", dueDate=date, dueTime="18:00"),
               task(id="t2", title="交報告", dueDate=date, dueTime=None, done=True)],
        jots=[jot(id="j1", date=date, text="看到貓", createdAt=f"{date}T14:32:00+08:00"),
              jot(id="j2", date=date, text="吃蛋糕", createdAt=f"{date}T09:05:00+08:00")],
        logs=[log(date=date)], moods=[mood(date=date, face="smile", text="還不錯")], **extra)


def make_plan(d, root, date=DATE, copied=(), auto=False, now=NOW):
    mine = diary.read_day(root, date)
    return line_copy.build(date, line_view.day(d, date, mine), mine, line_view.mood_of(d, date), copied, now=now, auto=auto)


def block(*lines):
    return HEADER + "\n" + "".join(f"{line}\n" for line in lines)


EVENTS = ("整天 生日", "10:00–11:00 開會 @會議室", "  帶筆電", "☐ 買牛奶（截止 18:00）", "☑ 交報告")
JOTS = ("09:05 吃蛋糕", "14:32 看到貓")
LOGS = ("寫程式", "  完成解析", "散步")


def write_day(root, date=DATE, **fields):
    diary.save_day(root, date, fields, 20)


def read(root, field, date=DATE):
    path = diary.day_folder(root, date) / f"{field}.txt"
    return path.read_text(encoding="utf-8") if path.exists() else ""


@pytest.fixture
def ledger(tmp_path):
    return line_copy.Ledger(tmp_path / "line_copied.json")


@pytest.fixture
def clock(monkeypatch):
    now = [datetime.datetime(2026, 11, 8, 21, 0, 0)]
    monkeypatch.setattr(diary, "_now", lambda: now[0])
    return lambda **kw: now.__setitem__(0, now[0] + datetime.timedelta(**kw))


# ── 格式 ──

def test_event_task_jot_log_line_formats_and_field_mapping(root):
    plan = make_plan(standard_day(), root)
    assert plan.additions == {"行程": block(*EVENTS), "看到": block(*JOTS), "做了": block(*LOGS)}
    assert all(plan.fields[name] == text for name, text in plan.additions.items())   # 原本都是空的：整份就是新加的
    assert plan.mood == {"mood": "🙂", "note": "還不錯"} and plan.fields["心情"] == diary.mood_text("🙂", "還不錯")


def test_appends_after_existing_text_with_a_blank_line_and_a_header(root):
    write_day(root, 行程="我的行程")
    assert make_plan(standard_day(), root).fields["行程"] == "我的行程\n\n" + block(*EVENTS)
    write_day(root, 行程="我的行程\n")
    assert make_plan(standard_day(), root).fields["行程"] == "我的行程\n\n" + block(*EVENTS)
    write_day(root, 行程="我的行程\n\n\n")
    assert make_plan(standard_day(), root).fields["行程"] == "我的行程\n\n\n\n" + block(*EVENTS)


def test_empty_field_gets_header_and_items_only(root):
    plan = make_plan(standard_day(), root)
    assert plan.fields["看到"].startswith(HEADER + "\n") and not plan.fields["看到"].startswith("\n")


@pytest.mark.parametrize("existing", [
    "我的字", "我的字\n", "第一行\r\n第二行\r\n", "  前面有空白\t後面也有  ", "整段都是空白\n\n\n", "<b>標記</b> \"引號\"", "x" * 5000,
])
def test_never_overwrites_existing_text(root, existing):
    write_day(root, 行程=existing, 看到=existing, 做了=existing)
    plan = make_plan(standard_day(), root)
    for field in ("行程", "看到", "做了"):
        assert plan.fields[field].startswith(read(root, field)) and plan.fields[field] != read(root, field)


def test_mood_only_fills_empty_face_and_empty_note(root):
    cases = [("", "", {"mood": "🙂", "note": "還不錯"}), ("😄", "", {"mood": None, "note": "還不錯"}),
             ("", "我寫的", {"mood": "🙂", "note": None}), ("😄", "我寫的", None)]
    for face, note, expected in cases:
        write_day(root, 心情=diary.mood_text(face, note))
        plan = make_plan(standard_day(), root)
        assert plan.mood == expected, (face, note)
        if expected is None:
            assert "心情" not in plan.fields
        else:
            assert plan.fields["心情"] == diary.mood_text(expected["mood"] or face, expected["note"] or note)
        write_day(root, 心情="")


def test_mood_with_no_sentence_only_fills_the_face(root):
    plan = make_plan(data(moods=[mood(date=DATE, face="cry", text=None)]), root)
    assert plan.mood == {"mood": "😢", "note": None} and plan.fields["心情"] == diary.mood_text("😢", "")


def test_text_with_newlines_or_markup_is_copied_as_plain_text_only(root):
    nasty = "<img src=x onerror=alert(1)> \"q\" </script>"
    plan = make_plan(data(events=[event(id="x", title=nasty, note="第一行\n第二行", location=None)],
                          jots=[jot(id="y", text="甲\n乙\n丙")]), root)
    assert nasty in plan.additions["行程"] and "  第一行\n  第二行\n" in plan.additions["行程"]
    assert plan.additions["看到"] == block("14:32 甲", "  乙", "  丙")


def test_nothing_from_line_means_an_empty_plan(root):
    plan = make_plan(data(), root)
    assert plan.empty and plan.fields == {} and plan.items == [] and plan.mood is None


def test_unreadable_fields_are_skipped_and_reported_not_overwritten(root):
    folder = diary.day_folder(root, DATE)
    folder.mkdir(parents=True)
    (folder / "行程.txt").write_bytes(b"\xff\xfe\x00bad")
    plan = make_plan(standard_day(), root)
    assert "行程" not in plan.fields and plan.skipped["unreadable"] == ["行程"] and "看到" in plan.fields
    assert not any(key.startswith(("event:", "task:")) for key in plan.items)


# ── 略過：私人、已複製、公開 ──

def private_day():
    return data(events=[event(id="pe", title="私人活動", private=True), event(id="ge", title="公開活動", private=False)],
                tasks=[task(id="pt", title="私人待辦", private=True)], jots=[jot(id="pj", text="一則小記")],
                logs=[log(private=True, items=[{"title": "私人紀錄", "details": None}]), log(private=False)])


def test_non_public_day_copies_private_items_in_manual_mode(root):
    plan = make_plan(private_day(), root)
    assert "私人活動" in plan.additions["行程"] and "私人待辦" in plan.additions["行程"] and "一則小記" in plan.additions["看到"]
    assert "私人紀錄" in plan.additions["做了"] and plan.skipped["private"] == 0 and plan.public is False


def test_public_day_preview_warns_and_skips_private_items(root):
    diary.set_public(root, DATE, True)
    write_day(root, 行程="x")
    plan = make_plan(private_day(), root)
    assert plan.public is True and plan.skipped["private"] == 3   # 私人活動、私人待辦、私人紀錄（小記沒有 private 欄位）
    assert "私人" not in "".join(plan.additions.values()) and "公開活動" in plan.additions["行程"]


def test_auto_mode_always_skips_private_items_even_on_a_non_public_day(root):
    plan = make_plan(private_day(), root, auto=True)
    assert plan.skipped["private"] == 3 and "私人" not in "".join(plan.additions.values())
    assert "公開活動" in plan.additions["行程"]


def test_auto_mode_copies_nothing_on_a_public_day(root):
    diary.set_public(root, DATE, True)
    plan = make_plan(standard_day(), root, auto=True)
    assert plan.empty and plan.skipped["public_day"] is True and plan.fields == {} and plan.items == []


def test_already_copied_items_are_not_copied_twice(root, ledger):
    plan = make_plan(standard_day(), root)
    line_copy.apply(root, DATE, plan, 20, ledger, now=NOW)
    again = make_plan(standard_day(), root, copied=ledger)
    assert again.empty and again.skipped["already"] == len(plan.items)
    more = make_plan(data(jots=[jot(id="j1", date=DATE), jot(id="j9", date=DATE, text="新的")]), root, copied=ledger)
    assert "新的" in more.additions["看到"] and "看到一隻貓" not in more.additions["看到"]


def test_multi_day_event_is_tracked_per_day(root, ledger):
    trip = data(events=[all_day_event(id="trip", title="出差", startDate="2026-11-06", endDate="2026-11-08")])
    first = make_plan(trip, root, date="2026-11-06")
    assert first.items == ["event:trip:2026-11-06"] and "第 1 天／共 3 天" in first.additions["行程"]
    line_copy.apply(root, "2026-11-06", first, 20, ledger, now=NOW)
    second = make_plan(trip, root, date="2026-11-07", copied=ledger)
    assert second.items == ["event:trip:2026-11-07"] and "第 2 天／共 3 天" in second.additions["行程"]


def test_task_done_after_copy_is_not_copied_again(root, ledger):
    undone = data(tasks=[task(id="t1", title="買牛奶", dueDate=DATE, done=False)])
    line_copy.apply(root, DATE, make_plan(undone, root), 20, ledger, now=NOW)
    done = data(tasks=[task(id="t1", title="買牛奶", dueDate=DATE, done=True)])
    assert make_plan(done, root, copied=ledger).empty


def test_mood_is_copied_once_per_day(root, ledger):
    plan = make_plan(data(moods=[mood(date=DATE)]), root)
    assert plan.items == [f"mood:{DATE}"]
    line_copy.apply(root, DATE, plan, 20, ledger, now=NOW)
    write_day(root, 心情="")                                         # 就算你之後把它清掉，也不會再自動補回
    assert make_plan(data(moods=[mood(date=DATE)]), root, copied=ledger).empty


def test_log_items_have_no_ids_so_they_are_tracked_by_content(root, ledger):
    logs = data(logs=[log(date=DATE)])
    plan = make_plan(logs, root)
    assert len(plan.items) == 2 and all(key.startswith(f"log:{DATE}:") for key in plan.items)
    line_copy.apply(root, DATE, plan, 20, ledger, now=NOW)
    assert make_plan(logs, root, copied=ledger).empty
    changed = data(logs=[log(date=DATE, items=[{"title": "寫程式", "details": "完成解析"}, {"title": "新的一項", "details": None}])])
    assert make_plan(changed, root, copied=ledger).additions["做了"] == block("新的一項")


# ── digest ──

def test_digest_is_stable_and_changes_when_line_or_diary_changes(root):
    first = make_plan(standard_day(), root)
    assert first.digest == make_plan(standard_day(), root, now=NOW + datetime.timedelta(minutes=7)).digest   # 標題的時間不算
    assert first.digest != make_plan(data(jots=[jot(id="new", date=DATE)]), root).digest
    write_day(root, 行程="我改了這欄")
    assert make_plan(standard_day(), root).digest != first.digest


def test_digest_covers_the_mood(root):
    one = make_plan(data(moods=[mood(date=DATE, face="smile")]), root)
    two = make_plan(data(moods=[mood(date=DATE, face="cry")]), root)
    assert one.digest != two.digest


# ── 寫進去 ──

def test_apply_writes_every_field_and_the_pages_and_records_the_items(root, ledger):
    plan = make_plan(standard_day(), root)
    result = line_copy.apply(root, DATE, plan, 20, ledger, now=NOW)
    assert set(result["changed"]) == {"心情", "看到", "做了", "行程"} and result["items"] == len(plan.items) and result["warning"] is None
    assert read(root, "行程") == block(*EVENTS) and read(root, "看到") == block(*JOTS) and read(root, "做了") == block(*LOGS)
    assert diary.read_day(root, DATE)["mood"] == "🙂" and diary.read_day(root, DATE)["note"] == "還不錯"
    assert (diary.day_folder(root, DATE) / "index.html").exists()         # 網頁照常重建
    assert set(plan.items) == set(ledger.items) and json.loads(ledger.path.read_text(encoding="utf-8"))["items"]


def test_apply_saves_a_snapshot_even_if_the_field_was_edited_a_minute_ago(root, ledger, clock):
    write_day(root, 行程="v1")
    clock(minutes=1)
    write_day(root, 行程="v2：一分鐘前剛改過")        # 一般的存檔：上一份快照不到 10 分鐘，不會再存
    history = diary.day_folder(root, DATE) / diary.HISTORY
    assert [p.read_text(encoding="utf-8") for p in sorted(history.glob("行程-*.txt"))] == ["v1"]
    clock(minutes=1)
    line_copy.apply(root, DATE, make_plan(standard_day(), root), 20, ledger, now=NOW)
    snapshots = [p.read_text(encoding="utf-8") for p in sorted(history.glob("行程-*.txt"))]
    assert snapshots == ["v1", "v2：一分鐘前剛改過"]                            # 複製之前的內容找得回來，逐字相同
    assert read(root, "行程").startswith("v2：一分鐘前剛改過\n\n" + HEADER)


def test_apply_respects_history_keep(root, ledger, clock):
    for n in range(4):
        write_day(root, 行程=f"v{n}")
        clock(minutes=11)
    line_copy.apply(root, DATE, make_plan(standard_day(), root), 1, ledger, now=NOW)
    history = diary.day_folder(root, DATE) / diary.HISTORY
    assert [p.read_text(encoding="utf-8") for p in history.glob("行程-*.txt")] == ["v3"]


def test_failed_diary_write_does_not_record_items_as_copied(root, ledger, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(line_copy.diary, "save_day", broken)
    with pytest.raises(OSError, match="No space"):
        line_copy.apply(root, DATE, make_plan(standard_day(), root), 20, ledger, now=NOW)
    assert ledger.items == {} and not ledger.path.exists()


def test_apply_does_not_record_items_of_a_field_that_turned_out_unreadable(root, ledger, monkeypatch):
    plan = make_plan(standard_day(), root)
    real = diary.save_day

    def unreadable_now(root_, date, fields, keep, force_snapshot=False):
        result = real(root_, date, {k: v for k, v in fields.items() if k != "行程"}, keep, force_snapshot)
        result["unreadable"]["行程"] = "x"
        return result

    monkeypatch.setattr(line_copy.diary, "save_day", unreadable_now)
    line_copy.apply(root, DATE, plan, 20, ledger, now=NOW)
    assert not any(key.startswith(("event:", "task:")) for key in ledger.items) and any(key.startswith("jot:") for key in ledger.items)


def test_rebuild_failure_after_a_good_write_is_a_warning_not_a_lost_copy(root, ledger, monkeypatch):
    def broken(*args):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(line_copy.pages, "rebuild_after_save", broken)
    result = line_copy.apply(root, DATE, make_plan(standard_day(), root), 20, ledger, now=NOW)
    assert result["warning"] and str(root) not in result["warning"] and ledger.items and read(root, "行程")


def test_apply_with_an_empty_plan_writes_nothing(root, ledger):
    result = line_copy.apply(root, DATE, make_plan(data(), root), 20, ledger, now=NOW)
    assert result["changed"] == [] and result["items"] == 0 and not ledger.path.exists() and not (root / "2026").exists()


def test_building_a_plan_writes_nothing_anywhere(root, ledger):
    before = sorted(p for p in root.parent.rglob("*"))
    make_plan(standard_day(), root)
    assert sorted(p for p in root.parent.rglob("*")) == before and not ledger.path.exists()


# ── 已複製的紀錄 ──

def test_ledger_roundtrip_mode_and_unknown_fields(tmp_path):
    path = tmp_path / "line_copied.json"
    path.write_text(json.dumps({"version": 1, "auto_through": "2026-11-07", "future": {"a": 1},
                                "items": {"event:e1:2026-11-06": "2026-11-08T21:50:00", "bad": 5}}), encoding="utf-8")
    ledger = line_copy.Ledger(path)
    assert ledger.auto_through == "2026-11-07" and "event:e1:2026-11-06" in ledger and "bad" not in ledger
    ledger.add(["jot:j1:2026-11-06"], "2026-11-08T22:00:00")
    ledger.save()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["future"] == {"a": 1} and on_disk["version"] == 1 and on_disk["auto_through"] == "2026-11-07"
    assert sorted(on_disk["items"]) == ["event:e1:2026-11-06", "jot:j1:2026-11-06"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("content", ["{壞掉".encode(), b"\xff\xfe\x00", b"[1]", b'{"version": 9, "items": {"x": "y"}}', b""])
def test_ledger_survives_corruption_and_unknown_versions(tmp_path, content):
    path = tmp_path / "line_copied.json"
    path.write_bytes(content)
    ledger = line_copy.Ledger(path)
    assert ledger.items == {} and ledger.auto_through is None


def test_ledger_ignores_an_invalid_auto_through(tmp_path):
    path = tmp_path / "line_copied.json"
    path.write_text(json.dumps({"version": 1, "auto_through": "昨天", "items": {}}), encoding="utf-8")
    assert line_copy.Ledger(path).auto_through is None


# ── 自動複製 ──

def days_data(*dates, private_on=()):
    events, tasks, jots, moods = [], [], [], []
    for date in dates:
        flag = date in private_on
        events.append(event(id=f"e-{date}", title=f"活動 {date}", start=f"{date}T10:00:00+08:00", end=f"{date}T11:00:00+08:00",
                            startDate=date, endDate=date, private=flag))
        tasks.append(task(id=f"t-{date}", title=f"待辦 {date}", dueDate=date, private=flag))
        jots.append(jot(id=f"j-{date}", date=date, text=f"小記 {date}", createdAt=f"{date}T12:00:00+08:00"))
        moods.append(mood(date=date, text=f"心情 {date}"))
    return data(events=events, tasks=tasks, jots=jots, moods=moods)


@pytest.fixture
def module_dir(tmp_path):
    folder = tmp_path / "module"
    folder.mkdir()
    return folder


def auto(module_dir, root, merged, today, *, viewing=None, keep=20):
    return line_copy.run_auto(module_dir / "設定.json", module_dir / "line_copied.json", merged, root, keep,
                              today=today, now=datetime.datetime.fromisoformat(f"{today}T00:10:00"), viewing=viewing)


def enable(module_dir, today):
    line_copy.set_auto(module_dir / "設定.json", module_dir / "line_copied.json", True, today)


def test_auto_is_off_by_default_and_does_nothing_when_off(module_dir, root):
    result = auto(module_dir, root, days_data("2026-11-07"), "2026-11-09")
    assert result.enabled is False and result.message == "" and result.days_copied == 0
    assert not (module_dir / "line_copied.json").exists() and list(root.iterdir()) == []


def test_turning_on_sets_auto_through_to_yesterday_and_does_not_backfill(module_dir, root):
    enable(module_dir, "2026-11-08")
    assert settings.line(module_dir / "設定.json")["auto_copy"] is True
    assert line_copy.Ledger(module_dir / "line_copied.json").auto_through == "2026-11-07"
    result = auto(module_dir, root, days_data("2026-11-05", "2026-11-06", "2026-11-07"), "2026-11-08")
    assert result.days_copied == 0 and list(root.iterdir()) == []         # 昨天（11-07）在開開關那天就算過了


def test_turning_on_again_later_restarts_from_yesterday_not_from_where_it_was_off(module_dir, root):
    enable(module_dir, "2026-11-08")
    line_copy.set_auto(module_dir / "設定.json", module_dir / "line_copied.json", False, "2026-11-09")
    assert settings.line(module_dir / "設定.json")["auto_copy"] is False
    enable(module_dir, "2026-11-20")
    assert line_copy.Ledger(module_dir / "line_copied.json").auto_through == "2026-11-19"


def test_set_auto_keeps_the_url_and_unknown_settings(module_dir):
    settings.update(module_dir / "設定.json", lambda d: d.update({"資料夾": "/x", "LINE": {"url": "u", "write_key": "k"}}))
    enable(module_dir, "2026-11-08")
    assert settings.read(module_dir / "設定.json") == {"資料夾": "/x", "LINE": {"url": "u", "write_key": "k", "auto_copy": True}}


def test_auto_copies_each_missing_day_up_to_yesterday_then_advances_auto_through(module_dir, root):
    enable(module_dir, "2026-11-06")                                         # auto_through = 11-05
    merged = days_data("2026-11-06", "2026-11-07", "2026-11-08")
    result = auto(module_dir, root, merged, "2026-11-09")                      # 昨天是 11-08
    assert result.days_copied == 3 and result.through == "2026-11-08" and result.error is None
    for date in ("2026-11-06", "2026-11-07", "2026-11-08"):
        assert f"活動 {date}" in read(root, "行程", date) and f"小記 {date}" in read(root, "看到", date)
        assert "── 從 LINE 複製 2026-11-09 00:10 ──" in read(root, "行程", date)
    assert line_copy.Ledger(module_dir / "line_copied.json").auto_through == "2026-11-08"


def test_auto_never_copies_today_or_future_days(module_dir, root):
    enable(module_dir, "2026-11-06")
    auto(module_dir, root, days_data("2026-11-06", "2026-11-07", "2026-11-08", "2026-11-09", "2026-11-10"), "2026-11-08")
    assert read(root, "行程", "2026-11-07") and not read(root, "行程", "2026-11-08") and not read(root, "行程", "2026-11-10")


def test_auto_second_open_the_same_day_copies_nothing_new(module_dir, root):
    enable(module_dir, "2026-11-06")
    merged = days_data("2026-11-06", "2026-11-07")
    auto(module_dir, root, merged, "2026-11-09")
    before = {p: p.read_text(encoding="utf-8") for p in root.rglob("*.txt") if ".history" not in p.parts}
    result = auto(module_dir, root, merged, "2026-11-09")
    assert result.days_copied == 0 and result.message == ""
    assert {p: p.read_text(encoding="utf-8") for p in root.rglob("*.txt") if ".history" not in p.parts} == before


def test_auto_skips_private_items_always(module_dir, root):
    enable(module_dir, "2026-11-06")
    result = auto(module_dir, root, days_data("2026-11-06", "2026-11-07", private_on=("2026-11-07",)), "2026-11-09")
    assert result.skipped_private == 2 and "活動 2026-11-06" in read(root, "行程", "2026-11-06")
    assert "活動 2026-11-07" not in read(root, "行程", "2026-11-07") and "待辦 2026-11-07" not in read(root, "行程", "2026-11-07")
    assert "小記 2026-11-07" in read(root, "看到", "2026-11-07")                  # 小記沒有 private 欄位，照常複製


def test_auto_skips_public_days_entirely_and_reports_them(module_dir, root):
    enable(module_dir, "2026-11-06")
    diary.set_public(root, "2026-11-07", True)
    result = auto(module_dir, root, days_data("2026-11-06", "2026-11-07", "2026-11-08"), "2026-11-09")
    assert result.skipped_public_days == 1 and result.days_copied == 2
    assert read(root, "行程", "2026-11-06") and not read(root, "行程", "2026-11-07") and read(root, "行程", "2026-11-08")
    assert result.through == "2026-11-08"                                      # 公開的日子也算過了，不會每次打開再試


def test_auto_skips_the_day_the_page_is_viewing_and_stops_before_it(module_dir, root):
    enable(module_dir, "2026-11-06")
    merged = days_data("2026-11-06", "2026-11-07", "2026-11-08")
    result = auto(module_dir, root, merged, "2026-11-09", viewing="2026-11-07")
    assert result.days_copied == 1 and result.through == "2026-11-06" and not read(root, "行程", "2026-11-07")
    assert not read(root, "行程", "2026-11-08")                                  # 停在它前一天：後面的也等下次
    later = auto(module_dir, root, merged, "2026-11-09")
    assert later.days_copied == 2 and read(root, "行程", "2026-11-07") and read(root, "行程", "2026-11-08")


def test_auto_viewing_the_very_first_day_makes_no_progress(module_dir, root):
    enable(module_dir, "2026-11-06")
    result = auto(module_dir, root, days_data("2026-11-06"), "2026-11-08", viewing="2026-11-06")
    assert result.days_copied == 0 and result.through == "2026-11-05"


def test_auto_status_line_counts_days_and_skipped_items(module_dir, root):
    enable(module_dir, "2026-11-06")
    diary.set_public(root, "2026-11-08", True)
    result = auto(module_dir, root, days_data("2026-11-06", "2026-11-07", "2026-11-08", private_on=("2026-11-07",)), "2026-11-09")
    assert result.message == "自動複製了 2 天（略過 2 項私人、1 個公開的日子）"
    quiet = line_copy.AutoResult(enabled=True, days_copied=3)
    assert quiet.message == "自動複製了 3 天"
    nothing_new = line_copy.AutoResult(enabled=True, skipped_public_days=1)
    assert nothing_new.message == "自動複製：這次沒有複製任何東西（略過 1 個公開的日子）"
    assert line_copy.AutoResult(enabled=True).message == ""


def test_auto_catches_up_at_most_35_days(module_dir, root):
    settings.update(module_dir / "設定.json", lambda d: d.update({"LINE": {"auto_copy": True}}))
    ledger = line_copy.Ledger(module_dir / "line_copied.json")
    ledger.auto_through = "2026-08-01"
    ledger.save()
    merged = days_data("2026-09-15", "2026-10-04", "2026-10-05", "2026-11-08")
    result = auto(module_dir, root, merged, "2026-11-09")                      # 昨天 11-08 往前 34 天是 10-05
    assert not read(root, "行程", "2026-09-15") and not read(root, "行程", "2026-10-04")
    assert read(root, "行程", "2026-10-05") and read(root, "行程", "2026-11-08") and result.through == "2026-11-08"


def test_auto_with_the_switch_on_but_no_record_yet_starts_from_yesterday(module_dir, root):
    settings.update(module_dir / "設定.json", lambda d: d.update({"LINE": {"auto_copy": True}}))
    result = auto(module_dir, root, days_data("2026-11-06", "2026-11-07"), "2026-11-08")
    assert result.days_copied == 0 and line_copy.Ledger(module_dir / "line_copied.json").auto_through == "2026-11-07"


def test_auto_write_failure_stops_there_does_not_advance_past_it_and_leaks_no_path(module_dir, root, monkeypatch):
    enable(module_dir, "2026-11-06")
    real, calls = diary.save_day, []

    def flaky(root_, date, fields, keep, force_snapshot=False):
        calls.append(date)
        if date == "2026-11-07":
            raise OSError(28, "No space left on device", str(root_))
        return real(root_, date, fields, keep, force_snapshot)

    monkeypatch.setattr(line_copy.diary, "save_day", flaky)
    result = auto(module_dir, root, days_data("2026-11-06", "2026-11-07", "2026-11-08"), "2026-11-09")
    assert result.days_copied == 1 and result.through == "2026-11-06" and "存不進日記" in result.error and str(root) not in result.error
    assert calls == ["2026-11-06", "2026-11-07"] and result.message == result.error
    monkeypatch.setattr(line_copy.diary, "save_day", real)
    assert auto(module_dir, root, days_data("2026-11-06", "2026-11-07", "2026-11-08"), "2026-11-09").days_copied == 2   # 下次打開接著做


def test_auto_writes_only_inside_the_diary_folder_and_the_module_folder(tmp_path, module_dir, root):
    enable(module_dir, "2026-11-06")
    auto(module_dir, root, days_data("2026-11-06", "2026-11-07"), "2026-11-09")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["diary", "module"]
    assert sorted(p.name for p in module_dir.iterdir()) == ["line_copied.json", "設定.json"]


def test_auto_uses_the_forced_snapshot_so_the_original_can_be_found(module_dir, root, clock):
    enable(module_dir, "2026-11-06")
    write_day(root, "2026-11-07", 行程="我寫的行程")
    clock(minutes=1)
    write_day(root, "2026-11-07", 行程="我寫的行程（剛改）")
    clock(minutes=1)
    auto(module_dir, root, days_data("2026-11-07"), "2026-11-09")
    history = diary.day_folder(root, "2026-11-07") / diary.HISTORY
    assert "我寫的行程（剛改）" in [p.read_text(encoding="utf-8") for p in history.glob("行程-*.txt")]


def test_only_real_newlines_split_lines_and_other_characters_are_kept_as_they_are(root):
    odd = "前" + chr(0x2028) + "中" + chr(0x2029) + "後\x0b\x0c"
    plan = make_plan(data(events=[event(id="x", title="活動", note=odd + "\r\n第二行\r第三行")], jots=[jot(id="y", text=odd)]), root)
    assert f"  {odd}\n  第二行\n  第三行\n" in plan.additions["行程"]
    assert plan.additions["看到"] == block(f"14:32 {odd}")
