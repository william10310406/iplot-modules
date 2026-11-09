"""LINE 資料的解析（docs/01_設計.md 第 4.3 節，L06）：version 1、型別嚴格、不認得的欄位忽略、台北時間、整天活動含最後一天。"""

import copy
import json
import os
import time

import pytest
from support import all_day_event, event, jot, line_payload, log, mood, task

import diary
import line_data

# 每一區必要的欄位與型別；"str"、"bool"、"date"、"items"、"face" 是型別名稱，"?str" 是 字串或 null
REQUIRED = {
    "events": {"id": "str", "title": "str", "allDay": "bool", "startDate": "date", "endDate": "date", "private": "bool"},
    "tasks": {"id": "str", "title": "str", "done": "bool", "private": "bool"},
    "logs": {"date": "date", "private": "bool", "items": "items"},
    "moods": {"date": "date", "face": "face"},
    "jots": {"id": "str", "date": "date", "text": "str", "createdAt": "datetime"},
}
NULLABLE = {
    "events": ("start", "end", "location", "note", "group"),
    "tasks": ("dueDate", "dueTime", "note", "group"),
    "logs": ("group",),
    "moods": ("text",),
    "jots": (),
}
BAD = {
    "str": [None, 1, 1.5, True, [], {}],
    "bool": [None, 0, 1, "true", "yes", [], {}],
    "date": [None, 20261101, "2026-02-30", "2026-13-01", "20261101", "2026-1-1", "", "2026/11/01", [], True],
    "items": [None, "x", {}, 1, [1], [{}], [{"title": 1}], [{"title": "a", "details": 1}]],
    "face": [None, 1, "happy", "SMILE", "", [], "😄"],
    "datetime": [None, 1, "", "yesterday", "2026-11-06", "2026-11-06T14:32:00", "2026-11-06 14:32:00+08:00", [], {}],
}
SAMPLE = {"events": event, "tasks": task, "logs": log, "moods": mood, "jots": jot}


def _payload_with(section, **changes):
    payload = line_payload()
    payload[section] = [{**SAMPLE[section](), **changes}]
    return payload


def _one(parsed, section):
    return getattr(parsed, section)[0]


def test_parses_the_documented_example():
    parsed = line_data.parse(line_payload())
    assert (parsed.range_from, parsed.range_to) == ("2026-10-02", "2027-01-15")
    assert parsed.generated_at == "2026-11-06T16:40:00+08:00"
    assert [len(getattr(parsed, s)) for s in ("events", "tasks", "logs", "moods", "jots")] == [2, 3, 1, 1, 2]


def test_unknown_fields_are_ignored_at_every_level():
    plain = line_payload()
    noisy = copy.deepcopy(plain)
    noisy["將來才有"] = {"x": 1}
    noisy["range"]["tz"] = "?"
    for section in ("events", "tasks", "logs", "moods", "jots"):
        for item in noisy[section]:
            item["fromIPLoT"] = True
            item["未知"] = [1, {"a": None}]
    noisy["logs"][0]["items"][0]["icon"] = "x"
    assert line_data.parse(noisy).to_payload() == line_data.parse(plain).to_payload()


def test_unknown_top_level_section_is_ignored():
    payload = line_payload(photos=[{"id": "p"}], future=None)
    assert line_data.parse(payload).to_payload() == line_data.parse(line_payload()).to_payload()


@pytest.mark.parametrize("version", [0, 2, 99, -1, "1", 1.0 + 0.5, None, True, [1], {"v": 1}])
def test_version_not_1_is_rejected(version):
    with pytest.raises(line_data.VersionError):
        line_data.parse(line_payload(version=version))


def test_missing_version_is_rejected_and_version_error_carries_the_number():
    payload = line_payload()
    del payload["version"]
    with pytest.raises(line_data.VersionError):
        line_data.parse(payload)
    with pytest.raises(line_data.VersionError) as caught:
        line_data.parse(line_payload(version=2))
    assert caught.value.version == 2
    assert issubclass(line_data.VersionError, line_data.FormatError)


def _wrong_type_cases():
    for section, fields in REQUIRED.items():
        for field, kind in fields.items():
            for bad in BAD[kind]:
                yield pytest.param(section, field, bad, id=f"{section}.{field}={bad!r}")
    for section, fields in NULLABLE.items():
        for field in fields:
            for bad in (1, 1.5, True, [], {}):
                yield pytest.param(section, field, bad, id=f"{section}.{field}={bad!r}")


