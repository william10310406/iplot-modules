"""iplot.Api 的 LINE 部分：月、年、日帶 LINE 的資料、狀態、貼網址、複製進日記、自動複製（docs/01_設計.md 第 5–7 節）。

用 conftest 的 make_api：假 app、tmp 的日記資料夾、假的 LINE（同步執行，不開執行緒、不連網）。"""

import datetime
import json
import stat
import threading

import pytest
from support import FAKE_TOKEN, FAKE_URL, Clock, FakeLine, all_day_event, event, jot, line_payload, log, mood, taipei_ts, task

import diary
import line_net
import line_url

DATE = "2026-11-06"


def payload(**sections):
    base = {"events": [], "tasks": [], "logs": [], "moods": [], "jots": []}
    return line_payload(range={"from": "2026-10-04", "to": "2027-01-17"}, **{**base, **sections})


def sample():
    return payload(events=[event(id="e1", title="開會", start=f"{DATE}T10:00:00+08:00", end=f"{DATE}T11:00:00+08:00"),
                           all_day_event(id="e2", title="出差", startDate="2026-11-08", endDate="2026-11-10")],
                   tasks=[task(id="t1", title="買牛奶", dueDate=DATE, dueTime="18:00")],
                   jots=[jot(id="j1", date=DATE, text="看到貓", createdAt=f"{DATE}T14:32:00+08:00")],
                   logs=[log(date=DATE)], moods=[mood(date=DATE, face="smile", text="還不錯")])


def with_data(make_api, **kw):
    fetch = FakeLine()
    fetch.script = [sample()]
    return make_api(url=FAKE_URL, fetch=fetch, **kw)


# ── 月、年、日 ──

def test_month_year_day_carry_a_line_section_with_the_cached_data(make_api):
    h = with_data(make_api)
    month = h.api.month("2026-11")
    assert month["ym"] == "2026-11" and month["days"] == {} and month["folder"] == str(h.root)    # 原本的部分照舊
    cell = month["line"]["06"]
    assert cell["count"] == 2 and [row["text"] for row in cell["lines"]] == ["10:00 開會", "18:00 買牛奶"]
    assert cell["mood"] == {"source": "line", "emoji": "🙂", "text": "還不錯"} and sorted(month["line"]) == ["06", "08", "09", "10"]
    day = h.api.day(DATE)
    assert day["date"] == DATE and day["images"] == [] and day["行程"] == ""                         # 原本的部分照舊
    assert [e["title"] for e in day["line"]["events"]] == ["開會"] and day["line"]["jots"][0]["text"] == "看到貓"
    year = h.api.year("2026")
    assert year["y"] == "2026" and year["months"] == {} and year["line"]["11"]["06"] == {"source": "line", "emoji": "🙂"}
    json.dumps([month, day, year])                                                                   # 都能給頁面


def test_the_first_month_call_opens_once_and_later_calls_do_not_refetch(make_api):
    h = with_data(make_api)
    h.api.month("2026-11")
    h.api.month("2026-12")
    h.api.month("2026-11")
    h.api.day(DATE)
    assert h.fetch.calls == [(None, None)]


def test_a_month_outside_the_default_range_fetches_just_that_month(make_api):
    h = with_data(make_api)
    h.api.month("2026-11")
    h.api.month("2027-03")
    assert h.fetch.calls == [(None, None), ("2027-03-01", "2027-03-31")]


def test_a_day_in_an_uncached_month_fetches_that_month_and_a_year_fetches_its_gaps(make_api):
    h = with_data(make_api)
    h.api.month("2026-11")
    h.api.day("2027-04-10")
    assert h.fetch.calls[-1] == ("2027-04-01", "2027-04-30")
    h.api.year("2026")
    assert all(call != (None, None) for call in h.fetch.calls[2:]) and 1 <= len(h.fetch.calls) - 2 <= 4


def test_without_a_url_everything_works_as_before_and_nothing_touches_the_network(make_api):
    h = make_api()
    diary.save_day(h.root, DATE, {"行程": "我的行程", "心情": diary.mood_text("😄", "好")}, 20)
    month, day, year = h.api.month("2026-11"), h.api.day(DATE), h.api.year("2026")
    assert month["days"]["06"]["mood"] == "😄" and month["line"] == {} and day["line"]["empty"] is True and year["line"] == {}
    assert day["行程"] == "我的行程" and year["months"]["11"] == {"06": "😄"}
    assert h.fetch.calls == [] and not h.cache.exists()


