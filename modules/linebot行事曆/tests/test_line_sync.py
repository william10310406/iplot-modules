"""抓哪一段、什麼時候抓、背景執行緒、429 要等、狀態（docs/01_設計.md 第 4.6 節）。

用假的 fetch（記下每一次請求）、假的時鐘；多數測試用「同步版」的 spawn（工作在呼叫的當下做完），
只有「不卡住呼叫的人」和「同一段只送一次」用真的執行緒。"""

import datetime
import json
import threading

import pytest
from support import FAKE_TOKEN, FAKE_URL, NOW, Clock, FakeLine, event, jot, line_payload, mood, task

import line_cache
import line_data
import line_net
import line_sync
import line_url
import settings

HOUR = 3600.0


def make(tmp_path, *, url=FAKE_URL, fetch=None, clock=None, spawn=lambda fn: fn(), **kw):
    fetch = fetch or FakeLine()
    clock = clock or Clock()
    paths = (tmp_path / "設定.json", tmp_path / "line_cache.json")
    if url:
        settings.update(paths[0], lambda d: d.setdefault("LINE", {}).update({"url": url}))
    return line_sync.Sync(*paths, fetch=fetch, clock=clock, spawn=spawn, **kw), fetch, clock, paths


# ── 狀態：沒有網址、不外洩 ──

def test_no_url_configured_sends_nothing_and_says_how_to_get_one(tmp_path):
    sync, fetch, _, _ = make(tmp_path, url=None)
    state = sync.on_open()
    assert fetch.calls == [] and state["configured"] is False and state["masked_url"] is None
    assert "還沒設定" in state["message"] and "連上iPLoT" in state["message"]
    assert sync.refresh()["message"] == state["message"] and sync.need("month", "2026-11")["message"] == state["message"]
    assert fetch.calls == []


def test_state_never_contains_the_full_url(tmp_path):
    sync, fetch, _, _ = make(tmp_path)
    fetch.script = [line_net.LineError("not_found", line_net.RESET), None]
    for step in (sync.state, sync.on_open, sync.refresh, lambda: sync.need("month", "2027-01"), lambda: sync.need("year", "2026")):
        dumped = json.dumps(step())
        assert FAKE_TOKEN not in dumped and FAKE_URL not in dumped
    state = sync.state()
    assert state["masked_url"] == line_url.mask(FAKE_URL) and FAKE_TOKEN[8:-8] not in state["masked_url"]


# ── 打開、更新 ──

def test_open_fetches_the_default_range_once(tmp_path):
    sync, fetch, _, _ = make(tmp_path)
    sync.on_open()
    assert fetch.calls == [(None, None)]   # 沒有 from／to：前 35 天到後 70 天


def test_success_adds_a_slice_saves_the_cache_and_bumps_version(tmp_path):
    sync, fetch, _, (_, cache_path) = make(tmp_path)
    before = sync.state()["version"]
    state = sync.on_open()
    assert state["version"] > before and state["last"]["ok"] is True and state["message"] == ""
    assert state["last_ok_at"] == NOW
    on_disk = line_cache.load(cache_path)
    assert [(s.range_from, s.range_to) for s in on_disk.slices] == [("2026-10-04", "2027-01-17")]
    assert on_disk.account == line_url.account_id(FAKE_URL)


def test_data_comes_back_through_merged(tmp_path):
    fetch = FakeLine()
    fetch.script = [line_payload(range={"from": "2026-10-04", "to": "2027-01-16"})]
    sync, _, _, _ = make(tmp_path, fetch=fetch)
    sync.on_open()
    merged = sync.merged()
    assert [e["id"] for e in merged.events] == ["e1", "e2"] and [m["date"] for m in merged.moods] == ["2026-11-06"]


FAILURES = ["not_found", "rate_limit", "bad_range", "method", "server", "timeout", "offline", "dropped", "tls", "certificate",
            "network", "redirect", "too_big", "http"]