@pytest.mark.parametrize(("section", "field", "bad"), list(_wrong_type_cases()))
def test_wrong_types_are_rejected_per_section(section, field, bad):
    with pytest.raises(line_data.FormatError) as caught:
        line_data.parse(_payload_with(section, **{field: bad}))
    assert caught.value.section == section


@pytest.mark.parametrize("field", ["start", "end"])
@pytest.mark.parametrize("bad", ["", "tomorrow", "2026-11-06", "2026-11-06T10:00:00", "2026-11-06T25:00:00+08:00",
                                 "2026-11-06T10:00:00+25:00"])
def test_event_times_must_be_iso_with_an_offset(field, bad):
    with pytest.raises(line_data.FormatError):
        line_data.parse(_payload_with("events", **{field: bad}))


def test_wrong_types_inside_log_items_are_rejected_and_nullable_details_accepted():
    ok = line_payload(logs=[log(items=[{"title": "a", "details": None}, {"title": "b", "details": "x"}])])
    assert len(_one(line_data.parse(ok), "logs")["items"]) == 2
    with pytest.raises(line_data.FormatError):
        line_data.parse(line_payload(logs=[log(items=[{"details": "no title"}])]))


def test_nullable_fields_accept_null_and_may_be_missing():
    for section, fields in NULLABLE.items():
        for field in fields:
            nulled = _payload_with(section, **{field: None})
            assert _one(line_data.parse(nulled), section)[field] is None
            missing = line_payload()
            missing[section] = [{k: v for k, v in SAMPLE[section]().items() if k != field}]
            assert _one(line_data.parse(missing), section)[field] is None


@pytest.mark.parametrize("section", list(REQUIRED))
def test_missing_required_field_is_rejected(section):
    for field in REQUIRED[section]:
        payload = line_payload()
        payload[section] = [{k: v for k, v in SAMPLE[section]().items() if k != field}]
        with pytest.raises(line_data.FormatError) as caught:
            line_data.parse(payload)
        assert caught.value.section == section


@pytest.mark.parametrize("section", ["events", "tasks", "logs", "moods", "jots"])
def test_missing_or_non_list_section_is_rejected(section):
    missing = line_payload()
    del missing[section]
    with pytest.raises(line_data.FormatError) as caught:
        line_data.parse(missing)
    assert caught.value.section == section
    for bad in (None, {}, "x", 1):
        with pytest.raises(line_data.FormatError):
            line_data.parse(line_payload(**{section: bad}))
    for bad_item in (None, 1, "x", []):
        with pytest.raises(line_data.FormatError):
            line_data.parse(line_payload(**{section: [bad_item]}))


@pytest.mark.parametrize("range_value", [None, {}, {"from": "2026-10-02"}, {"to": "2026-10-02"}, {"from": 1, "to": 2},
                                         {"from": "2026-02-30", "to": "2026-03-01"}, "2026-10-02", [], {"from": "2026-10-02", "to": "x"}])
def test_range_must_be_two_valid_dates(range_value):
    with pytest.raises(line_data.FormatError) as caught:
        line_data.parse(line_payload(range=range_value))
    assert caught.value.section == "range"


def test_generated_at_is_optional_but_must_be_text_or_null():
    payload = line_payload()
    del payload["generatedAt"]
    assert line_data.parse(payload).generated_at is None
    assert line_data.parse(line_payload(generatedAt=None)).generated_at is None
    with pytest.raises(line_data.FormatError):
        line_data.parse(line_payload(generatedAt=5))


def test_face_is_one_of_the_five_and_the_emoji_field_is_ignored():
    for face, emoji in line_data.FACES.items():
        parsed = line_data.parse(line_payload(moods=[mood(face=face, emoji="X")]))
        assert _one(parsed, "moods")["emoji"] == emoji
    assert tuple(line_data.FACES.values()) == diary.MOODS  # 跟 diary.py 的五個表情一樣、順序也一樣
    assert list(line_data.FACES) == ["grin", "smile", "neutral", "worried", "cry"]


