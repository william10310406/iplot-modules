"""把 LINE 的資料變成月、年、日要顯示的樣子，以及心情的優先順序（docs/01_設計.md 第 5、6 節）。

view 只讀、不碰檔案與網路；回的東西都能直接變成 JSON 給頁面。"""

import copy
import json

import pytest
from support import all_day_event, event, jot, line_payload, log, mood, task

import line_data
import line_view

SMILE = {"date": "2026-11-06", "face": "smile", "emoji": "🙂", "text": "還不錯"}


def build(**sections):
    base = {"events": [], "tasks": [], "logs": [], "moods": [], "jots": []}
    return line_data.parse(line_payload(range={"from": "2026-10-01", "to": "2026-12-31"}, **{**base, **sections}))


def busy_day():
    """2026-11-06：一個整天、兩個有時間的活動、兩個待辦、一個心情、兩則小記、一份紀錄。"""
    return build(
        events=[event(id="e1", title="開會", start="2026-11-06T10:00:00+08:00", end="2026-11-06T11:00:00+08:00"),
                event(id="e3", title="早餐", start="2026-11-06T09:00:00+08:00", end="2026-11-06T09:30:00+08:00", location=None, note=None),
                all_day_event(id="e4", title="生日", startDate="2026-11-06", endDate="2026-11-06")],
        tasks=[task(id="t1", title="買牛奶", dueDate="2026-11-06", dueTime="18:00"),
               task(id="t2", title="交報告", dueDate="2026-11-06", dueTime=None, done=True)],
        moods=[mood(date="2026-11-06", face="smile", text="還不錯")],
        jots=[jot(id="j1", date="2026-11-06", text="看到貓", createdAt="2026-11-06T14:32:00+08:00"),
              jot(id="j2", date="2026-11-06", text="吃蛋糕", createdAt="2026-11-06T09:05:00+08:00")],
        logs=[log(date="2026-11-06")])


# ── 心情 ──

def test_my_face_wins_and_line_mood_is_hidden():
    result = line_view.effective_mood("😄", "我的一句話", SMILE)
    assert result == {"source": "mine", "emoji": "😄", "text": None}


def test_line_mood_shows_when_i_chose_no_face():
    assert line_view.effective_mood("", "", SMILE) == {"source": "line", "emoji": "🙂", "text": "還不錯"}


def test_note_only_counts_as_no_face_but_keeps_my_note():
    result = line_view.effective_mood("", "我只寫了一句話", SMILE)
    assert result == {"source": "line", "emoji": "🙂", "text": "還不錯"}  # LINE 的臉；我的一句話在我自己的欄位，這裡不碰


def test_no_mood_anywhere_shows_nothing():
    assert line_view.effective_mood("", "", None) == {"source": None, "emoji": "", "text": None}
    assert line_view.effective_mood("", "只有一句話", None)["source"] is None


def test_line_mood_without_a_sentence_has_no_text():
    assert line_view.effective_mood("", "", {**SMILE, "text": None})["text"] is None


def test_mood_priority_for_a_day_view_and_the_month_and_year():
    data = busy_day()
    mine = {"mood": "😢", "note": "", "images": []}
    assert line_view.day(data, "2026-11-06", mine)["mood"]["source"] == "mine"
    assert line_view.day(data, "2026-11-06", {"mood": "", "note": "x"})["mood"] == {"source": "line", "emoji": "🙂", "text": "還不錯"}
    assert line_view.day(data, "2026-11-06", None)["mood"]["source"] == "line"


# ── 月 ──

def test_month_cell_prefers_my_first_line_then_line_lines():
    data = busy_day()
    without = line_view.month(data, "2026-11", {})["06"]
    assert [row["text"] for row in without["lines"]] == ["生日", "09:00 早餐"]
    with_mine = line_view.month(data, "2026-11", {"06": {"mood": "", "first": "我寫的第一行"}})["06"]
    assert with_mine["lines"] == [] and with_mine["count"] == 5  # 我有字就不顯示 LINE 的行；數量還在（頁面可以標「ᴸ+5」）


