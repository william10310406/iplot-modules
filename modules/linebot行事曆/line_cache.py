"""LINE 的快取（line_cache.json，放在「行事曆 2」自己的資料夾；內容是你的私人資料，權限 0600）。

按「段」存：每一段是一次成功的抓取（解析過、保留每筆的 id 與所有認得的欄位）加上抓的時間。畫面用的時候把幾段合起來（merged）：
**較新的一段是它那段日期的權威**——較新的一段範圍裡沒有的東西（在 LINE 被刪掉的）就不再出現；範圍外的，舊的一段照樣留著。
「同一段時間有快取就不要重抓」靠 missing()／covers()：一段在 24 小時內抓的才算有。
壞檔、讀不了、版本不認得都當空的；有一段壞掉只跳過那一段。這個檔不碰網路、不 import core。"""

import copy
import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path

import line_data
import settings

VERSION = 1
MAX_SLICES = 12
KEEP_DAYS = 400   # 整段都在今天（台北）400 天以前的丟掉（LINE 只提供前後 400 天）
FRESH = 24 * 3600.0


@dataclass
class Slice:
    fetched_at: float          # 抓的時間（epoch 秒）
    parsed: line_data.Parsed

    @property
    def range_from(self) -> str:
        return self.parsed.range_from

    @property
    def range_to(self) -> str:
        return self.parsed.range_to


def _ordinal(day: str) -> int:
    return datetime.date.fromisoformat(day).toordinal()


def _day(ordinal: int) -> str:
    return datetime.date.fromordinal(ordinal).isoformat()


def _iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, line_data.TAIPEI).isoformat(timespec="seconds")


@dataclass
class Cache:
    account: str | None = None                       # token 的 sha256 前 12 碼：這份快取是不是這個網址的
    slices: list[Slice] = field(default_factory=list)  # 舊的在前、新的在後
    last: dict = field(default_factory=dict)         # 上一次抓的結果：{"at", "ok", "kind", "message"}
    retry_until: float | None = None                 # 429 之後，這個時間之前不再送請求

    def add_slice(self, parsed: line_data.Parsed, fetched_at: float, today: str | None = None) -> None:
        """加一段。被它完全蓋住的舊段丟掉；最多留 MAX_SLICES 段；today（台北日期）給了就順便丟太舊的。"""
        self.slices = [s for s in self.slices if not (parsed.range_from <= s.range_from and s.range_to <= parsed.range_to)]
        self.slices.append(Slice(fetched_at, parsed))
        del self.slices[:-MAX_SLICES]
        if today is not None:
            self.prune(today)

    def prune(self, today: str) -> None:
        cutoff = _day(_ordinal(today) - KEEP_DAYS)
        self.slices = [s for s in self.slices if s.range_to >= cutoff]

    def missing(self, from_: str, to: str, now: float, ttl: float = FRESH) -> list[tuple[str, str]]:
        """from_..to 之間，還沒有（或已經過期）的日期，合併成連續的幾段。"""
        start, end, cursor, gaps = _ordinal(from_), _ordinal(to), _ordinal(from_), []
        spans = sorted((max(start, _ordinal(s.range_from)), min(end, _ordinal(s.range_to)))
                       for s in self.slices if now - s.fetched_at <= ttl)
        for low, high in spans:
            if low > high:
                continue
            if low > cursor:
                gaps.append((cursor, low - 1))
            cursor = max(cursor, high + 1)
        if cursor <= end:
            gaps.append((cursor, end))
        return [(_day(a), _day(b)) for a, b in gaps]

    def covers(self, from_: str, to: str, now: float, ttl: float = FRESH) -> bool:
        return not self.missing(from_, to, now, ttl)

    def record(self, ok: bool, kind: str | None, message: str, at: float) -> None:
        self.last = {"at": at, "ok": ok, "kind": kind, "message": message}

    def latest_fetch(self) -> float | None:
        return max((s.fetched_at for s in self.slices), default=None)

    def clear_data(self) -> None:
        self.slices = []

    def merged(self) -> line_data.Parsed:
        """所有段合起來（回的是複製品，隨便改不影響快取）。較新的一段優先；詳見檔頭。"""
        order = sorted(enumerate(self.slices), key=lambda pair: (pair[1].fetched_at, pair[0]), reverse=True)
        covered: list[tuple[str, str]] = []
        events, tasks, logs, moods, jots = [], [], [], [], []
        seen = {"events": set(), "tasks": set(), "jots": set(), "moods": set()}

        def inside(first: str, last: str) -> bool:
            return any(low <= last and first <= high for low, high in covered)

        for rank, (_, piece) in enumerate(order):
            data = piece.parsed
            for item in data.events:
                span = line_data.event_span(item)
                if item["id"] not in seen["events"] and not inside(span.first, span.last):
                    seen["events"].add(item["id"])
                    events.append(item)
            for item in data.tasks:
                day = line_data.task_day(item)
                if item["id"] in seen["tasks"] or (day is None and rank > 0) or (day is not None and inside(day, day)):
                    continue  # 沒有截止日的待辦：只看最新的一段（每次回應都帶著所有沒完成的）
                seen["tasks"].add(item["id"])
                tasks.append(item)
            logs += [item for item in data.logs if not inside(item["date"], item["date"])]
            for item in data.moods:
                if item["date"] not in seen["moods"] and not inside(item["date"], item["date"]):
                    seen["moods"].add(item["date"])
                    moods.append(item)
            for item in data.jots:
                if item["id"] not in seen["jots"] and not inside(item["date"], item["date"]):
                    seen["jots"].add(item["id"])
                    jots.append(item)
            covered.append((piece.range_from, piece.range_to))
        events.sort(key=lambda e: line_data.event_span(e).first)  # 穩定排序：同一天保持原本的順序
        jots.sort(key=lambda j: (line_data.instant(j["createdAt"]), j["id"]))
        newest = order[0][1].parsed if order else None
        return line_data.Parsed(min((s.range_from for s in self.slices), default=""), max((s.range_to for s in self.slices), default=""),
                                newest.generated_at if newest else None, *copy.deepcopy((events, tasks, logs, moods, jots)))


