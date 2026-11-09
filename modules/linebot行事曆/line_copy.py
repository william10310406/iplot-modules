"""把 LINE 的內容複製進日記（做法 A）與自動複製（docs/01_設計.md 第 7 節）。

**這是唯一會把 LINE 的內容寫進日記資料夾的地方。** 手動是你按按鈕（先預覽、確定才寫）；自動要你在 ⚙ 打開開關，
每次打開行事曆時做一次。兩者同一套規則：
- 文字欄位（行程、看到、做了）**接在原本內容後面，不覆蓋**：原本有字就先空一行，再一行「── 從 LINE 複製 … ──」，再接內容；
  心情只在表情欄是空的才填表情、一句話欄是空的才填一句話。
- 寫之前**一定先存 .history 快照**（diary.save_day 的 force_snapshot：不管上一份快照多久以前），才找得回「複製之前」的原文。
- 已複製的記在 line_copied.json（只記 id 與日期，不記內容），重按、重開都不會重複。
- 自動複製更嚴：LINE 標了私人的項目一律略過；你勾了「公開」的日子整天不自動複製（不然「發佈」會把它們放上網路）。
  一次最多補 35 天；不碰今天、不碰頁面正在看的那一天；寫不進去就停在那裡、下次打開再試。
這個檔只寫日記資料夾（經 diary.save_day）與「行事曆 2」自己的紀錄檔；不碰網路、不 import core。"""

import dataclasses
import datetime
import hashlib
import json
from pathlib import Path

import diary
import line_view
import pages
import settings

LEDGER_VERSION = 1
CATCH_UP_DAYS = 35      # 一次最多補幾天（預設抓的範圍只有今天往前 35 天）
TEXT_FIELDS = ("行程", "看到", "做了")
_ONE_DAY = datetime.timedelta(days=1)


