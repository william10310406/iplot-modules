"""LINE 資料的解析：把 bot 回的 JSON（iPLoT-資料格式.md，version 1）檢查成乾淨的資料。純函式，不碰檔案與網路。

- 只認 version 1；頂層、每一筆的**不認得的欄位一律忽略**（之後會多的「這筆是從 iPLoT 來的」標記也是）。
- 型別嚴格（L06）：必要欄位缺了或型別不對、face 不認得、日期不合法，**整份拒收**（FormatError），不跳過單筆；
  可以是 null 的欄位缺了當 null。錯誤訊息只說是哪一區，不回顯資料。
- 每一筆保留文件裡的欄位（含 id）原樣；moods 的 emoji 不信 bot 給的，用 face 對照（跟 diary.MOODS 一樣的五個）。
- 時間是 +08:00 的 ISO 8601；一律換成台北時間（固定 +8，不看這台電腦的時區）。整天活動的 endDate 含最後一天。
這個檔只用標準庫、不 import core。"""

import datetime
import re
from dataclasses import dataclass
from typing import NamedTuple

VERSION = 1
TAIPEI = datetime.timezone(datetime.timedelta(hours=8))
FACES = {"grin": "😄", "smile": "🙂", "neutral": "😐", "worried": "😟", "cry": "😢"}  # 跟 diary.MOODS 一樣（有測試比）
MAX_EVENT_DAYS = 400  # 一筆活動最多展開幾天（壞資料不能讓畫面卡住）
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})", re.ASCII)
_ONE_DAY = datetime.timedelta(days=1)


class FormatError(ValueError):
    """資料格式不對。section 是哪一區（root、version、range、events…）；訊息不含資料。"""

    def __init__(self, section: str, message: str | None = None) -> None:
        self.section = section
        super().__init__(message or f"格式不對（{section}）")


class VersionError(FormatError):
    """version 不是 1。version 是 bot 給的整數（不是整數就是 None）。"""

    def __init__(self, version) -> None:
        self.version = version if isinstance(version, int) and not isinstance(version, bool) else None
        super().__init__("version", f"version 不是 {VERSION}")


class Span(NamedTuple):
    """一筆活動佔哪幾天、起訖時間（台北時間 HH:MM；沒有就是 None）。"""
    first: str
    last: str
    start: str | None
    end: str | None
    all_day: bool


@dataclass(frozen=True)
class Parsed:
    """一次回應解析完的樣子；各區是檢查過、只留認得欄位的 dict 清單（jots 已照 createdAt 排好）。"""
    range_from: str
    range_to: str
    generated_at: str | None
    events: list
    tasks: list
    logs: list
    moods: list
    jots: list

    def to_payload(self) -> dict:
        """回到 version 1 回應的形狀（只有認得的欄位）：快取就存這個，載入時再 parse 一次。"""
        return {"version": VERSION, "generatedAt": self.generated_at, "range": {"from": self.range_from, "to": self.range_to},
                "events": [dict(e) for e in self.events], "tasks": [dict(t) for t in self.tasks],
                "logs": [{**g, "items": [dict(i) for i in g["items"]]} for g in self.logs],
                "moods": [dict(m) for m in self.moods], "jots": [dict(j) for j in self.jots]}


# ── 欄位檢查 ──

def _str(item: dict, key: str, section: str) -> str:
    value = item.get(key)
    if not isinstance(value, str):
        raise FormatError(section)
    return value


def _opt_str(item: dict, key: str, section: str) -> str | None:
    value = item.get(key)
    if value is not None and not isinstance(value, str):
        raise FormatError(section)
    return value


def _bool(item: dict, key: str, section: str) -> bool:
    value = item.get(key)
    if not isinstance(value, bool):
        raise FormatError(section)
    return value


def _date(value, section: str) -> str:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise FormatError(section)
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        raise FormatError(section) from None
    return value


def _opt_date(item: dict, key: str, section: str) -> str | None:
    value = item.get(key)
    return None if value is None else _date(value, section)


def _datetime(value, section: str) -> datetime.datetime:
    """ISO 8601 帶偏移（+08:00、Z…）→ 有時區的 datetime。自己拆，不靠 fromisoformat（各版 Python 能吃的不一樣）。"""
    match = _ISO.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise FormatError(section)
    year, month, day, hour, minute, second, zone = match.groups()
    try:
        if zone == "Z":
            offset = datetime.timezone.utc
        else:
            delta = datetime.timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6]))
            offset = datetime.timezone(-delta if zone[0] == "-" else delta)
        return datetime.datetime(int(year), int(month), int(day), int(hour), int(minute), int(second or 0), tzinfo=offset)
    except ValueError:
        raise FormatError(section) from None


def _opt_datetime(item: dict, key: str, section: str) -> str | None:
    value = item.get(key)
    if value is not None:
        _datetime(value, section)
    return value


def _event(item: dict) -> dict:
    return {"id": _str(item, "id", "events"), "title": _str(item, "title", "events"), "allDay": _bool(item, "allDay", "events"),
            "start": _opt_datetime(item, "start", "events"), "end": _opt_datetime(item, "end", "events"),
            "startDate": _date(item.get("startDate"), "events"), "endDate": _date(item.get("endDate"), "events"),
            "location": _opt_str(item, "location", "events"), "note": _opt_str(item, "note", "events"),
            "private": _bool(item, "private", "events"), "group": _opt_str(item, "group", "events")}