@pytest.mark.parametrize("kind", FAILURES)
def test_failure_keeps_the_previous_cache_and_reports_the_reason(tmp_path, kind):
    fetch = FakeLine()
    fetch.script = [line_payload(range={"from": "2026-10-04", "to": "2027-01-16"}), None]
    sync, _, clock, _ = make(tmp_path, fetch=fetch)
    sync.on_open()
    good = sync.merged().to_payload()
    clock.advance(10)
    fetch.script = [line_net.LineError(kind, f"說明-{kind}", 30 if kind == "rate_limit" else None)]
    state = sync.refresh()
    assert sync.merged().to_payload() == good                         # 快取沒動
    assert state["last"]["ok"] is False and state["last"]["kind"] == kind
    assert "快取" in state["message"] and "顯示的是" in state["message"] and "11/08 21:45" in state["message"]
    if kind != "rate_limit":
        assert f"說明-{kind}" in state["message"]


def test_failure_with_nothing_cached_says_there_is_nothing_to_show(tmp_path):
    fetch = FakeLine()
    fetch.script = [line_net.LineError("offline", "連不上 LINE（沒有網路）")]
    sync, _, _, _ = make(tmp_path, fetch=fetch)
    state = sync.on_open()
    assert "連不上 LINE" in state["message"] and "還沒有 LINE 的資料可以顯示" in state["message"] and "顯示的是" not in state["message"]


def test_404_message_says_the_url_may_have_been_reset(tmp_path):
    fetch = FakeLine()
    fetch.script = [line_net.LineError("not_found", line_net.RESET)]
    sync, _, _, _ = make(tmp_path, fetch=fetch)
    message = sync.on_open()["message"]
    assert "網址可能已經重設" in message and "私訊 bot『連上iPLoT』拿新的" in message


def test_a_payload_with_the_wrong_version_or_types_is_refused_with_a_reason_and_the_cache_stays(tmp_path):
    fetch = FakeLine()
    sync, _, _, _ = make(tmp_path, fetch=fetch)
    sync.on_open()
    good = sync.merged().to_payload()
    fetch.script = [line_payload(version=2)]
    message = sync.refresh()["message"]
    assert "version 2" in message and "更新行事曆 2" in message
    fetch.script = [line_payload(events=[{"id": 5}])]
    message = sync.refresh()["message"]
    assert "格式不對" in message and "活動" in message and "沒有更新快取" in message
    fetch.script = [line_payload(version="evil" * 20)]
    assert "evil" not in sync.refresh()["message"]
    assert sync.merged().to_payload() == good


def test_on_success_runs_after_an_open_that_got_fresh_data_and_only_then(tmp_path):
    calls = []
    sync, fetch, _, _ = make(tmp_path, on_success=lambda: calls.append("copy"))
    sync.refresh()
    assert calls == []                                  # 「立刻更新」不觸發
    sync.on_open()
    assert calls == ["copy"]
    fetch.script = [line_net.LineError("offline", "x")]
    sync.on_open()
    assert calls == ["copy"]                            # 這次打開沒抓到：不做


def test_cache_that_cannot_be_saved_does_not_crash_and_says_so(tmp_path, monkeypatch):
    sync, _, _, _ = make(tmp_path)

    def broken(path, cache):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(line_sync.line_cache, "save", broken)
    state = sync.on_open()
    assert "存不進去" in state["message"] and str(tmp_path) not in state["message"]
    assert sync.merged() is not None


# ── 429 ──

def test_429_waits_retry_after_and_sends_nothing_meanwhile(tmp_path):
    fetch = FakeLine()
    fetch.script = [line_net.LineError("rate_limit", "x", 90)]
    sync, _, clock, _ = make(tmp_path, fetch=fetch)
    state = sync.on_open()
    assert state["retry_in"] == 90 and "90 秒後" in state["message"]
    sent = len(fetch.calls)
    clock.advance(30)
    for step in (sync.on_open, sync.refresh, lambda: sync.need("month", "2027-01"), lambda: sync.need("year", "2026")):
        state = step()
        assert state["retry_in"] == 60 and "60 秒後" in state["message"]   # 倒數
    assert len(fetch.calls) == sent                                          # 一個請求都沒有送


def test_429_resumes_after_the_wait(tmp_path):
    fetch = FakeLine()
    fetch.script = [line_net.LineError("rate_limit", "x", 90)]
    sync, _, clock, _ = make(tmp_path, fetch=fetch)
    sync.on_open()
    clock.advance(91)
    state = sync.refresh()
    assert state["retry_in"] == 0 and state["last"]["ok"] is True and state["message"] == "" and len(fetch.calls) == 2


