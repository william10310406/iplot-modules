"""LINE 資料的同步：決定抓哪一段、什麼時候抓、在背景抓、429 要等多久、現在是什麼狀況（docs/01_設計.md 第 4.6 節）。

- **抓網址一律在背景執行緒做**（L08）：refresh()／need()／on_open() 只是排工作、立刻回傳，不會卡住頁面，
  也不拿 iplot.py 的 Api._lock。工作一次做一件、依序做；同一段已經在排或在抓就不重複送。
- 打開行事曆時抓一次預設範圍（不帶 from／to：前 35 天到後 70 天）；「立刻更新」再抓一次；翻到沒有快取的月、年才用
  from／to 補抓，只抓在今天（台北日期）前後 400 天內、而且沒有快取（24 小時內抓的才算有）的部分；年最多 4 段、每段 ≤ 100 天。
- 失敗（任何一種）：快取不動、只記下原因，佇列裡剩下的丟掉；429 照 Retry-After 等（期間一個請求都不送，重開也一樣）。
- state() 給頁面看，**不含完整網址**：只有遮過的。
這個檔不 import core。"""

import datetime
import math
import threading
import time
from collections.abc import Callable
from pathlib import Path

import line_cache
import line_data
import line_net
import line_url
import settings

BACK_DAYS = FORWARD_DAYS = 400       # LINE 只提供今天前後 400 天
DEFAULT_BACK, DEFAULT_FORWARD = 35, 70
MAX_WINDOW_DAYS = 100                # 一次請求最多 100 天（含頭尾）
MAX_YEAR_WINDOWS = 4
NOT_CONFIGURED = "還沒設定 LINE 網址：到 ⚙ 貼上（私訊 bot『連上iPLoT』拿網址）"
OUT_OF_RANGE = "LINE 只提供今天前後 400 天的資料"
CANNOT_SAVE = "LINE 的快取存不進去：{why}。這一次的資料還在，關掉行事曆就沒有了"
SECTION_NAMES = {"root": "最外層", "version": "version", "range": "日期範圍", "events": "活動", "tasks": "待辦", "logs": "做了什麼",
                 "moods": "心情", "jots": "小記", "generatedAt": "產生時間", "time": "時間"}
NO_SUFFIX = ("format", "bad_url")    # 這兩種的訊息自己已經說了快取的事（或跟快取無關）
STICKY_KINDS = ("not_found", "method")  # 這兩種失敗，翻頁不再自動重試（網址失效、程式的問題）；要你按「立刻更新」或換網址
NEED_COOLDOWN = 30                   # 其他失敗之後，翻頁補抓要隔這麼多秒才再試
_ONE_DAY = datetime.timedelta(days=1)


def _spawn(job: Callable[[], None]) -> None:
    threading.Thread(target=job, daemon=True, name="line-sync").start()


def _day(text: str) -> datetime.date:
    return datetime.date.fromisoformat(text)


