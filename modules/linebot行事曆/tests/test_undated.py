"""沒有截止日的待辦（docs/01_設計.md L16）：月檢視底下一條唯讀的清單。

它不屬於任何一天，所以：不進月格、年檢視、日檢視；不複製進日記；不進網頁。"""

import json

import pytest
from support import FAKE_URL, SENTINEL, FakeLine, event, jot, line_payload, mood, task

import diary
import line_data
import line_view

DATE = "2026-11-06"


def build(**sections):
    base = {"events": [], "tasks": [], "logs": [], "moods": [], "jots": []}
    return line_data.parse(line_payload(range={"from": "2026-10-01", "to": "2026-12-31"}, **{**base, **sections}))


def undated(**over):
    return task(dueDate=None, dueTime=None, **over)


# ── line_view.undated ──

def test_nothing_is_listed_when_there_are_no_tasks_or_only_dated_ones():
    assert line_view.undated(build()) == []
    assert line_view.undated(build(tasks=[task(id="a", dueDate=DATE)])) == []


def test_only_unfinished_tasks_without_a_due_date_are_listed_in_the_order_given():
    data = build(tasks=[undated(id="u2", title="第二件"), task(id="d1", title="有日期", dueDate=DATE),
                        undated(id="u1", title="第一件"), undated(id="u3", title="做完了", done=True)])
    assert [item["id"] for item in line_view.undated(data)] == ["u2", "u1"]


def test_each_row_carries_exactly_what_the_page_shows():
    data = build(tasks=[undated(id="u1", title="買牛奶", private=True, group=None, note="兩罐"),
                        undated(id="u2", title="準備報告", private=False, group="社團", note=None)])
    assert line_view.undated(data) == [
        {"id": "u1", "title": "買牛奶", "private": True, "group": None, "note": "兩罐"},
        {"id": "u2", "title": "準備報告", "private": False, "group": "社團", "note": None}]


def test_a_time_without_a_date_is_still_undated_and_the_time_is_not_shown():
    row = line_view.undated(build(tasks=[task(id="u1", title="怪", dueDate=None, dueTime="09:00")]))[0]
    assert row["title"] == "怪" and "time" not in row and "dueTime" not in row


def test_text_is_passed_through_as_plain_strings_and_the_result_is_json():
    nasty = "<img src=x onerror=alert(1)> \"q\" </script>"
    rows = line_view.undated(build(tasks=[undated(id="u1", title=nasty, note=nasty)]))
    assert rows[0]["title"] == nasty and rows[0]["note"] == nasty
    json.dumps(rows)


def test_undated_does_not_change_the_data_it_reads():
    data = build(tasks=[undated(id="u1")])
    before = data.to_payload()
    line_view.undated(data)
    assert data.to_payload() == before


def test_undated_tasks_do_not_appear_in_any_day_month_or_year():
    data = build(tasks=[undated(id="u1", title="沒日期")], events=[event(id="e1", title="開會")], moods=[mood(date=DATE)])
    assert "沒日期" not in json.dumps(line_view.month(data, "2026-11", {}), ensure_ascii=False)
    assert "沒日期" not in json.dumps(line_view.day(data, DATE, None), ensure_ascii=False)
    assert "沒日期" not in json.dumps(line_view.year(data, "2026", {}), ensure_ascii=False)
    only = build(tasks=[undated(id="u1")])
    assert line_view.month(only, "2026-11", {}) == {} and line_view.year(only, "2026", {}) == {}
    assert line_view.day(only, DATE, None)["empty"] is True


# ── Api.month ──

def payload(**sections):
    base = {"events": [], "tasks": [], "logs": [], "moods": [], "jots": []}
    return line_payload(range={"from": "2026-10-04", "to": "2027-01-17"}, **{**base, **sections})


