"""從頭走一遍（docs/02_實作計畫.md 任務 12）：貼網址 → 打開 → 看月、年、日 → 手動複製 → 自動複製 → 換網址 → 清除。
每一步都確認：畫面看得到什麼、日記資料夾裡有沒有 LINE 的字、有沒有任何輸出含完整網址。"""

import datetime
import json

from support import FAKE_TOKEN, FAKE_URL, SENTINEL, Clock, FakeLine, event, jot, line_payload, mood, taipei_ts, task

import diary
import line_url

OTHER_URL = FAKE_URL.replace("FAKE-TOKEN", "OTHER-TOKEN")


def day_data(date, tag):
    return dict(events=[event(id=f"e-{date}", title=f"{SENTINEL} {tag} 活動", start=f"{date}T10:00:00+08:00", end=f"{date}T11:00:00+08:00",
                              startDate=date, endDate=date)],
                tasks=[task(id=f"t-{date}", title=f"{tag} 待辦", dueDate=date)],
                jots=[jot(id=f"j-{date}", date=date, text=f"{tag} 小記", createdAt=f"{date}T12:00:00+08:00")],
                moods=[mood(date=date, text=f"{tag} 心情")], logs=[])


def files_with(root, needle):
    return sorted(p.name for p in root.rglob("*") if p.is_file() and needle.encode() in p.read_bytes())


def test_the_whole_story(make_api):
    day1, day2 = "2026-11-07", "2026-11-08"          # 你開著的那一天（11-08）看得到前一天（11-07）
    fetch = FakeLine(today="2026-11-09")
    pay = lambda tag: line_payload(range={"from": "2026-10-05", "to": "2027-01-18"}, **{  # noqa: E731
        k: day_data(day1, tag)[k] + day_data(day2, tag)[k] for k in ("events", "tasks", "jots", "moods", "logs")})
    fetch.script = [pay("甲")] * 3
    h = make_api(today=datetime.date(2026, 11, 9), now=datetime.datetime(2026, 11, 9, 0, 10), fetch=fetch,
                 clock=Clock(taipei_ts(2026, 11, 9, 0, 10)))
    seen = []

    def check(result):
        seen.append(result)
        assert FAKE_TOKEN not in json.dumps(result) and "OTHER-TOKEN-0123" not in json.dumps(result)
        return result

    # 1 沒有網址：跟舊的行事曆一樣，沒有 LINE 的東西，也沒有任何請求
    assert check(h.api.month("2026-11"))["line"] == {} and fetch.calls == []
    assert check(h.api.line_state())["configured"] is False

    # 2 貼網址：存起來、抓一次、只拿得到遮過的
    state = check(h.api.line_set_url(FAKE_URL))
    assert state["configured"] is True and state["masked_url"] == line_url.mask(FAKE_URL) and fetch.calls == [(None, None)]
    assert json.loads(h.settings.read_text(encoding="utf-8"))["LINE"]["url"] == FAKE_URL

    # 3 看月、年、日：LINE 的內容在，日記資料夾裡沒有任何 LINE 的字
    month, year, day = check(h.api.month("2026-11")), check(h.api.year("2026")), check(h.api.day(day1))
    assert month["line"]["07"]["count"] == 2 and year["line"]["11"]["07"]["source"] == "line"
    assert "甲 活動" in json.dumps(day["line"], ensure_ascii=False)
    assert files_with(h.root, SENTINEL) == [] and files_with(h.root, "甲 小記") == []

    # 4 手動複製（先預覽、再確定）：這時才有 LINE 的字在日記裡；原本的字在最前面、舊的存進 .history
    diary.save_day(h.root, day1, {"行程": "我的行程"}, 20)
    preview = check(h.api.line_copy_preview(day1))
    assert files_with(h.root, "甲 小記") == []
    done = check(h.api.line_copy(day1, preview["digest"]))
    assert done["copied"] > 0 and diary.read_day(h.root, day1)["行程"].startswith("我的行程\n\n── 從 LINE 複製")
    assert [p.read_text(encoding="utf-8") for p in (diary.day_folder(h.root, day1) / diary.HISTORY).glob("行程-*.txt")] == ["我的行程"]
    assert check(h.api.line_copy_preview(day1))["empty"] is True

    # 5 打開自動複製：只從昨天開始；下次打開才把昨天以前還沒複製的接進去（11-07 已經手動複製過，不會重複）
    check(h.api.line_set_auto(True))
    ledger = json.loads(h.ledger.read_text(encoding="utf-8"))
    assert ledger["auto_through"] == "2026-11-08"
    h.sync.on_open()
    assert not diary.read_day(h.root, day2)["看到"] and h.api.line_state()["auto_message"] == ""

    # 6 換成別的網址（別的 token）：舊的快取清掉，LINE 的畫面空了；日記裡已經複製的字還在
    before = diary.read_day(h.root, day1)["行程"]
    state = check(h.api.line_set_url(OTHER_URL))
    assert state["masked_url"] == line_url.mask(OTHER_URL) and state["masked_url"] != line_url.mask(FAKE_URL)
    assert diary.read_day(h.root, day1)["行程"] == before and h.api.line_state()["last"]["ok"] is True       # 換了之後重抓成功

    # 7 清除：網址與快取都沒了；LINE 的畫面空了；已經複製進日記的字原封不動
    check(h.api.line_clear())
    assert not h.cache.exists() and "url" not in json.loads(h.settings.read_text(encoding="utf-8")).get("LINE", {})
    assert h.api.month("2026-11")["line"] == {} and h.api.day(day1)["line"]["empty"] is True
    assert diary.read_day(h.root, day1)["行程"] == before and json.loads(h.ledger.read_text(encoding="utf-8"))["items"]
    assert not [result for result in seen if FAKE_TOKEN in json.dumps(result)]