class Sync:
    def __init__(self, settings_path: Path, cache_path: Path, *, fetch=line_net.fetch, clock=time.time, spawn=None,
                 on_success: Callable[[], None] | None = None) -> None:
        self._settings, self._cache_path, self._fetch, self._clock = Path(settings_path), Path(cache_path), fetch, clock
        self._spawn, self._on_success = spawn or _spawn, on_success
        self._lock = threading.RLock()
        self._idle = threading.Event()
        self._idle.set()
        self._queue: list[tuple[str | None, str | None, bool]] = []   # (from, to, 是不是「打開」那一次)
        self._current: tuple[str | None, str | None] | None = None
        self._running = False
        self._version, self._note = 0, ""
        self._cache = self._load()

    # ── 設定與快取 ──

    def _url(self) -> str | None:
        """設定檔裡的網址；沒有、不是字串、格式不對都當作沒設定（不丟錯、不回顯）。"""
        value = settings.line(self._settings).get("url")
        try:
            return line_url.validate(value) if isinstance(value, str) else None
        except line_url.BadUrl:
            return None

    def _load(self) -> line_cache.Cache:
        url = self._url()
        return line_cache.load(self._cache_path, line_url.account_id(url)) if url else line_cache.Cache()

    def _today(self) -> str:
        """台北日期（L11）：LINE 用台北時間算「今天前後 400 天」，這台電腦不在台北時區時邊界才不會差一天。"""
        return datetime.datetime.fromtimestamp(self._clock(), line_data.TAIPEI).date().isoformat()

    def _save(self) -> None:
        try:
            line_cache.save(self._cache_path, self._cache)
        except OSError as exc:
            self._note = CANNOT_SAVE.format(why=exc.strerror or "寫入失敗")

    def _bump(self) -> None:
        self._version += 1

    def merged(self) -> line_data.Parsed:
        with self._lock:
            return self._cache.merged()

    def wait_idle(self, timeout: float = 10) -> bool:
        """等到沒有工作在排、也沒有在抓（測試與關閉視窗前用）。"""
        return self._idle.wait(timeout)

    # ── 狀態 ──

    def state(self) -> dict:
        with self._lock:
            url, cache, now = self._url(), self._cache, self._clock()
            retry_in = max(0, math.ceil(cache.retry_until - now)) if cache.retry_until else 0
            last = {"at": None, "ok": None, "kind": None, "message": "", **cache.last}
            return {"version": self._version, "busy": not self._idle.is_set(), "configured": url is not None,
                    "masked_url": line_url.mask(url) if url else None, "last": last, "last_ok_at": cache.latest_fetch(),
                    "retry_in": retry_in, "message": self._message(url, retry_in, last, cache)}

    def _message(self, url, retry_in: int, last: dict, cache: line_cache.Cache) -> str:
        if url is None:
            return NOT_CONFIGURED
        stored = cache.latest_fetch()
        have = (f"顯示的是 {datetime.datetime.fromtimestamp(stored, line_data.TAIPEI):%m/%d %H:%M} 的快取" if stored is not None
                else "還沒有 LINE 的資料可以顯示")
        if self._note:
            return self._note
        if retry_in:
            return f"LINE 說請求太多，{retry_in} 秒後可以再更新。{have}"
        if last["ok"] is False and last["kind"] != "rate_limit":
            return last["message"] if last["kind"] in NO_SUFFIX else f"{last['message']}。{have}"
        return ""

    # ── 動作 ──

    def set_url(self, text) -> str:
        """貼上或更換網址：檢查（不合格丟 line_url.BadUrl，訊息固定、不含輸入）、存進設定檔、換成別的帳號就清掉快取。回遮過的網址。"""
        url = line_url.validate(text)
        settings.update(self._settings, lambda data: settings.line_section(data).update({"url": url}))
        with self._lock:
            if self._cache.account != line_url.account_id(url):
                self._reset(line_url.account_id(url))
            self._note = ""
            self._bump()
        return line_url.mask(url)

    def clear(self) -> dict:
        """清除網址，也刪掉快取（那是這個帳號的私人資料）。設定檔裡 LINE 區的別的鍵留著。"""
        settings.update(self._settings, lambda data: settings.line_section(data).pop("url", None))
        with self._lock:
            self._queue.clear()
            self._reset(None)
            self._note = ""
            self._bump()
        return self.state()

    def _reset(self, account: str | None) -> None:
        self._cache = line_cache.Cache(account=account)
        self._cache_path.unlink(missing_ok=True)
        if account is not None:
            self._save()

    def on_open(self) -> dict:
        """打開行事曆：抓一次預設範圍；抓到最新資料之後做 on_success（自動複製）。"""
        return self._enqueue([(None, None, True)])

    def refresh(self) -> dict:
        """「立刻更新」：再抓一次預設範圍。"""
        return self._enqueue([(None, None, False)])

    def need(self, kind, key) -> dict:
        """翻到月（key=YYYY-MM）或年（key=YYYY）：沒有快取的部分補抓。格式不對就什麼都不做。"""
        window = self._window(kind, key)
        if window is None:
            return self.state()
        with self._lock:
            last = self._cache.last
            if last.get("ok") is False and (last["kind"] in STICKY_KINDS or self._clock() - last["at"] < NEED_COOLDOWN):
                return self.state()
        low, high = window
        today = _day(self._today())
        lowest, highest = today - BACK_DAYS * _ONE_DAY, today + FORWARD_DAYS * _ONE_DAY
        low, high = max(low, lowest), min(high, highest)
        if low > high:
            with self._lock:
                self._note = OUT_OF_RANGE
            return self.state()
        with self._lock:
            segments = [(low, high)]
            if self._current == (None, None) or any(job[:2] == (None, None) for job in self._queue):
                # 預設範圍正在抓（或排著）：它會蓋住的那一段不用另外抓（不然每次打開、頁面第一次重畫時都多送一個請求）
                first, last = today - DEFAULT_BACK * _ONE_DAY, today + DEFAULT_FORWARD * _ONE_DAY
                segments = [(low, min(high, first - _ONE_DAY)), (max(low, last + _ONE_DAY), high)]
            gaps = [gap for start, end in segments if start <= end
                    for gap in self._cache.missing(start.isoformat(), end.isoformat(), self._clock())]
        jobs = []
        for start, end in gaps:
            first, last = _day(start), _day(end)
            while first <= last:
                stop = min(last, first + (MAX_WINDOW_DAYS - 1) * _ONE_DAY)
                jobs.append((first.isoformat(), stop.isoformat(), False))
                first = stop + _ONE_DAY
        return self._enqueue(jobs[:MAX_YEAR_WINDOWS] if kind == "year" else jobs)

    @staticmethod
    def _window(kind, key) -> tuple[datetime.date, datetime.date] | None:
        try:
            if kind == "month" and isinstance(key, str) and len(key) == 7 and key[4] == "-":
                year, month = int(key[:4]), int(key[5:])
                first = datetime.date(year, month, 1)
                return first, (datetime.date(year + month // 12, month % 12 + 1, 1) - _ONE_DAY)
            if kind == "year" and isinstance(key, str) and len(key) == 4 and key.isascii() and key.isdigit():
                return datetime.date(int(key), 1, 1), datetime.date(int(key), 12, 31)
        except ValueError:
            pass
        return None

    def _enqueue(self, jobs: list[tuple[str | None, str | None, bool]]) -> dict:
        with self._lock:
            if self._url() is None or (self._cache.retry_until and self._clock() < self._cache.retry_until):
                return self.state()
            self._note = ""
            for job in jobs:
                if (job[0], job[1]) != self._current and all((job[0], job[1]) != (q[0], q[1]) for q in self._queue):
                    self._queue.append(job)
            start = bool(self._queue) and not self._running
            if start:
                self._running = True
                self._idle.clear()
        if start:
            self._spawn(self._work)
        return self.state()

    # ── 背景執行緒 ──

    def _work(self) -> None:
        try:
            while True:
                with self._lock:
                    if not self._queue:
                        return
                    low, high, opening = self._queue.pop(0)
                    self._current = (low, high)
                self._bump_after(self._run(low, high, opening))
        finally:  # 就算 on_success 之類丟了例外，狀態也要放開：不然「忙」永遠是 true、之後的工作都不會跑
            with self._lock:
                self._running, self._current = False, None
                self._idle.set()

    def _bump_after(self, changed: bool) -> None:
        if changed:
            with self._lock:
                self._bump()

    def _run(self, low: str | None, high: str | None, opening: bool) -> bool:
        """抓一段。成功回 True（資料變了）；失敗記下原因、丟掉佇列裡剩下的，回 True（狀態變了）。"""
        url = self._url()
        if url is None:
            return False
        try:
            parsed = line_data.parse(self._fetch(url, low, high))
        except line_net.LineError as exc:
            return self._failed(exc.kind, exc.message, exc.retry_after)
        except line_data.VersionError as exc:
            shown = exc.version if exc.version is not None else "不明"
            return self._failed("format", f"LINE 的資料是 version {shown}，這一版行事曆 2 只懂 version {line_data.VERSION}：請更新行事曆 2")
        except line_data.FormatError as exc:
            return self._failed("format", f"LINE 回的資料格式不對（{SECTION_NAMES.get(exc.section, exc.section)}），沒有更新快取")
        now = self._clock()
        with self._lock:
            self._cache.account = line_url.account_id(url)
            self._cache.add_slice(parsed, now, today=self._today())
            self._cache.record(True, None, "", now)
            self._cache.retry_until = None
            self._note = ""
            self._save()
        if opening and self._on_success is not None:
            self._on_success()
        return True

    def _failed(self, kind: str, message: str, retry_after: int | None = None) -> bool:
        now = self._clock()
        with self._lock:
            self._queue.clear()
            self._cache.record(False, kind, message, now)
            if kind == "rate_limit" and retry_after:
                self._cache.retry_until = now + retry_after
            self._save()
        return True