def test_month_cell_sorts_events_before_tasks_and_by_time_and_caps_at_two_with_more_count():
    cell = line_view.month(busy_day(), "2026-11", {})["06"]
    assert cell["count"] == 5 and cell["more"] == 3 and len(cell["lines"]) == 2
    day = line_view.day(busy_day(), "2026-11-06", None)
    assert [e["title"] for e in day["events"]] == ["生日", "早餐", "開會"]       # 整天在前，再按開始時間
    assert [t["title"] for t in day["tasks"]] == ["買牛奶", "交報告"]
    full = line_view.month(build(events=[event(id=f"e{n}", title=f"活動{n}", start=f"2026-11-06T0{n}:00:00+08:00",
                                                 end=f"2026-11-06T0{n}:30:00+08:00") for n in (3, 1, 2)],
                                 tasks=[task(id="t1", title="待辦", dueDate="2026-11-06")]), "2026-11", {})["06"]
    assert [row["text"] for row in full["lines"]] == ["01:00 活動1", "02:00 活動2"]
    assert full["more"] == 2  # 活動3 與 待辦


def test_month_lines_carry_kind_done_and_private():
    data = build(tasks=[task(id="a", title="完成的", dueDate="2026-11-06", dueTime=None, done=True),
                        task(id="b", title="私人的", dueDate="2026-11-07", dueTime="09:30", private=True)])
    month = line_view.month(data, "2026-11", {})
    assert month["06"]["lines"] == [{"kind": "task", "text": "完成的", "done": True, "private": False}]
    assert month["07"]["lines"] == [{"kind": "task", "text": "09:30 私人的", "done": False, "private": True}]


def test_done_and_undone_tasks_are_distinguishable():
    tasks = {t["title"]: t["done"] for t in line_view.day(busy_day(), "2026-11-06", None)["tasks"]}
    assert tasks == {"買牛奶": False, "交報告": True}


def test_private_items_are_marked_not_hidden():
    data = build(events=[event(id="p", title="私人活動", private=True)], tasks=[task(id="q", title="私人待辦", private=True)],
                 jots=[jot(id="r", text="私人小記")])
    day = line_view.day(data, "2026-11-06", None)
    assert day["events"][0]["private"] is True and day["tasks"][0]["private"] is True
    assert [j["text"] for j in day["jots"]] == ["私人小記"]


def test_month_includes_only_days_that_have_line_content_to_show():
    data = build(events=[all_day_event(id="x", startDate="2026-11-08", endDate="2026-11-09")])
    assert sorted(line_view.month(data, "2026-11", {})) == ["08", "09"]
    only_hidden_mood = build(moods=[mood(date="2026-11-12")])
    assert "12" in line_view.month(only_hidden_mood, "2026-11", {})                                 # LINE 的心情要顯示
    assert "12" not in line_view.month(only_hidden_mood, "2026-11", {"12": {"mood": "😄", "first": ""}})  # 我選了：LINE 的心情不顯示


def test_month_for_a_month_without_data_is_empty_and_rejects_bad_input():
    assert line_view.month(build(), "2026-11", {}) == {}
    with pytest.raises(ValueError, match="2026-13"):
        line_view.month(build(), "2026-13", {})


# ── 年 ──

def test_year_marks_line_only_days():
    data = build(events=[all_day_event(id="x", startDate="2026-11-08", endDate="2026-11-10")],
                 moods=[mood(date="2026-11-06", face="smile")])
    year = line_view.year(data, "2026", {})
    assert year["11"]["06"] == {"source": "line", "emoji": "🙂"}                                  # LINE 的心情（虛線外框）
    assert year["11"]["08"] == {"source": "items", "emoji": ""} and sorted(year["11"]) == ["06", "08", "09", "10"]  # 只有事項（小圓點）


def test_year_leaves_days_where_my_mood_shows_to_the_page():
    data = build(moods=[mood(date="2026-11-06", face="smile")])
    assert line_view.year(data, "2026", {"11": {"06": "😄"}}) == {}
    assert line_view.year(data, "2026", {"11": {"06": ""}})["11"]["06"]["source"] == "line"      # 我那天有日記但沒選表情


def test_year_ignores_other_years():
    data = build(events=[all_day_event(id="x", startDate="2026-12-31", endDate="2027-01-02")])
    assert sorted(line_view.year(data, "2026", {})) == ["12"] and sorted(line_view.year(data, "2027", {})) == ["01"]


# ── 日 ──

def test_day_lists_every_jot_in_created_order_with_clock_times():
    jots = line_view.day(busy_day(), "2026-11-06", None)["jots"]
    assert [(j["time"], j["text"]) for j in jots] == [("09:05", "吃蛋糕"), ("14:32", "看到貓")]


