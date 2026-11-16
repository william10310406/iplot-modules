"""「同步」按鈕（0.3.0）：上方一顆、⚙ 裡一顆「立刻同步」，都呼叫 line_refresh，做的事跟打開行事曆一樣：
抓一次 LINE 的資料；抓到之後，「自動複製」開著才把還沒複製的日子接進日記（規則不變）；沒開就只抓、不寫日記。"""

import datetime
import json

import pytest
from support import FAKE_URL, SENTINEL, Clock, FakeLine, event, jot, line_payload, taipei_ts, task

import diary
import line_net

TODAY = datetime.date(2026, 11, 9)
NOW = datetime.datetime(2026, 11, 9, 0, 10)


def payload(dates=("2026-11-08",), **extra):
    sections = dict(events=[event(id=f"e-{d}", title=f"活動 {d}", start=f"{d}T10:00:00+08:00", end=f"{d}T11:00:00+08:00",
                                  startDate=d, endDate=d) for d in dates],
                    jots=[jot(id=f"j-{d}", date=d, text=f"小記 {d}", createdAt=f"{d}T12:00:00+08:00") for d in dates],
                    tasks=[], logs=[], moods=[])
    return line_payload(range={"from": "2026-10-04", "to": "2027-01-17"}, **{**sections, **extra})


def api_with(make_api, *scripts, auto=True, through="2026-11-07"):
    """今天是 2026-11-09 00:10；開關 auto；做到哪一天設成 through。scripts 是之後每一次抓的結果。"""
    fetch = FakeLine(today="2026-11-09")
    fetch.script = list(scripts)
    h = make_api(url=FAKE_URL, fetch=fetch, today=TODAY, now=NOW, clock=Clock(taipei_ts(2026, 11, 9, 0, 10)))
    if auto:
        h.api.line_set_auto(True)
        ledger = json.loads(h.ledger.read_text(encoding="utf-8"))
        ledger["auto_through"] = through
        h.ledger.write_text(json.dumps(ledger), encoding="utf-8")
    return h


def read(h, date="2026-11-08"):
    return diary.read_day(h.root, date)


# ── 按了之後做完整同步 ──

def test_sync_catches_up_after_an_open_that_had_no_network(make_api):
    h = api_with(make_api, line_net.LineError("offline", "連不上 LINE（沒有網路）"), payload())
    h.api.month("2026-11")                                  # 打開的時候沒網路：沒抓到、沒複製
    assert not read(h)["行程"] and json.loads(h.ledger.read_text(encoding="utf-8"))["auto_through"] == "2026-11-07"
    h.api.line_refresh()                                    # 有網路了，按「同步」
    assert "活動 2026-11-08" in read(h)["行程"] and json.loads(h.ledger.read_text(encoding="utf-8"))["auto_through"] == "2026-11-08"


def test_open_and_then_sync_fetch_twice_but_copy_once(make_api):
    h = api_with(make_api, payload(), payload())
    h.api.month("2026-11")
    assert "活動 2026-11-08" in read(h)["行程"] and len(h.fetch.calls) == 1
    h.api.line_refresh()
    assert len(h.fetch.calls) == 2 and read(h)["行程"].count("活動 2026-11-08") == 1


def test_sync_button_alone_copies_when_the_page_never_opened_a_month(make_api):
    h = api_with(make_api, payload())
    h.api.line_refresh()                                    # 沒有經過 month()：按鈕自己就做完整同步
    assert "活動 2026-11-08" in read(h)["行程"] and "小記 2026-11-08" in read(h)["看到"]
    state = h.api.line_state()
    assert state["auto_message"] == "自動複製了 1 天" and state["diary_version"] == 1


def test_pressing_sync_again_does_not_copy_the_same_things_twice(make_api):
    h = api_with(make_api, payload(), payload(), payload())
    h.api.line_refresh()
    first = (read(h)["行程"], read(h)["看到"])
    h.api.line_refresh()
    h.api.line_refresh()
    assert (read(h)["行程"], read(h)["看到"]) == first and first[0].count("活動 2026-11-08") == 1


def test_sync_with_auto_off_only_fetches_and_never_writes_the_diary(make_api):
    h = api_with(make_api, payload(), auto=False)
    h.api.line_refresh()
    assert len(h.fetch.calls) == 1 and h.api.line_state()["last"]["ok"] is True
    assert not read(h)["行程"] and not read(h)["看到"] and h.api.line_state()["diary_version"] == 0 and not h.ledger.exists()


@pytest.mark.parametrize("error", [line_net.LineError("offline", "連不上 LINE（沒有網路）"), line_net.LineError("not_found", "x"),
                                   line_net.LineError("rate_limit", "x", 45)])
def test_a_failed_sync_copies_nothing_and_leaves_the_ledger_alone(make_api, error):
    h = api_with(make_api, error, through="2026-11-06")
    h.api.line_refresh()
    assert not read(h)["行程"] and json.loads(h.ledger.read_text(encoding="utf-8"))["auto_through"] == "2026-11-06"
    assert h.api.line_state()["auto_message"] == "" and h.api.line_state()["last"]["ok"] is False


def test_sync_skips_the_viewed_day_private_items_and_public_days(make_api):
    secret = task(id="p1", title=f"{SENTINEL} 私人的", dueDate="2026-11-07", private=True)
    h = api_with(make_api, payload(dates=("2026-11-07", "2026-11-08"), tasks=[secret]), through="2026-11-06")
    diary.save_day(h.root, "2026-11-07", {"行程": "我的"}, 20)
    h.api.set_public("2026-11-07", True)                  # 公開的日子：整天不自動複製
    h.api.day("2026-11-08")                               # 正在看昨天：不碰
    h.api.line_refresh()
    assert read(h, "2026-11-07")["行程"] == "我的" and not read(h, "2026-11-08")["行程"]
    assert SENTINEL not in json.dumps([read(h, "2026-11-07"), read(h, "2026-11-08")], ensure_ascii=False)


def test_the_sync_message_and_state_never_contain_the_url(make_api):
    h = api_with(make_api, payload())
    state = h.api.line_refresh()
    assert "FAKE-TOKEN" not in json.dumps([state, h.api.line_state()])


# ── 頁面 ──

def page_text():
    import support
    return (support.MODULE / "page.html").read_text(encoding="utf-8")


def test_the_top_bar_has_a_sync_button_that_calls_the_same_function_as_the_settings_button():
    page = page_text()
    top = page[page.index('<div class="bar">\n  <button id="vYear">'):page.index('<div id="view">')]
    assert 'id="lineSync"' in top and ">同步<" in top
    assert top.index('id="lineStat"') < top.index('id="lineSync"') < top.index('id="web"')
    assert 'id="lineRefresh">立刻同步<' in page and "立刻更新" not in page
    assert page.count('addEventListener("click", refreshLine)') == 2


def test_the_page_says_so_when_auto_copy_is_off():
    page = page_text()
    assert "自動複製沒開" in page and "複製進我的日記" in page


def test_the_sync_button_is_hidden_without_a_url_and_grey_while_busy_or_waiting_for_429():
    page = page_text()
    assert 'sync.hidden = !s.configured' in page and "sync.disabled = !s.configured || s.busy || s.retry_in > 0" in page