def test_429_wait_survives_a_restart(tmp_path):
    fetch = FakeLine()
    fetch.script = [line_net.LineError("rate_limit", "x", 120)]
    sync, _, clock, _ = make(tmp_path, fetch=fetch)
    sync.on_open()
    again, again_fetch, _, _ = make(tmp_path, clock=clock)
    assert again.state()["retry_in"] == 120
    again.on_open()
    assert again_fetch.calls == []


# ── 翻月、年 ──

def test_scrolling_to_an_uncached_month_fetches_just_that_month(tmp_path):
    sync, fetch, _, _ = make(tmp_path)
    sync.on_open()
    sync.need("month", "2027-03")
    assert fetch.calls[-1] == ("2027-03-01", "2027-03-31")


def test_scrolling_inside_the_default_range_does_not_fetch(tmp_path):
    sync, fetch, _, _ = make(tmp_path)
    sync.on_open()
    sync.need("month", "2026-11")
    sync.need("month", "2026-12")
    assert fetch.calls == [(None, None)]


def test_scrolling_back_to_a_cached_month_does_not_fetch(tmp_path):
    sync, fetch, _, _ = make(tmp_path)
    sync.on_open()
    sync.need("month", "2027-03")
    sync.need("month", "2027-03")
    assert fetch.calls.count(("2027-03-01", "2027-03-31")) == 1


def test_month_older_than_24h_is_fetched_again(tmp_path):
    sync, fetch, clock, _ = make(tmp_path)
    sync.need("month", "2027-03")
    clock.advance(24 * HOUR - 5)
    sync.need("month", "2027-03")
    assert len(fetch.calls) == 1
    clock.advance(10)
    sync.need("month", "2027-03")
    assert len(fetch.calls) == 2


def test_month_partly_cached_fetches_only_the_uncached_days(tmp_path):
    sync, fetch, _, _ = make(tmp_path)
    sync.on_open()                                   # 預設範圍蓋住到 2027-01-17（今天 + 70 天）
    sync.need("month", "2027-01")
    assert fetch.calls[-1] == ("2027-01-18", "2027-01-31")


def test_year_view_fetches_at_most_4_windows_of_at_most_100_days(tmp_path):
    sync, fetch, _, _ = make(tmp_path)
    sync.need("year", "2026")
    assert 1 <= len(fetch.calls) <= 4
    for low, high in fetch.calls:
        assert (datetime.date.fromisoformat(high) - datetime.date.fromisoformat(low)).days + 1 <= 100
    covered = {datetime.date.fromisoformat(low) + datetime.timedelta(days=n)
               for low, high in fetch.calls for n in range((datetime.date.fromisoformat(high) - datetime.date.fromisoformat(low)).days + 1)}
    assert len(covered) == 365 and min(covered).isoformat() == "2026-01-01" and max(covered).isoformat() == "2026-12-31"


def test_year_view_stops_at_the_first_429(tmp_path):
    fetch = FakeLine()
    fetch.script = [line_net.LineError("rate_limit", "x", 45)]
    sync, _, _, _ = make(tmp_path, fetch=fetch)
    state = sync.need("year", "2026")
    assert len(fetch.calls) == 1 and state["retry_in"] == 45


def test_a_failed_window_drops_the_rest_of_the_queue(tmp_path):
    fetch = FakeLine()
    fetch.script = [line_net.LineError("offline", "x")]
    sync, _, _, _ = make(tmp_path, fetch=fetch)
    sync.need("year", "2026")
    assert len(fetch.calls) == 1


def test_months_beyond_400_days_send_no_request_and_say_so(tmp_path):
    sync, fetch, _, _ = make(tmp_path)
    for key in ("2028-06", "2024-01"):
        state = sync.need("month", key)
        assert "400 天" in state["message"]
    assert fetch.calls == []
    assert "400 天" not in sync.on_open()["message"]   # 下一次成功的更新就把這句話拿掉


def test_a_month_at_the_edge_is_clipped_to_the_allowed_range(tmp_path):
    sync, fetch, _, _ = make(tmp_path)               # 今天 2026-11-08：往後最多到 2027-12-13
    sync.need("month", "2027-12")
    assert fetch.calls == [("2027-12-01", "2027-12-13")]
    sync.need("month", "2025-10")                    # 往前最多到 2025-10-04
    assert fetch.calls[-1] == ("2025-10-04", "2025-10-31")