def test_logs_show_title_and_details_when_present():
    logs = line_view.day(busy_day(), "2026-11-06", None)["logs"]
    items = [{"title": "寫程式", "details": "完成解析"}, {"title": "散步", "details": None}]
    assert logs == [{"private": False, "group": None, "items": items}]


def test_multi_day_event_is_labelled_per_day():
    trip = build(events=[all_day_event(id="trip", startDate="2026-11-08", endDate="2026-11-10")])
    labels = [line_view.day(trip, f"2026-11-{d}", None)["events"][0]["when"] for d in ("08", "09", "10")]
    assert labels == ["整天（第 1 天／共 3 天）", "整天（第 2 天／共 3 天）", "整天（第 3 天／共 3 天）"]
    night = build(events=[event(id="n", title="夜間", start="2026-11-06T22:00:00+08:00", end="2026-11-07T02:00:00+08:00",
                                startDate="2026-11-06", endDate="2026-11-07")])
    assert line_view.day(night, "2026-11-06", None)["events"][0]["when"] == "22:00 起（第 1 天／共 2 天）"
    assert line_view.day(night, "2026-11-07", None)["events"][0]["when"] == "至 02:00（第 2 天／共 2 天）"


def test_single_day_event_times():
    when = {e["title"]: e["when"] for e in line_view.day(busy_day(), "2026-11-06", None)["events"]}
    assert when == {"生日": "整天", "早餐": "09:00–09:30", "開會": "10:00–11:00"}
    open_ended = build(events=[event(id="o", end=None)])
    assert line_view.day(open_ended, "2026-11-06", None)["events"][0]["when"] == "10:00"
    timeless = build(events=[event(id="o", start=None, end=None)])
    assert line_view.day(timeless, "2026-11-06", None)["events"][0]["when"] == ""


def test_day_event_keeps_id_and_details():
    first = line_view.day(busy_day(), "2026-11-06", None)["events"][2]
    assert (first["id"], first["location"], first["note"], first["group"]) == ("e1", "會議室", "帶筆電", "工作群")


def test_day_without_anything_is_empty_but_well_formed():
    empty = line_view.day(build(), "2026-11-20", None)
    assert empty == {"mood": {"source": None, "emoji": "", "text": None}, "events": [], "tasks": [], "logs": [], "jots": [], "empty": True}
    assert line_view.day(busy_day(), "2026-11-06", None)["empty"] is False


def test_undated_tasks_are_not_shown_on_any_day():
    data = build(tasks=[task(id="u", title="沒截止", dueDate=None, dueTime=None)])
    assert line_view.month(data, "2026-11", {}) == {} and line_view.day(data, "2026-11-06", None)["tasks"] == []


# ── 一般 ──

def test_view_never_mutates_the_data_or_the_diary_arguments():
    data, mine = busy_day(), {"mood": "", "note": "x", "first": "", "images": ["a.jpg"]}
    before, mine_before = copy.deepcopy(data.to_payload()), copy.deepcopy(mine)
    line_view.month(data, "2026-11", {"06": mine})
    line_view.year(data, "2026", {"11": {"06": ""}})
    line_view.day(data, "2026-11-06", mine)
    assert data.to_payload() == before and mine == mine_before


def test_view_output_is_json_serializable():
    data = busy_day()
    json.dumps(line_view.month(data, "2026-11", {}))
    json.dumps(line_view.year(data, "2026", {}))
    json.dumps(line_view.day(data, "2026-11-06", None))


def test_text_is_passed_through_exactly_as_plain_strings():
    nasty = "<img src=x onerror=alert(1)> \"q\" </script>"
    data = build(events=[event(id="x", title=nasty, note=nasty)], jots=[jot(id="y", text=nasty)], moods=[mood(text=nasty)])
    day = line_view.day(data, "2026-11-06", None)
    assert day["events"][0]["title"] == nasty and day["jots"][0]["text"] == nasty and day["mood"]["text"] == nasty
    assert "<img" in line_view.month(data, "2026-11", {})["06"]["lines"][0]["text"]  # 沒有被改成別的（顯示那一頭用 textContent）


def test_mood_of_returns_the_raw_line_mood_even_when_my_face_hides_it_on_screen():
    data = busy_day()
    assert line_view.mood_of(data, "2026-11-06") == {"emoji": "🙂", "text": "還不錯"}
    assert line_view.mood_of(data, "2026-11-07") is None
    assert line_view.day(data, "2026-11-06", {"mood": "😢"})["mood"]["source"] == "mine"  # 畫面上藏起來了，但複製要用原本的