def with_undated(make_api, **kw):
    fetch = FakeLine()
    fetch.script = [payload(tasks=[undated(id="u1", title=f"{SENTINEL} 買牛奶", private=True), undated(id="u2", title="寄信", group="社團"),
                                   task(id="d1", title="有日期", dueDate=DATE)],
                            jots=[jot(id="j1", date=DATE, text="看到貓", createdAt=f"{DATE}T14:32:00+08:00")])]
    return make_api(url=FAKE_URL, fetch=fetch, **kw)


def test_month_returns_the_undated_list_next_to_line_not_inside_it(make_api):
    h = with_undated(make_api)
    month = h.api.month("2026-11")
    assert [row["id"] for row in month["line_undated"]] == ["u1", "u2"]
    assert month["line_undated"][0]["private"] is True and month["line_undated"][1]["group"] == "社團"
    assert sorted(month["line"]) == ["06"] and SENTINEL not in json.dumps(month["line"], ensure_ascii=False)
    json.dumps(month)


def test_the_list_is_the_same_for_every_month_it_is_not_tied_to_a_month(make_api):
    h = with_undated(make_api)
    assert h.api.month("2026-11")["line_undated"] == h.api.month("2026-12")["line_undated"] != []


def test_without_a_url_or_without_data_the_list_is_empty(make_api):
    h = make_api()
    assert h.api.month("2026-11")["line_undated"] == []
    fetch = FakeLine()
    fetch.script = [payload()]
    assert make_api(url=FAKE_URL, fetch=fetch).api.month("2026-11")["line_undated"] == []


def test_day_and_year_do_not_carry_the_undated_list(make_api):
    h = with_undated(make_api)
    assert "line_undated" not in h.api.day(DATE) and "line_undated" not in h.api.year("2026")
    assert SENTINEL not in json.dumps([h.api.day(DATE), h.api.year("2026")], ensure_ascii=False)


def test_clearing_the_url_empties_the_list(make_api):
    h = with_undated(make_api)
    assert h.api.month("2026-11")["line_undated"]
    h.api.line_clear()
    assert h.api.month("2026-11")["line_undated"] == []


# ── 不進日記、不進網頁 ──

def files_with(root, needle):
    return sorted(p.name for p in root.rglob("*") if p.is_file() and needle.encode() in p.read_bytes())


def test_manual_copy_never_copies_an_undated_task(make_api):
    h = with_undated(make_api)
    h.api.month("2026-11")
    for date in (DATE, "2026-11-07", "2026-11-08"):
        preview = h.api.line_copy_preview(date)
        assert SENTINEL not in json.dumps(preview, ensure_ascii=False)
        if not preview.get("empty"):
            h.api.line_copy(date, preview["digest"])
    assert files_with(h.root, SENTINEL) == []


def test_auto_copy_never_copies_an_undated_task(make_api):
    h = with_undated(make_api)
    h.api.month("2026-11")
    h.api.line_set_auto(True)
    h.sync.on_open()
    assert files_with(h.root, SENTINEL) == []


def test_private_and_published_pages_never_contain_an_undated_task(make_api):
    import pages
    h = with_undated(make_api)
    h.api.month("2026-11")
    diary.save_day(h.root, DATE, {"行程": "我的行程"}, 20)
    h.api.set_public(DATE, True)
    for public in (False, True):
        for text in (pages.render_day(h.root, DATE, public=public), pages.render_month(h.root, "2026-11", public=public),
                     pages.render_year(h.root, "2026", public=public), pages.render_index(h.root, public=public)):
            assert SENTINEL not in text
    h.api.publish()
    h.api.rebuild()
    assert files_with(h.root, SENTINEL) == []


# ── 頁面 ──

def page_text():
    import support
    return (support.MODULE / "page.html").read_text(encoding="utf-8")


def test_the_page_draws_the_list_from_the_month_reply_with_el_and_never_innerhtml():
    page = page_text()
    assert "line_undated" in page and "innerHTML" not in page and "insertAdjacentHTML" not in page


@pytest.mark.parametrize("needle", ["沒有日期的待辦", "還有", "收起"])
def test_the_page_has_the_words_for_the_strip(needle):
    assert needle in page_text()