def test_my_face_hides_the_line_mood_in_the_day_and_the_month(make_api):
    h = with_data(make_api)
    diary.save_day(h.root, DATE, {"心情": diary.mood_text("😢", "")}, 20)
    assert h.api.day(DATE)["line"]["mood"] == {"source": "mine", "emoji": "😢", "text": None}
    assert h.api.month("2026-11")["line"]["06"]["mood"]["source"] == "mine"
    assert "06" not in h.api.year("2026")["line"].get("11", {})


def test_my_first_line_replaces_the_line_rows_in_the_month_cell(make_api):
    h = with_data(make_api)
    diary.save_day(h.root, DATE, {"行程": "我寫的"}, 20)
    cell = h.api.month("2026-11")["line"]["06"]
    assert cell["lines"] == [] and cell["count"] == 2


def test_viewing_tracks_the_open_day_and_is_cleared_by_month_and_year(make_api):
    h = make_api()
    assert h.api._viewing is None
    h.api.day(DATE)
    assert h.api._viewing == DATE
    h.api.month("2026-11")
    assert h.api._viewing is None
    h.api.day(DATE)
    h.api.year("2026")
    assert h.api._viewing is None


def test_data_errors_in_line_never_break_the_calendar(make_api):
    fetch = FakeLine()
    fetch.script = [line_net.LineError("offline", "連不上 LINE（沒有網路）")]
    h = make_api(url=FAKE_URL, fetch=fetch)
    diary.save_day(h.root, DATE, {"行程": "我的"}, 20)
    month, day = h.api.month("2026-11"), h.api.day(DATE)
    assert month["days"]["06"]["first"] == "我的" and month["line"] == {} and day["行程"] == "我的"
    assert "連不上 LINE" in h.api.line_state()["message"]


# ── 狀態 ──

def test_line_state_fields_and_never_the_full_url(make_api):
    h = make_api()
    state = h.api.line_state()
    assert state["configured"] is False and state["auto_copy"] is False and state["auto_message"] == "" and state["diary_version"] == 0
    assert "還沒設定" in state["message"]
    h = with_data(make_api)
    h.api.month("2026-11")
    state = h.api.line_state()
    assert state["configured"] is True and state["last"]["ok"] is True and state["last_ok_at"] == h.clock.now
    dumped = json.dumps(state)
    assert FAKE_TOKEN not in dumped and FAKE_URL not in dumped and state["masked_url"] == line_url.mask(FAKE_URL)


def test_line_refresh_fetches_again_and_returns_the_full_state(make_api):
    h = with_data(make_api)
    h.api.month("2026-11")
    state = h.api.line_refresh()
    assert len(h.fetch.calls) == 2 and state["last"]["ok"] is True and "auto_copy" in state and "diary_version" in state


# ── 貼網址、清除 ──

def test_line_set_url_rejects_bad_urls_without_echoing_them(make_api):
    h = make_api()
    for bad in ("http://x.example.test/j/" + "a" * 40 + ".json", "SECRET-PASTE 隨便貼", ""):
        result = h.api.line_set_url(bad)
        assert result == {"error": line_url.BAD_URL_MESSAGE} and "SECRET" not in json.dumps(result)
    assert h.api.line_state()["configured"] is False and h.fetch.calls == []


def test_line_set_url_stores_it_fetches_and_returns_only_the_masked_url(make_api):
    h = make_api()
    result = h.api.line_set_url(f"  {FAKE_URL}\n")
    assert result["configured"] is True and result["masked_url"] == line_url.mask(FAKE_URL)
    assert FAKE_TOKEN not in json.dumps(result) and h.fetch.calls == [(None, None)]
    assert json.loads(h.settings.read_text(encoding="utf-8"))["LINE"]["url"] == FAKE_URL
    assert stat.S_IMODE(h.settings.stat().st_mode) == 0o600