def test_the_400_day_limit_uses_taipei_dates_not_the_machine_timezone(tmp_path):
    late = datetime.datetime(2026, 11, 8, 15, 30, tzinfo=datetime.timezone.utc).timestamp()   # 台北已經是 11-08 23:30
    next_day = datetime.datetime(2026, 11, 8, 16, 30, tzinfo=datetime.timezone.utc).timestamp()  # 台北 11-09 00:30
    sync, fetch, clock, _ = make(tmp_path, clock=Clock(late))
    sync.need("month", "2027-12")
    assert fetch.calls == [("2027-12-01", "2027-12-13")]
    clock.now = next_day
    sync.need("month", "2027-12")                    # 台北日期換成 11-09：再多一天（12-14）
    assert fetch.calls[-1] == ("2027-12-14", "2027-12-14")


def test_bad_need_arguments_are_refused(tmp_path):
    sync, fetch, _, _ = make(tmp_path)
    for kind, key in (("month", "2026-13"), ("month", "x"), ("year", "26"), ("week", "2026-11"), ("month", None), (None, None)):
        state = sync.need(kind, key)
        assert state["configured"] is True
    assert fetch.calls == []


# ── 執行緒 ──

def test_refresh_never_blocks_the_caller(tmp_path):
    fetch = FakeLine()
    fetch.gate = threading.Event()
    sync, _, _, _ = make(tmp_path, fetch=fetch, spawn=None)
    timer = threading.Timer(5, fetch.gate.set)
    timer.start()
    try:
        started = threading.Event()
        result = []

        def caller():
            result.append(sync.refresh())
            started.set()

        threading.Thread(target=caller, daemon=True).start()
        assert started.wait(2), "refresh() 在等網路：會卡住頁面"
        assert result[0]["busy"] is True
    finally:
        fetch.gate.set()
        timer.cancel()
    assert sync.wait_idle(5) and sync.state()["busy"] is False and sync.state()["last"]["ok"] is True


def test_same_range_requested_twice_while_running_sends_one_request(tmp_path):
    fetch = FakeLine()
    fetch.gate = threading.Event()
    sync, _, _, _ = make(tmp_path, fetch=fetch, spawn=None)
    sync.need("month", "2027-03")
    sync.need("month", "2027-03")
    sync.need("month", "2027-03")
    fetch.gate.set()
    assert sync.wait_idle(5)
    assert fetch.calls == [("2027-03-01", "2027-03-31")]


def test_jobs_run_one_at_a_time_in_order(tmp_path):
    fetch = FakeLine()
    sync, _, _, _ = make(tmp_path, fetch=fetch, spawn=None)
    sync.need("month", "2027-02")
    sync.need("month", "2027-03")
    assert sync.wait_idle(5)
    assert fetch.calls == [("2027-02-01", "2027-02-28"), ("2027-03-01", "2027-03-31")]


# ── 設定網址、清除 ──

def test_set_url_rejects_bad_urls_without_echoing_them_and_changes_nothing(tmp_path):
    sync, _, _, (settings_path, _) = make(tmp_path)
    before = settings.read(settings_path)
    for bad in ("http://x.example.test/j/" + "a" * 40 + ".json", "隨便貼的 SECRET-STRING", FAKE_URL + "?x=1", ""):
        with pytest.raises(line_url.BadUrl) as caught:
            sync.set_url(bad)
        assert "SECRET" not in str(caught.value)
    assert settings.read(settings_path) == before


def test_set_url_stores_it_only_in_the_settings_file_and_returns_the_masked_one(tmp_path):
    sync, _, _, (settings_path, _) = make(tmp_path, url=None)
    masked = sync.set_url(f"  {FAKE_URL}\n")
    assert masked == line_url.mask(FAKE_URL) and FAKE_TOKEN not in masked
    assert settings.line(settings_path)["url"] == FAKE_URL and sync.state()["configured"] is True


def test_set_url_keeps_other_line_settings_and_unknown_keys(tmp_path):
    sync, _, _, (settings_path, _) = make(tmp_path, url=None)
    settings.update(settings_path, lambda d: d.update({"資料夾": "/x", "LINE": {"auto_copy": True, "write_key": "k"}}))
    sync.set_url(FAKE_URL)
    assert settings.read(settings_path) == {"資料夾": "/x", "LINE": {"auto_copy": True, "write_key": "k", "url": FAKE_URL}}