def _task(item: dict) -> dict:
    return {"id": _str(item, "id", "tasks"), "title": _str(item, "title", "tasks"),
            "dueDate": _opt_date(item, "dueDate", "tasks"), "dueTime": _opt_str(item, "dueTime", "tasks"),
            "done": _bool(item, "done", "tasks"), "private": _bool(item, "private", "tasks"),
            "group": _opt_str(item, "group", "tasks"), "note": _opt_str(item, "note", "tasks")}


def _log(item: dict) -> dict:
    items = item.get("items")
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise FormatError("logs")
    return {"date": _date(item.get("date"), "logs"), "private": _bool(item, "private", "logs"),
            "group": _opt_str(item, "group", "logs"),
            "items": [{"title": _str(i, "title", "logs"), "details": _opt_str(i, "details", "logs")} for i in items]}


def _mood(item: dict) -> dict:
    face = item.get("face")
    if not isinstance(face, str) or face not in FACES:
        raise FormatError("moods")
    return {"date": _date(item.get("date"), "moods"), "face": face, "emoji": FACES[face], "text": _opt_str(item, "text", "moods")}


def _jot(item: dict) -> dict:
    created = _str(item, "createdAt", "jots")
    _datetime(created, "jots")
    return {"id": _str(item, "id", "jots"), "date": _date(item.get("date"), "jots"), "text": _str(item, "text", "jots"),
            "createdAt": created}


def _section(payload: dict, name: str, normalize) -> list:
    items = payload.get(name)
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise FormatError(name)
    return [normalize(i) for i in items]


def parse(payload) -> Parsed:
    """version 1 的回應 → Parsed。不合格丟 FormatError（version 不對是 VersionError）；不改動傳進來的東西。"""
    if not isinstance(payload, dict):
        raise FormatError("root")
    version = payload.get("version")
    if type(version) is not int or version != VERSION:
        raise VersionError(version)
    span = payload.get("range")
    if not isinstance(span, dict):
        raise FormatError("range")
    generated = payload.get("generatedAt")
    if generated is not None and not isinstance(generated, str):
        raise FormatError("generatedAt")
    jots = _section(payload, "jots", _jot)
    jots.sort(key=lambda j: (instant(j["createdAt"]), j["id"]))
    return Parsed(_date(span.get("from"), "range"), _date(span.get("to"), "range"), generated,
                  _section(payload, "events", _event), _section(payload, "tasks", _task), _section(payload, "logs", _log),
                  _section(payload, "moods", _mood), jots)


# ── 台北時間、整天活動 ──

def instant(iso: str) -> datetime.datetime:
    """ISO 8601 時間 → UTC 的 datetime（排先後用；字串比大小在不同偏移之間不準）。"""
    return _datetime(iso, "time").astimezone(datetime.timezone.utc)


def taipei(iso: str) -> tuple[str, str]:
    """ISO 8601 時間 → (台北日期 YYYY-MM-DD, 台北時間 HH:MM)。"""
    moment = _datetime(iso, "time").astimezone(TAIPEI)
    return moment.date().isoformat(), moment.strftime("%H:%M")


def event_span(event: dict) -> Span:
    """這筆活動佔哪幾天。整天：startDate 到 endDate（含最後一天）；有時間：看 start、end 換成台北時間，
    結束剛好是 00:00 時最後那天不算；結束比開始早當作單日；最多 MAX_EVENT_DAYS 天。"""
    if event["allDay"] or event["start"] is None:
        first, last = event["startDate"], max(event["startDate"], event["endDate"])
        start = end = None
    else:
        begin = _datetime(event["start"], "events").astimezone(TAIPEI)
        first, start, last, end = begin.date().isoformat(), begin.strftime("%H:%M"), None, None
        if event["end"] is None:
            last = first
        else:
            finish = _datetime(event["end"], "events").astimezone(TAIPEI)
            if finish < begin:
                last = first
            elif finish.time() == datetime.time(0, 0) and finish.date() > begin.date():
                last, end = (finish.date() - _ONE_DAY).isoformat(), "24:00"
            else:
                last, end = finish.date().isoformat(), finish.strftime("%H:%M")
    ceiling = (datetime.date.fromisoformat(first) + datetime.timedelta(days=MAX_EVENT_DAYS - 1)).isoformat()
    return Span(first, min(last, ceiling), start, end, bool(event["allDay"]))


def event_days(event: dict) -> list[str]:
    """這筆活動出現在哪幾天（YYYY-MM-DD，由早到晚）。"""
    span = event_span(event)
    day, last, days = datetime.date.fromisoformat(span.first), datetime.date.fromisoformat(span.last), []
    while day <= last:
        days.append(day.isoformat())
        day += _ONE_DAY
    return days


def task_day(task: dict) -> str | None:
    """待辦屬於哪一天（截止日）；沒有截止日是 None。"""
    return task["dueDate"]