def test_line_set_url_reports_a_settings_file_that_cannot_be_written(make_api, monkeypatch):
    h = make_api()

    def broken(*args, **kwargs):
        raise OSError(13, "Permission denied", str(h.settings))

    monkeypatch.setattr("settings.write_private", broken)
    result = h.api.line_set_url(FAKE_URL)
    assert "error" in result and FAKE_TOKEN not in json.dumps(result) and str(h.module) not in json.dumps(result)


def test_line_clear_removes_the_url_and_the_cache(make_api):
    h = with_data(make_api)
    h.api.month("2026-11")
    assert h.cache.exists()
    state = h.api.line_clear()
    assert state["configured"] is False and not h.cache.exists() and h.api.month("2026-11")["line"] == {}
    assert "url" not in json.loads(h.settings.read_text(encoding="utf-8")).get("LINE", {})


# ── 複製進日記：手動 ──

def preview(h, date=DATE):
    return h.api.line_copy_preview(date)


def test_preview_writes_nothing_and_describes_what_would_be_added(make_api):
    h = with_data(make_api)
    h.api.month("2026-11")
    before = sorted(p for p in h.root.rglob("*"))
    result = preview(h)
    assert sorted(p for p in h.root.rglob("*")) == before and not h.ledger.exists()
    assert result["empty"] is False and result["public"] is False and result["date"] == DATE and len(result["digest"]) == 64
    assert "10:00–11:00 開會" in result["additions"]["行程"] and "☐ 買牛奶（截止 18:00）" in result["additions"]["行程"]
    assert result["additions"]["看到"].endswith("14:32 看到貓\n") and result["mood"] == {"mood": "🙂", "note": "還不錯"}
    assert result["skipped"] == {"private": 0, "already": 0, "public_day": False, "unreadable": []}
    json.dumps(result)


def test_copy_with_the_previewed_digest_writes_the_diary_and_records_it(make_api):
    h = with_data(make_api)
    h.api.month("2026-11")
    diary.save_day(h.root, DATE, {"行程": "我的行程"}, 20)
    result = h.api.line_copy(DATE, preview(h)["digest"])
    assert result["copied"] > 0 and result["warning"] is None and set(result["changed"]) >= {"行程", "看到", "做了", "心情"}
    day = diary.read_day(h.root, DATE)
    assert day["行程"].startswith("我的行程\n\n── 從 LINE 複製 2026-11-08 21:45 ──\n") and "開會" in day["行程"]
    assert day["mood"] == "🙂" and day["note"] == "還不錯"
    history = diary.day_folder(h.root, DATE) / diary.HISTORY
    assert [p.read_text(encoding="utf-8") for p in history.glob("行程-*.txt")] == ["我的行程"]        # 複製之前的原文找得回
    assert (diary.day_folder(h.root, DATE) / "index.html").exists()
    assert preview(h)["empty"] is True                                                              # 再按沒有新內容
    assert h.api.day(DATE)["行程"] == day["行程"] and h.api.day(DATE)["line"]["events"]              # LINE 的唯讀區照樣在


def test_copy_refuses_a_stale_digest_and_writes_nothing(make_api):
    h = with_data(make_api)
    h.api.month("2026-11")
    old = preview(h)["digest"]
    diary.save_day(h.root, DATE, {"行程": "預覽之後我又改了"}, 20)
    result = h.api.line_copy(DATE, old)
    assert result == {"error": "內容有變，請重新預覽"} and diary.read_day(h.root, DATE)["行程"] == "預覽之後我又改了"
    assert not h.ledger.exists()
    for wrong in ("x" * 64, None, 5, ""):
        assert h.api.line_copy(DATE, wrong) == {"error": "內容有變，請重新預覽"}


def test_copy_on_a_public_day_warns_and_skips_private_items(make_api):
    fetch = FakeLine()
    fetch.script = [payload(events=[event(id="p", title="私人活動", private=True), event(id="g", title="公開活動")])]
    h = make_api(url=FAKE_URL, fetch=fetch)
    h.api.month("2026-11")
    diary.set_public(h.root, DATE, True)
    result = preview(h)
    assert result["public"] is True and result["skipped"]["private"] == 1 and "私人活動" not in result["additions"]["行程"]
    h.api.line_copy(DATE, result["digest"])
    assert "私人活動" not in diary.read_day(h.root, DATE)["行程"] and "公開活動" in diary.read_day(h.root, DATE)["行程"]