def test_set_url_with_a_different_token_clears_the_cache_and_the_same_one_keeps_it(tmp_path):
    fetch = FakeLine()
    fetch.script = [line_payload(range={"from": "2026-10-04", "to": "2027-01-16"})]
    sync, _, _, (_, cache_path) = make(tmp_path, fetch=fetch)
    sync.on_open()
    assert sync.merged().events
    sync.set_url(FAKE_URL)                                                # 同一個：不動
    assert sync.merged().events
    sync.set_url(FAKE_URL.replace("FAKE-TOKEN", "OTHER-TOKEN"))
    assert sync.merged().events == [] and line_cache.load(cache_path).slices == []
    assert sync.state()["last"] == {"at": None, "ok": None, "kind": None, "message": ""}


def test_clear_removes_the_url_and_the_cache(tmp_path):
    sync, fetch, _, (settings_path, cache_path) = make(tmp_path)
    settings.update(settings_path, lambda d: d["LINE"].update({"auto_copy": True}))
    sync.on_open()
    assert cache_path.exists()
    state = sync.clear()
    assert state["configured"] is False and state["masked_url"] is None and not cache_path.exists()
    assert settings.line(settings_path) == {"auto_copy": True}            # 只拿掉網址
    assert sync.merged().events == [] and "還沒設定" in state["message"]
    calls = len(fetch.calls)
    sync.on_open()
    assert len(fetch.calls) == calls                                        # 沒網址就不送


def test_a_cache_belonging_to_another_url_is_not_used_on_startup(tmp_path):
    sync, _, _, (settings_path, cache_path) = make(tmp_path)
    sync.on_open()
    cache = line_cache.load(cache_path)
    cache.add_slice(line_data.parse(line_payload(events=[event(id="私人", title="別人的")])), NOW)
    line_cache.save(cache_path, cache)
    settings.update(settings_path, lambda d: d["LINE"].update({"url": FAKE_URL.replace("FAKE-TOKEN", "SWAPPED-TOKEN")}))
    again, _, _, _ = make(tmp_path, url=None)
    assert again.merged().events == []


def test_invalid_url_in_the_settings_file_counts_as_not_configured(tmp_path):
    sync, fetch, _, (settings_path, _) = make(tmp_path, url="http://not-https.example.test/j/" + "a" * 40 + ".json")
    state = sync.on_open()
    assert state["configured"] is False and fetch.calls == [] and "not-https" not in json.dumps(state)


def test_merged_returns_data_that_includes_what_each_slice_brought(tmp_path):
    fetch = FakeLine()
    fetch.script = [line_payload(range={"from": "2026-10-04", "to": "2027-01-16"}, events=[], tasks=[task(id="a")],
                                 moods=[mood(date="2026-11-06")], jots=[jot(id="z")]),
                    line_payload(range={"from": "2027-03-01", "to": "2027-03-31"}, events=[event(id="march", startDate="2027-03-05",
                                 endDate="2027-03-05", start="2027-03-05T10:00:00+08:00", end="2027-03-05T11:00:00+08:00")],
                                 tasks=[], moods=[], jots=[], logs=[])]
    sync, _, _, _ = make(tmp_path, fetch=fetch)
    sync.on_open()
    sync.need("month", "2027-03")
    merged = sync.merged()
    assert [t["id"] for t in merged.tasks] == ["a"]                          # 十一月的那一段沒被三月的蓋住
    assert [e["id"] for e in merged.events] == ["march"] and [j["id"] for j in merged.jots] == ["z"]


# ── 失敗之後不要每翻一頁就重送 ──

def test_need_does_not_retry_after_a_404_until_the_user_refreshes_or_changes_the_url(tmp_path):
    fetch = FakeLine()
    fetch.script = [line_net.LineError("not_found", line_net.RESET)]
    sync, _, clock, _ = make(tmp_path, fetch=fetch)
    sync.on_open()
    clock.advance(10 * HOUR)                        # 隔很久也一樣：網址失效了，翻頁敲 bot 也沒用
    sync.need("month", "2027-03")
    sync.need("year", "2026")
    assert len(fetch.calls) == 1
    sync.refresh()                                  # 你自己按「立刻更新」才再試
    assert len(fetch.calls) == 2
    sync.need("month", "2027-03")                   # 這次成功了，翻頁照常補抓
    assert len(fetch.calls) == 3