class Ledger:
    """line_copied.json：哪些項目已經複製過（鍵是 種類:id:日期）、自動複製做到哪一天。不認得的欄位原樣保留；壞檔當空的。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.items: dict[str, str] = {}
        self.auto_through: str | None = None
        self._extra: dict = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict) or data.get("version") != LEDGER_VERSION:
            return
        items = data.get("items")
        self.items = {k: v for k, v in items.items() if isinstance(v, str)} if isinstance(items, dict) else {}
        through = data.get("auto_through")
        try:
            self.auto_through = datetime.date.fromisoformat(through).isoformat() if isinstance(through, str) else None
        except ValueError:
            self.auto_through = None
        self._extra = {k: v for k, v in data.items() if k not in ("version", "items", "auto_through")}

    def __contains__(self, key: str) -> bool:
        return key in self.items

    def add(self, keys: list[str], when: str) -> None:
        for key in keys:
            self.items[key] = when

    def save(self) -> None:
        data = {"version": LEDGER_VERSION, **self._extra, "auto_through": self.auto_through, "items": self.items}
        settings.write_private(self.path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


@dataclasses.dataclass
class Plan:
    """一天要複製什麼（還沒寫）。additions 是每個欄位接上去的那一段（預覽用）；fields 是要寫的整份新內容（含心情）；
    items 是要記進 line_copied.json 的鍵；digest 讓「預覽之後 LINE 或日記又變了」查得出來（不含標題的時間）。"""
    date: str
    additions: dict[str, str]
    fields: dict[str, str]
    mood: dict | None
    items: list[str]
    items_by_field: dict[str, list[str]]
    skipped: dict
    public: bool
    digest: str

    @property
    def empty(self) -> bool:
        return not self.fields


def _lines(text: str) -> list[str]:
    """只把 \n、\r\n、\r 當換行（str.splitlines 連 U+2028 這類字元也算，會悄悄改掉 LINE 的原文）。"""
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _indent(text: str) -> list[str]:
    return ["  " + part for part in _lines(text)] if text else []


def _key(kind: str, ident: str, date: str) -> str:
    return f"{kind}:{ident}:{date}"


def _log_key(date: str, title: str, details: str | None) -> str:
    return f"log:{date}:" + hashlib.sha256(f"{title}\0{details or ''}".encode()).hexdigest()[:12]


def _separator(existing: str) -> str:
    """原本有字就空一行；原本的字一個都不動（結尾已經有換行就只多一個換行）。"""
    return "" if existing == "" else ("\n" if existing.endswith("\n") else "\n\n")


def build(date: str, view: dict, mine: dict, line_mood: dict | None, copied, *, now: datetime.datetime, auto: bool = False) -> Plan:
    """這一天要複製什麼。view 是 line_view.day 的結果、mine 是 diary.read_day 的結果、line_mood 是 line_view.mood_of、
    copied 是支援 `in` 的已複製鍵（Ledger 或 set）。不寫任何東西。
    手動：私人項目照複製，除非這一天勾了「公開」（那時略過私人並提醒）；自動：私人一律略過、公開的日子整天不做。"""
    public = bool(mine.get("public"))
    skipped = {"private": 0, "already": 0, "public_day": False, "unreadable": []}
    additions, fields, by_field, items, mood = {}, {}, {}, [], None
    header = f"── 從 LINE 複製 {now:%Y-%m-%d %H:%M} ──"
    if auto and public:
        skipped["public_day"] = True
        return Plan(date, {}, {}, None, [], {}, skipped, public, _digest(date, [], {}, None))
    allow_private = not auto and not public

    def take(key: str, private: bool) -> bool:
        if private and not allow_private:
            skipped["private"] += 1
            return False
        if key in copied:
            skipped["already"] += 1
            return False
        return True

    lines: dict[str, list[tuple[str, list[str]]]] = {name: [] for name in TEXT_FIELDS}   # 欄位 → [(鍵, 這一項的行)]
    for entry in view["events"]:
        if take(_key("event", entry["id"], date), entry["private"]):
            head = f"{entry['when']} {entry['title']}" if entry["when"] else entry["title"]
            head += f" @{entry['location']}" if entry["location"] else ""
            lines["行程"].append((_key("event", entry["id"], date), [head, *_indent(entry["note"] or "")]))
    for entry in view["tasks"]:
        if take(_key("task", entry["id"], date), entry["private"]):
            head = f"{'☑' if entry['done'] else '☐'} {entry['title']}" + (f"（截止 {entry['time']}）" if entry["time"] else "")
            lines["行程"].append((_key("task", entry["id"], date), [head, *_indent(entry["note"] or "")]))
    for entry in view["jots"]:
        if take(_key("jot", entry["id"], date), False):
            first, *rest = _lines(entry["text"])
            lines["看到"].append((_key("jot", entry["id"], date), [f"{entry['time']} {first}", *_indent("\n".join(rest))]))
    for record in view["logs"]:
        for item in record["items"]:
            key = _log_key(date, item["title"], item["details"])
            if take(key, record["private"]):
                lines["做了"].append((key, [item["title"], *_indent(item["details"] or "")]))

    for name in TEXT_FIELDS:
        if not lines[name]:
            continue
        if name in mine["unreadable"]:
            skipped["unreadable"].append(name)       # 不是 UTF-8 的檔不覆寫
            continue
        block = header + "\n" + "".join(f"{row}\n" for _, rows in lines[name] for row in rows)
        existing = mine[name]
        additions[name], fields[name] = block, existing + _separator(existing) + block
        by_field[name] = [key for key, _ in lines[name]]
        items += by_field[name]

    if line_mood is not None and "心情" not in mine["unreadable"]:
        key = f"mood:{date}"
        if key in copied:
            skipped["already"] += 1
        else:
            face = line_mood["emoji"] if not mine["mood"] else None
            note = line_mood["text"] if (not mine["note"].strip() and line_mood["text"]) else None
            if face or note:
                mood = {"mood": face, "note": note}
                fields["心情"] = diary.mood_text(face or mine["mood"], note or mine["note"])
                by_field["心情"] = [key]
                items.append(key)
    before = {name: mine[name] for name in additions} | ({"心情": [mine["mood"], mine["note"]]} if mood else {})
    return Plan(date, additions, fields, mood, items, by_field, skipped, public, _digest(date, items, before, mood))


def _digest(date: str, items: list[str], before: dict, mood: dict | None) -> str:
    """要複製的項目＋這幾個欄位現在的內容＋心情：LINE 或日記有一邊變了就不一樣。標題的時間不算（預覽與按確定差幾分鐘沒關係）。"""
    text = json.dumps([date, sorted(items), before, mood], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def apply(root: Path, date: str, plan: Plan, keep: int, ledger: Ledger, *, now: datetime.datetime) -> dict:
    """寫進日記：先強制存 .history 快照再寫；寫好才把這次複製的項目記進 ledger；網頁重建失敗只是警告（日記已經存好）。
    寫不進日記的 OSError 往外丟，這時 ledger 不動。回 {"changed", "unreadable", "items", "warning"}。"""
    if plan.empty:
        return {"changed": [], "unreadable": {}, "items": 0, "warning": None}
    result = diary.save_day(root, date, plan.fields, keep, force_snapshot=True)
    done = [key for name in result["changed"] for key in plan.items_by_field.get(name, [])]
    warnings = []
    if done:
        ledger.add(done, now.isoformat(timespec="seconds"))
        try:
            ledger.save()
        except OSError as exc:
            warnings.append(f"已複製的紀錄存不進去（{exc.strerror or '寫入失敗'}），再按一次可能會重複複製")
    if result["changed"]:
        try:
            pages.rebuild_after_save(root, date)
        except OSError as exc:
            warnings.append(f"日記存好了，但網頁沒有重建（{exc.strerror or '寫入失敗'}）")
    return {"changed": result["changed"], "unreadable": result["unreadable"], "items": len(done), "warning": "；".join(warnings) or None}


# ── 自動複製 ──

@dataclasses.dataclass
class AutoResult:
    enabled: bool = False
    days_copied: int = 0
    items: int = 0
    skipped_private: int = 0
    skipped_public_days: int = 0
    through: str | None = None
    error: str | None = None

    @property
    def message(self) -> str:
        if self.error:
            return self.error
        parts = ([f"{self.skipped_private} 項私人"] if self.skipped_private else []) + (
            [f"{self.skipped_public_days} 個公開的日子"] if self.skipped_public_days else [])
        tail = f"（略過 {'、'.join(parts)}）" if parts else ""
        if self.days_copied:
            return f"自動複製了 {self.days_copied} 天{tail}"
        return f"自動複製：這次沒有複製任何東西{tail}" if parts else ""


def set_auto(settings_path: Path, ledger_path: Path, on: bool, today: str) -> None:
    """⚙ 的「自動複製」開關。打開時一律把「做到哪一天」設成昨天：只從之後新增的日子開始，不回頭補（關著的那段也不補）。"""
    settings.update(settings_path, lambda data: settings.line_section(data).update({"auto_copy": bool(on)}))
    if on:
        ledger = Ledger(ledger_path)
        ledger.auto_through = (datetime.date.fromisoformat(today) - _ONE_DAY).isoformat()
        ledger.save()


def run_auto(settings_path: Path, ledger_path: Path, merged, root: Path, keep: int, *, today: str, now: datetime.datetime,
             viewing: str | None = None) -> AutoResult:
    """每次打開行事曆（抓到最新資料之後）做一次：從「做到哪一天」的隔天，到昨天，一天一天複製。
    開關沒開就什麼都不做。viewing 是頁面正在看的那一天：複製到它前一天為止（不然頁面的舊文字框會把它蓋掉）。"""
    if settings.line(settings_path).get("auto_copy") is not True:
        return AutoResult()
    ledger, result = Ledger(ledger_path), AutoResult(enabled=True)
    yesterday = datetime.date.fromisoformat(today) - _ONE_DAY
    if ledger.auto_through is None:        # 開關是手動改設定檔打開的：從昨天開始
        ledger.auto_through = yesterday.isoformat()
        result.through = ledger.auto_through
        _save_quietly(ledger, result)
        return result
    start = max(datetime.date.fromisoformat(ledger.auto_through) + _ONE_DAY, yesterday - (CATCH_UP_DAYS - 1) * _ONE_DAY)
    through, day = max(datetime.date.fromisoformat(ledger.auto_through), start - _ONE_DAY), start
    while day <= yesterday:
        date = day.isoformat()
        if date == viewing:
            break
        mine = diary.read_day(root, date)
        plan = build(date, line_view.day(merged, date, mine), mine, line_view.mood_of(merged, date), ledger, now=now, auto=True)
        result.skipped_private += plan.skipped["private"]
        result.skipped_public_days += 1 if plan.skipped["public_day"] else 0
        if not plan.empty:
            try:
                done = apply(root, date, plan, keep, ledger, now=now)
            except OSError as exc:
                result.error = f"自動複製：存不進日記（{exc.strerror or '寫入失敗'}），下次打開再試"
                break
            result.days_copied += 1 if done["items"] else 0
            result.items += done["items"]
        through, day = day, day + _ONE_DAY
    ledger.auto_through = result.through = through.isoformat()
    _save_quietly(ledger, result)
    return result


def _save_quietly(ledger: Ledger, result: AutoResult) -> None:
    try:
        ledger.save()
    except OSError as exc:
        result.error = result.error or f"自動複製：紀錄存不進去（{exc.strerror or '寫入失敗'}），下次打開可能會重複複製"