def test_copy_reports_a_diary_that_cannot_be_written_without_the_path(make_api, monkeypatch):
    h = with_data(make_api)
    h.api.month("2026-11")
    digest = preview(h)["digest"]

    def broken(*args, **kwargs):
        raise OSError(28, "No space left on device", str(h.root))

    monkeypatch.setattr(diary, "save_day", broken)
    result = h.api.line_copy(DATE, digest)
    assert "error" in result and str(h.root) not in json.dumps(result) and not h.ledger.exists()


def test_preview_and_copy_reject_bad_dates(make_api):
    h = with_data(make_api)
    for bad in ("2026-02-30", "x", None, 20261106):
        assert "error" in h.api.line_copy_preview(bad) and "error" in h.api.line_copy(bad, "x")


def test_copy_with_nothing_from_line_is_an_empty_preview(make_api):
    h = make_api()
    assert preview(h)["empty"] is True and h.api.line_copy(DATE, preview(h)["digest"])["copied"] == 0


# ── 自動複製 ──

def auto_api(make_api, *, dates=("2026-11-08",), **kw):
    """今天是 2026-11-09 00:10，打開行事曆。LINE 在 dates 這幾天有內容。"""
    fetch = FakeLine(today="2026-11-09")
    fetch.script = [payload(events=[event(id=f"e-{d}", title=f"活動 {d}", start=f"{d}T10:00:00+08:00", end=f"{d}T11:00:00+08:00",
                                           startDate=d, endDate=d) for d in dates],
                            jots=[jot(id=f"j-{d}", date=d, text=f"小記 {d}", createdAt=f"{d}T12:00:00+08:00") for d in dates])
                    for _ in range(6)]                                  # 每次打開都抓到同樣的資料
    return make_api(url=FAKE_URL, fetch=fetch, today=datetime.date(2026, 11, 9), now=datetime.datetime(2026, 11, 9, 0, 10),
                    clock=Clock(taipei_ts(2026, 11, 9, 0, 10)), **kw)


def test_line_set_auto_turns_it_on_from_yesterday_and_keeps_the_rest(make_api):
    h = make_api(url=FAKE_URL, today=datetime.date(2026, 11, 8))
    state = h.api.line_set_auto(True)
    assert state["auto_copy"] is True and json.loads(h.settings.read_text(encoding="utf-8"))["LINE"] == {"url": FAKE_URL, "auto_copy": True}
    assert json.loads(h.ledger.read_text(encoding="utf-8"))["auto_through"] == "2026-11-07"
    assert h.api.line_set_auto(False)["auto_copy"] is False


def test_auto_is_off_by_default_so_opening_copies_nothing(make_api):
    h = auto_api(make_api)
    h.api.month("2026-11")
    assert not diary.read_day(h.root, "2026-11-08")["行程"] and h.api.line_state()["auto_message"] == ""
    assert h.api.line_state()["diary_version"] == 0 and not h.ledger.exists()


def test_auto_copies_yesterday_on_open_reports_it_and_bumps_the_diary_version(make_api):
    h = auto_api(make_api)
    h.api.line_set_auto(True)
    json_ledger = json.loads(h.ledger.read_text(encoding="utf-8"))
    json_ledger["auto_through"] = "2026-11-07"                       # 昨天開的開關
    h.ledger.write_text(json.dumps(json_ledger), encoding="utf-8")
    h.api.month("2026-11")
    day = diary.read_day(h.root, "2026-11-08")
    assert "活動 2026-11-08" in day["行程"] and "小記 2026-11-08" in day["看到"]
    state = h.api.line_state()
    assert state["auto_message"] == "自動複製了 1 天" and state["diary_version"] == 1