def test_invalid_dates_are_rejected_everywhere_a_date_is_expected():
    for section, field in (("events", "startDate"), ("events", "endDate"), ("tasks", "dueDate"), ("logs", "date"),
                           ("moods", "date"), ("jots", "date")):
        with pytest.raises(line_data.FormatError):
            line_data.parse(_payload_with(section, **{field: "2026-02-30"}))
    assert line_data.parse(_payload_with("tasks", dueDate="2028-02-29"))  # 閏日是真的日子


def test_ids_and_all_known_fields_are_kept_verbatim():
    payload = line_payload()
    parsed = line_data.parse(payload)
    assert parsed.events == payload["events"]
    assert parsed.tasks == payload["tasks"]
    assert parsed.logs == payload["logs"]
    assert parsed.moods == payload["moods"]
    assert [j["id"] for j in parsed.jots] == ["j2", "j1"]  # 小記照 createdAt 排；內容一個字沒變
    assert {j["id"]: j for j in parsed.jots} == {j["id"]: j for j in payload["jots"]}


def test_task_without_due_date_is_kept_but_has_no_day():
    parsed = line_data.parse(line_payload())
    undated = [t for t in parsed.tasks if t["dueDate"] is None]
    assert [t["id"] for t in undated] == ["t3"]
    assert line_data.task_day(undated[0]) is None
    assert line_data.task_day(parsed.tasks[0]) == "2026-11-06"


def test_jots_are_ordered_by_created_at_across_offsets():
    payload = line_payload(jots=[
        jot(id="a", createdAt="2026-11-06T10:00:00+08:00"),      # 02:00 UTC
        jot(id="b", createdAt="2026-11-06T01:30:00+00:00"),      # 01:30 UTC：比 a 早，雖然字串排序在前面
        jot(id="c", createdAt="2026-11-06T09:00:00+08:00"),      # 01:00 UTC
    ])
    assert [j["id"] for j in line_data.parse(payload).jots] == ["c", "b", "a"]


def test_text_fields_are_kept_exactly_as_given():
    nasty = "<script>alert(1)</script> \"quote\" 'q' \\ \n 第二行 " + chr(0x2028) + " </script>"
    parsed = line_data.parse(line_payload(jots=[jot(text=nasty)], moods=[mood(text=nasty)],
                                          events=[event(title=nasty, note=nasty, location=nasty)]))
    assert _one(parsed, "jots")["text"] == nasty
    assert _one(parsed, "moods")["text"] == nasty
    assert _one(parsed, "events")["title"] == nasty and _one(parsed, "events")["note"] == nasty


def test_to_payload_roundtrips_through_json_and_parse():
    parsed = line_data.parse(line_payload())
    again = line_data.parse(json.loads(json.dumps(parsed.to_payload())))
    assert again.to_payload() == parsed.to_payload()
    assert parsed.to_payload()["version"] == 1


# ── 時區與整天活動 ──

def test_all_day_event_includes_the_last_day():
    ev = all_day_event(startDate="2026-11-08", endDate="2026-11-10")
    assert line_data.event_days(ev) == ["2026-11-08", "2026-11-09", "2026-11-10"]  # endDate 含最後一天（跟 ICS 的 DTEND 不同）
    assert line_data.event_days(all_day_event(startDate="2026-11-08", endDate="2026-11-08")) == ["2026-11-08"]


def test_all_day_event_has_no_clock_times():
    span = line_data.event_span(all_day_event())
    assert span.all_day is True and span.start is None and span.end is None
    assert (span.first, span.last) == ("2026-11-08", "2026-11-10")


def test_all_day_event_crossing_a_month_and_year_boundary():
    ev = all_day_event(startDate="2026-12-30", endDate="2027-01-02")
    assert line_data.event_days(ev) == ["2026-12-30", "2026-12-31", "2027-01-01", "2027-01-02"]


def test_timed_event_uses_taipei_time_regardless_of_the_machine_timezone():
    ev = event(start="2026-11-06T20:30:00+00:00", end="2026-11-06T21:30:00+00:00", startDate="2026-11-06", endDate="2026-11-06")
    old = os.environ.get("TZ")
    try:
        for zone in ("America/Los_Angeles", "Asia/Tokyo", "UTC"):
            os.environ["TZ"] = zone
            time.tzset()
            span = line_data.event_span(ev)
            assert (span.first, span.start, span.last, span.end) == ("2026-11-07", "04:30", "2026-11-07", "05:30")
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def test_event_crossing_midnight_appears_on_both_days():
    ev = event(start="2026-11-06T22:00:00+08:00", end="2026-11-07T02:00:00+08:00", startDate="2026-11-06", endDate="2026-11-07")
    assert line_data.event_days(ev) == ["2026-11-06", "2026-11-07"]
    span = line_data.event_span(ev)
    assert (span.first, span.start, span.last, span.end) == ("2026-11-06", "22:00", "2026-11-07", "02:00")


