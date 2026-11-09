"""把 LINE 的資料（line_cache 合併好的 Parsed）變成月、年、日要顯示的樣子，並決定心情的優先順序。

只讀：不改傳進來的東西、不碰檔案與網路。回的都是 dict／list／字串／數字，能直接變成 JSON 給頁面；
LINE 的文字原樣放著（顯示那一頭用 textContent，這裡不跳脫、不拼 HTML）。
我的日記資料（diary.py 讀出來的）當參數傳進來，這個檔不 import diary。"""

import datetime
import re

import line_data

_YM = re.compile(r"(\d{4})-(\d{2})", re.ASCII)
_YEAR = re.compile(r"\d{4}", re.ASCII)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
MONTH_LINES = 2   # 月格裡最多放幾行 LINE 的事項


def effective_mood(mine_face: str, mine_note: str, line_mood: dict | None) -> dict:
    """心情的優先順序（設計第 6 節）：我選過表情就用我的（LINE 的不顯示）；沒選過就顯示 LINE 的表情和一句話（標記是 LINE 來的）；
    兩邊都沒有就沒有。只寫了一句話、沒選表情，算沒選過表情；我的一句話在我自己的欄位，這裡不碰（mine_note 只是對照用）。"""
    if mine_face:
        return {"source": "mine", "emoji": mine_face, "text": None}
    if line_mood is not None:
        return {"source": "line", "emoji": line_mood["emoji"], "text": line_mood["text"]}
    return {"source": None, "emoji": "", "text": None}


def mood_of(data: line_data.Parsed, date: str) -> dict | None:
    """那天 LINE 的心情原樣（{"emoji", "text"}；沒有就 None）。不管我選了什麼：畫面上用 effective_mood 決定顯示誰的，複製進日記要用這個。"""
    for item in data.moods:
        if item["date"] == date:
            return {"emoji": item["emoji"], "text": item["text"]}
    return None


def _index(data: line_data.Parsed) -> dict[str, dict]:
    """日期 → 那一天的東西。活動每一天都出現（連同第幾天、共幾天）；沒有截止日的待辦不屬於任何一天。"""
    days: dict[str, dict] = {}

    def bucket(day: str) -> dict:
        return days.setdefault(day, {"events": [], "tasks": [], "logs": [], "mood": None, "jots": []})

    for item in data.events:
        span, span_days = line_data.event_span(item), line_data.event_days(item)
        for number, day in enumerate(span_days, 1):
            bucket(day)["events"].append((item, span, number, len(span_days)))
    for item in data.tasks:
        if line_data.task_day(item) is not None:
            bucket(line_data.task_day(item))["tasks"].append(item)
    for item in data.logs:
        bucket(item["date"])["logs"].append(item)
    for item in data.moods:
        bucket(item["date"])["mood"] = item
    for item in data.jots:
        bucket(item["date"])["jots"].append(item)
    return days


def _event_key(entry) -> tuple:
    """整天（含多天活動的第二天起）在前，再按開始時間；同樣的保持原本的順序。"""
    _, span, number, _ = entry
    return (1, span.start) if number == 1 and span.start else (0, "")


def _task_key(item: dict) -> tuple:
    return (item["dueTime"] is None, item["dueTime"] or "")


def _when(span: line_data.Span, number: int, count: int) -> str:
    """這一天的時間說明：整天、10:00–11:00、22:00 起（第 1 天／共 2 天）…"""
    if count == 1:
        if span.all_day or not span.start:
            return "整天" if span.all_day else ""
        return f"{span.start}–{span.end}" if span.end else span.start
    part = f"（第 {number} 天／共 {count} 天）"
    if not span.all_day and number == 1 and span.start:
        return f"{span.start} 起{part}"
    if not span.all_day and number == count and span.end:
        return f"至 {span.end}{part}"
    return f"整天{part}"


def _lines(bucket: dict) -> list[dict]:
    rows = []
    for item, span, number, _ in sorted(bucket["events"], key=_event_key):
        timed = not span.all_day and number == 1 and span.start
        rows.append({"kind": "event", "text": f"{span.start} {item['title']}" if timed else item["title"], "done": False,
                     "private": item["private"]})
    for item in sorted(bucket["tasks"], key=_task_key):
        text = f"{item['dueTime']} {item['title']}" if item["dueTime"] else item["title"]
        rows.append({"kind": "task", "text": text, "done": item["done"], "private": item["private"]})
    return rows