def test_auto_does_nothing_when_this_open_failed_to_get_fresh_data(make_api):
    fetch = FakeLine(today="2026-11-09")
    fetch.script = [line_net.LineError("offline", "連不上 LINE（沒有網路）")]
    h = make_api(url=FAKE_URL, fetch=fetch, today=datetime.date(2026, 11, 9), clock=Clock(taipei_ts(2026, 11, 9, 0, 10)))
    h.api.line_set_auto(True)
    json_ledger = json.loads(h.ledger.read_text(encoding="utf-8"))
    json_ledger["auto_through"] = "2026-11-06"
    h.ledger.write_text(json.dumps(json_ledger), encoding="utf-8")
    h.api.month("2026-11")
    assert json.loads(h.ledger.read_text(encoding="utf-8"))["auto_through"] == "2026-11-06" and h.api.line_state()["auto_message"] == ""


def test_auto_skips_the_day_the_page_is_viewing(make_api):
    h = auto_api(make_api)
    h.api.line_set_auto(True)
    json_ledger = json.loads(h.ledger.read_text(encoding="utf-8"))
    json_ledger["auto_through"] = "2026-11-07"
    h.ledger.write_text(json.dumps(json_ledger), encoding="utf-8")
    h.api.day("2026-11-08")                                          # 頁面正開著昨天
    h.api.line_refresh()
    h.sync.on_open()                                                  # 這時候才抓完、做自動複製
    assert not diary.read_day(h.root, "2026-11-08")["行程"]
    h.api.month("2026-11")                                            # 離開日檢視
    h.sync.on_open()
    assert "活動 2026-11-08" in diary.read_day(h.root, "2026-11-08")["行程"]


def test_auto_failure_is_a_message_not_a_crash_and_leaks_no_path(make_api, monkeypatch):
    h = auto_api(make_api)
    h.api.line_set_auto(True)
    json_ledger = json.loads(h.ledger.read_text(encoding="utf-8"))
    json_ledger["auto_through"] = "2026-11-07"
    h.ledger.write_text(json.dumps(json_ledger), encoding="utf-8")

    def broken(*args, **kwargs):
        raise OSError(28, "No space left on device", str(h.root))

    monkeypatch.setattr(diary, "save_day", broken)
    h.api.month("2026-11")
    state = h.api.line_state()
    assert "存不進日記" in state["auto_message"] and str(h.root) not in state["auto_message"] and state["diary_version"] == 0


def test_an_unexpected_failure_in_the_auto_hook_becomes_a_message_too(make_api, monkeypatch):
    h = auto_api(make_api)
    h.api.line_set_auto(True)

    def broken(*args, **kwargs):
        raise ValueError("日期格式不對：x")

    monkeypatch.setattr("line_copy.run_auto", broken)
    h.api.month("2026-11")
    assert "自動複製失敗" in h.api.line_state()["auto_message"]


def test_the_page_can_see_a_changed_day_through_diary_version_and_reload(make_api):
    h = auto_api(make_api)
    h.api.line_set_auto(True)
    json_ledger = json.loads(h.ledger.read_text(encoding="utf-8"))
    json_ledger["auto_through"] = "2026-11-07"
    h.ledger.write_text(json.dumps(json_ledger), encoding="utf-8")
    version = h.api.line_state()["diary_version"]
    h.api.month("2026-11")
    assert h.api.line_state()["diary_version"] == version + 1
    h.api.line_refresh()
    h.sync.on_open()
    assert h.api.line_state()["diary_version"] == version + 1       # 沒有新的內容：不會多加


def test_state_polling_does_not_take_the_diary_lock(make_api):
    h = make_api()
    seen = []
    with h.api._lock:                       # 別的呼叫（存檔、加圖片）正拿著鎖時，狀態還是要拿得到（在另一條執行緒問，免得測試卡死）
        asker = threading.Thread(target=lambda: seen.append(h.api.line_state()["configured"]), daemon=True)
        asker.start()
        asker.join(3)
        assert not asker.is_alive() and seen == [False]


@pytest.mark.parametrize("name", ["line_set_url", "line_clear", "line_set_auto", "line_copy_preview", "line_copy", "month", "year", "day"])
def test_methods_that_touch_files_serialise_on_the_api_lock(make_api, name):
    h = make_api()
    assert getattr(getattr(type(h.api), name), "__wrapped__", None) is not None   # _guarded 包著：拿同一把鎖