def _last(value) -> dict:
    if not isinstance(value, dict):
        return {}
    at, ok, kind, message = value.get("at"), value.get("ok"), value.get("kind"), value.get("message")
    if not (isinstance(at, (int, float)) and not isinstance(at, bool) and isinstance(ok, bool)
            and (kind is None or isinstance(kind, str)) and isinstance(message, str)):
        return {}
    return {"at": at, "ok": ok, "kind": kind, "message": message}


def load(path: Path, account: str | None = None) -> Cache:
    """讀快取。沒有、壞掉、版本不認得都回空的；指定了 account 而檔案是別的帳號的，也回空的（檔案不動，下次存才換）。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Cache(account=account)
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return Cache(account=account)
    stored = data.get("account")
    stored = stored if isinstance(stored, str) else None
    if account is not None and stored != account:
        return Cache(account=account)
    cache = Cache(account=account if account is not None else stored, last=_last(data.get("last")))
    retry = data.get("retry_until")
    cache.retry_until = float(retry) if isinstance(retry, (int, float)) and not isinstance(retry, bool) else None
    for item in data.get("slices") if isinstance(data.get("slices"), list) else []:
        try:
            when = datetime.datetime.fromisoformat(item["fetched_at"]).timestamp()
            cache.slices.append(Slice(when, line_data.parse(item["data"])))
        except (KeyError, TypeError, ValueError):  # FormatError 是 ValueError
            continue
    return cache


def save(path: Path, cache: Cache) -> None:
    """先寫暫存檔再換、權限 0600；寫不進去的 OSError 往外丟。"""
    data = {"version": VERSION, "account": cache.account, "last": cache.last, "retry_until": cache.retry_until,
            "slices": [{"fetched_at": _iso(s.fetched_at), "data": s.parsed.to_payload()} for s in cache.slices]}
    settings.write_private(Path(path), json.dumps(data, ensure_ascii=False, indent=1) + "\n")
