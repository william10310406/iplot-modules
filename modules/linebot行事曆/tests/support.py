"""測試共用的東西：假網址、假的 LINE 回應、假的 app。

網址等於密碼：這裡只有明顯是假的 token；測試不連網、不用任何真網址。"""

import copy
import datetime
import pathlib
import types

MODULE = pathlib.Path(__file__).resolve().parents[1]
FAKE_TOKEN = "FAKE-TOKEN-0123456789abcdefghijklmnopqrstuv"
FAKE_HOST = "line.example.test"
FAKE_URL = f"https://{FAKE_HOST}/j/{FAKE_TOKEN}.json"
SENTINEL = "LINE-SENTINEL-8f3a"  # 放進 LINE 資料裡，用來掃「哪些輸出含有 LINE 的內容」


def event(**over):
    base = {"id": "e1", "title": "開會", "allDay": False, "start": "2026-11-06T10:00:00+08:00",
            "end": "2026-11-06T11:00:00+08:00", "startDate": "2026-11-06", "endDate": "2026-11-06",
            "location": "會議室", "note": "帶筆電", "private": False, "group": "工作群"}
    return {**base, **over}


def all_day_event(**over):
    base = {"id": "e2", "title": "出差", "allDay": True, "start": None, "end": None, "startDate": "2026-11-08",
            "endDate": "2026-11-10", "location": None, "note": None, "private": False, "group": None}
    return {**base, **over}


def task(**over):
    base = {"id": "t1", "title": "買牛奶", "dueDate": "2026-11-06", "dueTime": "18:00", "done": False,
            "private": False, "group": None, "note": None}
    return {**base, **over}


def log(**over):
    base = {"date": "2026-11-06", "private": False, "group": None,
            "items": [{"title": "寫程式", "details": "完成解析"}, {"title": "散步", "details": None}]}
    return {**base, **over}


def mood(**over):
    base = {"date": "2026-11-06", "face": "smile", "emoji": "🙂", "text": "還不錯"}
    return {**base, **over}


def jot(**over):
    base = {"id": "j1", "date": "2026-11-06", "text": "看到一隻貓", "createdAt": "2026-11-06T14:32:00+08:00"}
    return {**base, **over}


def line_payload(**over):
    """合法的 version 1 回應，每一區各有幾筆；over 換掉頂層的鍵。每次回新的一份（可以隨便改）。"""
    payload = {
        "version": 1, "generatedAt": "2026-11-06T16:40:00+08:00", "timezone": "Asia/Taipei",
        "range": {"from": "2026-10-02", "to": "2027-01-15"},
        "events": [event(), all_day_event()],
        "tasks": [task(), task(id="t2", title="交報告", dueTime=None, done=True),
                  task(id="t3", title="沒截止", dueDate=None, dueTime=None)],
        "logs": [log()], "moods": [mood()],
        "jots": [jot(), jot(id="j2", text="吃了蛋糕", createdAt="2026-11-06T09:05:00+08:00")],
    }
    payload.update(copy.deepcopy(over))
    return payload


class FakeApp:
    """app 的替身：記下被叫了什麼，不開任何視窗。"""

    def __init__(self, home: pathlib.Path, history_keep: int = 20):
        self.home = home
        self.config = types.SimpleNamespace(history_keep=history_keep, roots=[])
        self.logs, self.opened, self.trashed, self.pages = [], [], [], []
        self.chosen_folder = None

    def log(self, text):
        self.logs.append(text)

    def open(self, path):
        self.opened.append(pathlib.Path(path))

    def trash(self, path):
        self.trashed.append(pathlib.Path(path))

    def page(self, title, html, api=None):
        self.pages.append((title, html, api))

    def choose_folder(self):
        return self.chosen_folder


# ── 假的網路與時鐘（test_line_sync.py、test_api_line.py 共用）──

TAIPEI = datetime.timezone(datetime.timedelta(hours=8))
NOW = datetime.datetime(2026, 11, 8, 21, 45, tzinfo=TAIPEI).timestamp()   # 台北 2026-11-08 21:45


def day(offset, base="2026-11-08"):
    return (datetime.date.fromisoformat(base) + datetime.timedelta(days=offset)).isoformat()


class FakeLine:
    """假的 line_net.fetch：回合法的回應（range 照請求的給；沒給就是前 35 天到後 70 天），或丟出排好的例外。"""

    def __init__(self, today="2026-11-08"):
        self.calls, self.script, self.today = [], [], today
        self.gate = None  # 給一個 threading.Event：fetch 要等它才回

    def __call__(self, url, from_=None, to=None, **kw):
        self.calls.append((from_, to))
        if self.gate is not None:
            self.gate.wait(10)
        if self.script:
            outcome = self.script.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            if outcome is not None:
                return outcome
        low, high = from_ or day(-35, self.today), to or day(70, self.today)
        return line_payload(range={"from": low, "to": high}, events=[], tasks=[], logs=[], moods=[], jots=[])


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def taipei_ts(year, month, day_, hour=0, minute=0):
    """台北時間的 epoch 秒。"""
    return datetime.datetime(year, month, day_, hour, minute, tzinfo=TAIPEI).timestamp()