def month(data: line_data.Parsed, ym: str, mine_days: dict) -> dict[str, dict]:
    """一個月裡有 LINE 內容要顯示的日子：{"06": {"mood", "lines", "more", "count"}}。
    mine_days 是 diary.month_summary 的結果（{"06": {"mood": 表情, "first": 第一行, …}}）：
    我有第一行，月格就不放 LINE 的行（count 還在）。"""
    if not _YM.fullmatch(ym) or not 1 <= int(ym[5:7]) <= 12:
        raise ValueError(f"日期格式不對：{ym}")
    result = {}
    for day, bucket in sorted(_index(data).items()):
        if not day.startswith(ym + "-"):
            continue
        mine = mine_days.get(day[8:], {})
        rows = _lines(bucket)
        mood = effective_mood(mine.get("mood", ""), "", bucket["mood"])
        if not rows and mood["source"] != "line":
            continue
        shown = [] if mine.get("first") else rows[:MONTH_LINES]
        result[day[8:]] = {"mood": mood, "lines": shown, "more": len(rows) - len(shown) if shown else 0, "count": len(rows)}
    return result


def year(data: line_data.Parsed, y: str, mine_moods: dict) -> dict[str, dict]:
    """一年裡 LINE 要標記的日子：{"11": {"06": {"source": "line", "emoji": "🙂"}}}。
    source 是 "line"（LINE 的心情，虛線外框）或 "items"（只有事項，小圓點）。我那天選了表情的不列（頁面顯示我的）。
    mine_moods：{"11": {"06": 表情}}，我有日記但沒選表情就是 ""。"""
    if not _YEAR.fullmatch(y):
        raise ValueError(f"日期格式不對：{y}")
    result: dict[str, dict] = {}
    for day, bucket in sorted(_index(data).items()):
        if not day.startswith(y + "-") or mine_moods.get(day[5:7], {}).get(day[8:]):
            continue
        if bucket["mood"] is not None:
            mark = {"source": "line", "emoji": bucket["mood"]["emoji"]}
        elif bucket["events"] or bucket["tasks"] or bucket["logs"] or bucket["jots"]:
            mark = {"source": "items", "emoji": ""}
        else:
            continue
        result.setdefault(day[5:7], {})[day[8:]] = mark
    return result


def day(data: line_data.Parsed, date: str, mine_day: dict | None) -> dict:
    """一天的 LINE 內容（日檢視的唯讀區）。mine_day 是 diary.read_day 的結果（或 None）：用它的 mood 與 note 決定心情。"""
    if not _DATE.fullmatch(date):
        raise ValueError(f"日期格式不對：{date}")
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        raise ValueError(f"日期格式不對：{date}") from None
    bucket = _index(data).get(date) or {"events": [], "tasks": [], "logs": [], "mood": None, "jots": []}
    mine = mine_day or {}
    events = [{"id": item["id"], "title": item["title"], "when": _when(span, number, count), "all_day": span.all_day,
               "location": item["location"], "note": item["note"], "group": item["group"], "private": item["private"]}
              for item, span, number, count in sorted(bucket["events"], key=_event_key)]
    tasks = [{"id": item["id"], "title": item["title"], "time": item["dueTime"], "done": item["done"], "private": item["private"],
              "group": item["group"], "note": item["note"]} for item in sorted(bucket["tasks"], key=_task_key)]
    logs = [{"private": item["private"], "group": item["group"], "items": [dict(entry) for entry in item["items"]]}
            for item in bucket["logs"]]
    jots = [{"id": item["id"], "time": line_data.taipei(item["createdAt"])[1], "text": item["text"]} for item in bucket["jots"]]
    return {"mood": effective_mood(mine.get("mood", ""), mine.get("note", ""), bucket["mood"]), "events": events, "tasks": tasks,
            "logs": logs, "jots": jots, "empty": not (events or tasks or logs or jots or bucket["mood"])}