def test_need_waits_30_seconds_after_any_failure(tmp_path):
    fetch = FakeLine()
    fetch.script = [line_net.LineError("offline", "連不上 LINE（沒有網路）")]
    sync, _, clock, _ = make(tmp_path, fetch=fetch)
    sync.on_open()
    clock.advance(29)
    sync.need("month", "2027-03")
    assert len(fetch.calls) == 1
    clock.advance(2)
    sync.need("month", "2027-03")
    assert len(fetch.calls) == 2


def test_on_open_and_refresh_still_try_right_after_a_failure(tmp_path):
    fetch = FakeLine()
    fetch.script = [line_net.LineError("offline", "x")]
    sync, _, _, _ = make(tmp_path, fetch=fetch)
    sync.on_open()
    sync.refresh()
    assert len(fetch.calls) == 2


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_crashing_on_success_does_not_wedge_the_worker(tmp_path):
    def crash():
        raise RuntimeError("bug in the callback")

    sync, _, _, _ = make(tmp_path, spawn=None, on_success=crash)
    sync.on_open()
    assert sync.wait_idle(5) and sync.state()["busy"] is False   # 例外照樣會被執行緒的 excepthook 印出來，但狀態不會卡在「忙」
    for thread in threading.enumerate():                          # 等那條執行緒真的死透：警告才會算在這個測試頭上
        if thread.name == "line-sync":
            thread.join(5)
    assert sync.state()["last"]["ok"] is True
    sync.refresh()
    assert sync.wait_idle(5)


# ── 預設範圍還在抓的時候，翻頁不要重複去抓同一段 ──

def test_need_inside_the_default_range_does_not_duplicate_a_pending_default_fetch(tmp_path):
    fetch = FakeLine()
    fetch.gate = threading.Event()
    sync, _, _, _ = make(tmp_path, fetch=fetch, spawn=None)
    sync.on_open()                                   # 預設範圍正在抓（卡在 fetch）
    sync.need("month", "2026-11")                    # 今天這個月就在預設範圍裡：不用另外抓
    sync.need("month", "2026-12")
    sync.need("year", "2026")                        # 年：扣掉預設範圍，只補範圍外的
    fetch.gate.set()
    assert sync.wait_idle(5)
    assert fetch.calls[0] == (None, None)
    for low, high in fetch.calls[1:]:
        assert high < "2026-10-04" or low > "2027-01-17", (low, high)   # 都在預設範圍（10-04 到 2027-01-17）之外


def test_need_outside_the_default_range_is_still_queued_while_the_default_fetch_runs(tmp_path):
    fetch = FakeLine()
    fetch.gate = threading.Event()
    sync, _, _, _ = make(tmp_path, fetch=fetch, spawn=None)
    sync.on_open()
    sync.need("month", "2027-03")
    fetch.gate.set()
    assert sync.wait_idle(5)
    assert fetch.calls == [(None, None), ("2027-03-01", "2027-03-31")]


def test_need_straddling_the_edge_of_the_default_range_fetches_only_the_outside_part(tmp_path):
    fetch = FakeLine()
    fetch.gate = threading.Event()
    sync, _, _, _ = make(tmp_path, fetch=fetch, spawn=None)
    sync.on_open()
    sync.need("month", "2027-01")                    # 預設範圍到 2027-01-17：只補 18 號以後
    fetch.gate.set()
    assert sync.wait_idle(5)
    assert fetch.calls == [(None, None), ("2027-01-18", "2027-01-31")]


def test_after_the_default_fetch_failed_need_is_back_to_normal_rules(tmp_path):
    fetch = FakeLine()
    fetch.script = [line_net.LineError("offline", "x")]
    sync, _, clock, _ = make(tmp_path, fetch=fetch)
    sync.on_open()                                   # 失敗了：沒有快取
    clock.advance(31)
    sync.need("month", "2026-11")                    # 預設範圍已經不在抓了：這個月沒有快取就去抓
    assert fetch.calls[-1] == ("2026-11-01", "2026-11-30")