def test_event_ending_exactly_at_midnight_does_not_spill_to_the_next_day():
    ev = event(start="2026-11-06T22:00:00+08:00", end="2026-11-07T00:00:00+08:00", startDate="2026-11-06", endDate="2026-11-07")
    assert line_data.event_days(ev) == ["2026-11-06"]


def test_timed_event_without_an_end_is_a_single_day():
    ev = event(end=None)
    assert line_data.event_days(ev) == ["2026-11-06"]
    assert line_data.event_span(ev).end is None


def test_timed_event_without_a_start_falls_back_to_its_dates_without_clock_times():
    ev = event(start=None, end=None, startDate="2026-11-06", endDate="2026-11-07")
    assert line_data.event_days(ev) == ["2026-11-06", "2026-11-07"]
    assert line_data.event_span(ev).start is None


def test_end_before_start_is_treated_as_one_day():
    assert line_data.event_days(all_day_event(startDate="2026-11-10", endDate="2026-11-08")) == ["2026-11-10"]
    ev = event(start="2026-11-06T10:00:00+08:00", end="2026-11-05T09:00:00+08:00", startDate="2026-11-06", endDate="2026-11-05")
    assert line_data.event_days(ev) == ["2026-11-06"]


def test_event_span_is_capped_at_400_days():
    days = line_data.event_days(all_day_event(startDate="2020-01-01", endDate="2026-12-31"))
    assert len(days) == 400 and days[0] == "2020-01-01"


def test_offsets_other_than_plus_8_and_z_and_fractional_seconds_are_understood():
    for stamp, expect in (("2026-11-06T00:30:00Z", "08:30"), ("2026-11-06T00:30:00.123+00:00", "08:30"),
                          ("2026-11-06T08:30:00.5+08:00", "08:30"), ("2026-11-05T19:30-05:00", "08:30")):
        span = line_data.event_span(event(start=stamp, end=None, startDate="2026-11-06", endDate="2026-11-06"))
        assert span.start == expect, stamp


def test_taipei_helper_returns_date_and_clock():
    assert line_data.taipei("2026-11-06T23:59:59-08:00") == ("2026-11-07", "15:59")
    with pytest.raises(line_data.FormatError):
        line_data.taipei("nope")


# ── 壞資料 ──

@pytest.mark.parametrize("junk", [None, [], "x", 1, 1.5, True, [{"version": 1}], b"{}", set()])
def test_garbage_top_level_is_a_format_error(junk):
    with pytest.raises(line_data.FormatError) as caught:
        line_data.parse(junk)
    assert caught.value.section == "root"


def test_deeply_nested_and_huge_junk_never_raises_anything_but_format_error():
    deep = current = {}
    for _ in range(500):
        current["x"] = {}
        current = current["x"]
    huge = [{"id": str(i)} for i in range(20000)]
    base = line_payload()  # 不經 line_payload(**over)：它會深拷貝覆蓋的值，500 層的 dict 連拷貝都做不了
    for junk in ({**base, "events": huge}, {**base, "tasks": [deep]}, {**base, "extra": deep}, {"version": 1, "x": deep}):
        try:
            line_data.parse(junk)
        except line_data.FormatError:
            pass


def test_format_errors_never_echo_the_data():
    secret = "SECRET-TEXT-" + "x" * 30
    for bad in (_payload_with("jots", text=secret, createdAt=secret), _payload_with("events", id=secret, title=5),
                line_payload(version=secret), line_payload(range={"from": secret, "to": secret})):
        with pytest.raises(line_data.FormatError) as caught:
            line_data.parse(bad)
        assert secret not in str(caught.value) and secret not in repr(caught.value)


def test_parse_does_not_modify_its_input():
    payload = line_payload()
    snapshot = copy.deepcopy(payload)
    line_data.parse(payload)
    assert payload == snapshot
