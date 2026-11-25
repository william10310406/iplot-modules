"""網頁面板：pywebview 開的原生視窗裡跑這個資料夾的 index.html（D162：面板是模組，核心不知道它）。

只用開機程式交來的核心的公開方法（scope、enter、back、press、create、action、rescan、each、providers、describe、
report_internal），不 import 核心的任何東西；ModuleInfo、ErrorInfo、Scope 是核心交來的資料，只讀欄位。
WebPanel 實作 core.View，把 show／log／report／ask 翻成對頁面的呼叫（iplot.<名字>(…)）；
Bridge 是頁面呼叫 Python 的入口，動作都排進單一工作執行緒交給 Core。沒有 server、沒有 port：
頁面用 file:// 載入，JS 直接呼叫 Python（pywebview 的 js_api）。Core 不知道執行緒的存在。"""

import base64
import contextlib
import itertools
import json
import os
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import panel_menu
from panel_text import T

Core = ModuleInfo = ErrorInfo = Scope = Any  # 核心交來的物件：這裡只讀欄位、呼叫公開方法，不 import 核心
ERROR_ROLE = "panel.error"  # 錯誤那一列的「回報這個問題」與自動問「要回報嗎？」交給提供它的模組（D110、D150）
HERE = Path(__file__).resolve().parent  # index.html、app.js、style.css 在這裡
RECENT = 40          # 最近的訊息留幾行
WINDOW = 600.0       # 同一種錯誤（類型、檔案、行號）幾秒內只問一次

MAX_ICON = 1024 * 1024  # 圖示檔的上限：1 MB（D65）
MIME = {".png": "image/png", ".svg": "image/svg+xml"}
PATHS = {"here": "modules/", "parent": "../"}  # 組標題旁邊顯示的路徑；extra 顯示 config 裡寫的那個字串
ACTIONS = ("reveal", "terminal")  # 頁面可以要求「作業系統」模組做的事；另有 edit，參數不同
_icons: dict[Path, tuple[tuple[int, int], str]] = {}  # 圖示檔 →（（修改時間, 大小）, data URI）


def _data_uri(file: Path) -> str | None:
    """圖示檔變成 data URI；空的、超過 1 MB 或讀不到回 None。檔案沒變就用上次讀的。
    內容是不是一張讀得出來的圖，要到頁面上才知道：讀不出來時頁面自己換成預設圖示（app.js 的 iconEl）。"""
    try:
        stat = file.stat()
        if not 0 < stat.st_size <= MAX_ICON:
            return None
        stamp = (stat.st_mtime_ns, stat.st_size)
        if _icons.get(file, (None, ""))[0] != stamp:
            data = base64.b64encode(file.read_bytes()).decode("ascii")
            _icons[file] = (stamp, f"data:{MIME[file.suffix]};base64,{data}")
        return _icons[file][1]
    except OSError:
        return None


def icon_for(info: ModuleInfo, warned: set[Path], log: Callable[[str], None]) -> dict | None:
    """圖示的來源依序：資料夾裡的圖檔 → ICON 常數 → None（頁面用名字第一個字）。
    圖檔不能用就當作沒有，並用 log 記一行；warned 記著說過的檔，每個檔只說一次。"""
    if info.icon_file is not None:
        uri = _data_uri(info.icon_file)
        if uri is not None:
            return {"file": uri}
        if info.icon_file not in warned:
            warned.add(info.icon_file)
            log(T["icon_unusable"].format(title=info.title))
    return {"text": info.icon} if info.icon else None


def scope_json(scope: Scope, icon_for: Callable[[ModuleInfo], dict | None]) -> dict:
    """Scope 變成給頁面的 JSON（規格附錄 A）。進到下一層時只有一組，level 是 child；
    root 是那一組的資料夾，頁面按 ＋ 時原樣傳回來。"""
    nested = len(scope.crumbs) > 1
    return {"crumbs": list(scope.crumbs), "groups": [{
        "label": g.label, "level": "child" if nested else g.level,
        "path": g.root.name + "/" if nested else PATHS.get(g.level, g.label), "root": str(g.root), "note": g.note,
        "modules": [{"id": str(m.folder), "name": m.name, "title": m.title, "description": m.description,
                     "icon": icon_for(m), "has_children": m.has_children, "error": m.error}
                    for m in g.modules]} for g in scope.groups]}


def error_json(error: ErrorInfo, sentence: str) -> dict:
    """ErrorInfo 變成給頁面的 JSON：白話那一句（sentence，核心的 describe 算的）與 traceback 分開，怎麼排由頁面決定。"""
    return {"kind": error.kind, "message": error.message,
            "file": None if error.file is None else str(error.file), "line": error.line,
            "traceback": error.traceback_text, "source": error.source, "module": error.module,
            "sentence": sentence}


def is_module(folder: Path) -> bool:
    """folder 是資料夾（不是符號連結），裡面有檔名剛好是 iplot.py 的檔案；讀不到就不是。
    抄自 core/scan.py 的 is_module（tools/copies.json 登記）：面板不 import 核心。"""
    with contextlib.suppress(OSError):  # APFS 不分大小寫，所以比對 listdir 的實際檔名，iPLoT.py 不算
        return (not folder.is_symlink() and folder.is_dir()
                and "iplot.py" in os.listdir(folder) and (folder / "iplot.py").is_file())
    return False


class Recent:
    """訊息區最近的 RECENT 行（log 與 report 各記一行）：交給 panel.error 的提供者附在回報裡。"""

    def __init__(self) -> None:
        self._lines: deque[str] = deque(maxlen=RECENT)

    def add(self, text: str) -> None:
        self._lines.extend(str(text).splitlines() or [""])

    def lines(self) -> list[str]:
        return list(self._lines)


class Offer:
    """自動跳出「出錯了，要回報嗎？」該不該問（D150）：同一種錯誤 WINDOW 秒內只問一次；勾了「這次執行期間不要再問」
    （muted）之後都不問。config.py 的錯誤（自己改壞的設定）、在 input() 的提問框按取消不問。哪些錯誤值得回報
    （例如學生作業不算）由 panel.error 的提供者決定，不在這裡。只記在記憶體。"""

    def __init__(self, window: float = WINDOW, clock: Callable[[], float] = time.monotonic) -> None:
        self._window, self._clock = window, clock
        self._asked: dict[tuple, float] = {}
        self.muted = False

    def due(self, error: ErrorInfo) -> bool:
        if self.muted or error.source == "config" or error.kind == "InputCancelled":
            return False
        key, now = (error.kind, str(error.file), error.line), self._clock()
        if now - self._asked.get(key, -self._window) < self._window:
            return False
        self._asked[key] = now
        return True


class Bridge:
    """頁面的 JS 用 pywebview.api.<方法> 呼叫的入口。除了 state 與 answer，都只把工作排進工作執行緒、
    立刻回傳。頁面傳來的 id、資料夾、動作名稱只認目前面板上有的，其餘一律當作「畫面過期了」重掃。錯誤的編號
    （open_error、report_error）只認 errors 裡有的，其餘什麼都不做；report_error 交給提供 panel.error 的模組，
    沒有了就什麼都不做。
    面板放在 _panel：pywebview 會把公開屬性一路攤開進 pywebview.api，底線讓攤出去的只有下面這些方法。
    這是整潔，不是安全邊界；真正的邊界是頁面不載入任何外來的內容（零外部資源、模組的輸出一律當文字）。"""

    def __init__(self, panel: "WebPanel") -> None:
        self._panel = panel

    def _on(self, id: str, fn: Callable[[Core, Any], object], find: Callable[[str], Any] | None = None) -> None:
        """排一件工作：用 find（預設找模組）把頁面給的 id 找回來，交給 fn(core, 找到的)；找不到就重掃。"""
        def job() -> None:
            core, found = self._panel.core, (find or self._panel.find)(id)
            if found is None:  # 不在面板上，或資料夾已經被刪掉
                core.rescan()
            else:
                fn(core, found)
        self._panel.submit(job)

    def state(self) -> dict:
        """目前的範圍（跟 iplot.show 收到的一樣）。"""
        return scope_json(self._panel.core.scope, self._panel.icon)

    def press(self, id: str) -> None:
        """執行模組。"""
        self._on(id, self._panel.press)

    def enter(self, id: str) -> None:
        """進入下一層。"""
        self._on(id, lambda core, info: core.enter(info))

    def back(self, depth: int) -> None:
        """麵包屑回上；0 是頂層。"""
        self._panel.submit(lambda: self._panel.core.back(int(depth)))

    def create(self, parent: str, name: str) -> None:
        """在某一組的資料夾（那一組的 root）新增模組。"""
        self._on(parent, lambda core, root: core.create(root, name), self._panel.root)

    def add_child(self, id: str, name: str) -> None:
        """在模組底下新增下一層模組。"""
        self._on(id, lambda core, info: core.create(info.folder, name))

    def menu(self, id: str) -> None:
        """右鍵選單打開了：問提供 menu.module 的模組要加哪些項目，用 iplot.menu(id, 顯示的字) 送回頁面（D159）。"""
        self._on(id, self._panel.menu)

    def menu_pick(self, index: int) -> None:
        """按了模組提供的第 index 項：交給提供它的模組，參數是那一格的模組。"""
        if type(index) is int and 0 <= index < len(items := self._panel.menu_items):
            self._panel.submit(lambda: self._panel.press(self._panel.core, *items[index], quiet=True))

    def action(self, name: str, id: str) -> None:
        """右鍵選單的 edit／reveal／terminal，交給「作業系統」模組做。"""
        if name == "edit":
            self._on(id, lambda core, info: core.action("edit", info.file, core.config.editor, None))
        elif name in ACTIONS:
            self._on(id, lambda core, info: core.action(name, info.folder))

    def open_error(self, error_id: int) -> None:
        """「打開檔案」：用編輯器打開第 error_id 筆回報的檔案，跳到出錯的那一行。"""
        errors, core = self._panel.errors, self._panel.core
        if isinstance(error_id, int) and 0 <= error_id < len(errors) and errors[error_id][0].file is not None:
            error = errors[error_id][0]
            self._panel.submit(lambda: core.action("edit", error.file, core.config.editor, error.line))

    def report_error(self, error_id: int) -> None:
        """「回報這個問題」：第 error_id 筆交給提供 panel.error 的模組，pressed 是 True（D110）。"""
        errors = self._panel.errors
        if isinstance(error_id, int) and 0 <= error_id < len(errors):
            error, recent = errors[error_id]
            self._panel.submit(lambda: self._panel.hand_over(error, recent, True))

    def rescan(self) -> None:
        """重掃（視窗取得焦點時頁面會呼叫，D11）。"""
        self._panel.submit(self._panel.core.rescan)

    def answer(self, ask_id: int, value: Any) -> None:
        """回答第 ask_id 個對話框：字串、true／false，或 null（取消）。"""
        self._panel.answer(ask_id, value)


class WebPanel:
    """iPLoT 的主視窗（網頁版）：上面是麵包屑和一組組圖示，下面是狀態列和訊息區。實作 core.View。"""

    def __init__(self, home: Path, version: str, safe: bool, webview: Any = None,
                 folder: Path = HERE) -> None:
        if webview is None:
            try:
                import webview  # lib/ 裡的 pywebview
            except ImportError as exc:  # 沒有它 iPLoT 照樣開：開機程式接到 ImportError 就去裝，裝不了就開後備面板（R4）
                raise ImportError(str(exc)) from exc
        self.home, self.version, self.safe, self.webview, self.folder = home, version, safe, webview, folder
        self.core: Core | None = None
        self.window: Any = None
        self.errors: list[tuple[ErrorInfo, list[str]]] = []  # 回報過的錯誤與那時候最近的訊息；頁面用編號指回來
        self._jobs: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._waiting: dict[int, tuple[threading.Event, list]] = {}  # 等回答的對話框
        self._closed = False
        self.menu_items: list[tuple[ModuleInfo, str, tuple]] = []  # 右鍵選單上模組提供的項目：（提供者, 函式名, (那一格,)）
        self._busy, self._pages = [], []  # 還在跑的模組、頁面開著的模組（標題），按下的順序
        self._warned: set[Path] = set()
        self.recent, self.offer, self.name = Recent(), Offer(), "網頁"  # 最近的訊息；要回報嗎的節流（D150）；app.panel（D164）
        self.restarting = False  # app.restart（D166）：視窗關掉之後 start 重新啟動

    def attach(self, core: Core) -> None:
        """接上 Core；之後頁面的動作都交給它。"""
        self.core = core

    def run(self) -> None:
        """開視窗，進入 pywebview 的事件迴圈（佔住主執行緒）；視窗關掉才回傳。"""
        title = T["title"].format(version=self.version) + (T["safe_mode"] if self.safe else "")
        self.window = self.webview.create_window(
            title, url=(self.folder / "index.html").as_uri(), js_api=Bridge(self),
            width=820, height=620, min_size=(480, 420))
        self.window.events.loaded += self._loaded
        self.window.events.closing += lambda: self._cancel(closed=True)
        self.webview.start()

    def restart(self) -> None:
        """app.restart（D166）：關掉視窗；事件迴圈結束後 iplot.py 的 start 重新啟動整個 iPLoT。"""
        self.restarting = True
        self.window.destroy()

    def _loaded(self) -> None:
        """頁面載入完成：先把文字整份送進去，工作執行緒才開始做事，頁面拿到文字之前不會收到別的呼叫。"""
        self._cancel()  # 重新載入的話，舊頁面上的對話框已經不在了
        self._js("init", {"text": T, "version": self.version, "safe": self.safe})
        self.submit(self.core.rescan)
        if self._worker is None:  # 第一次載入（啟動）
            self.submit(self._scanned)
            self._worker = threading.Thread(target=self._work, daemon=True)
            self._worker.start()

    def _scanned(self) -> None:
        roots = T["list_sep"].join(PATHS.get(g.level, g.label) for g in self.core.scope.groups)
        self.log(T["scanned"].format(roots=roots, count=len(self.core.all_modules())))

    def _cancel(self, closed: bool = False) -> None:
        """等回答的對話框全部當作按了取消；closed（視窗關了）之後不再對頁面說話，新的對話框直接回取消。"""
        with self._lock:
            self._closed = self._closed or closed
            for event, _ in self._waiting.values():
                event.set()
            self._waiting.clear()

    def _work(self) -> None:
        """工作執行緒：一次只做一件。沒接住的例外交給 core.report_internal，迴圈繼續。"""
        while True:
            job = self._jobs.get()
            try:
                if not self._closed:  # 視窗關了：排著還沒做的工作不再做
                    job()
            except Exception as exc:  # noqa: BLE001  規格 §11 允許的三處之一：一件工作出錯，面板不能就此不動
                self.core.report_internal(type(exc), exc, exc.__traceback__)
            finally:
                self._jobs.task_done()

    def press(self, core: Core, info: ModuleInfo, handler: str = "run", args: tuple = (), quiet: bool = False) -> None:
        """執行模組，前後各告訴頁面一聲：輸出要等模組結束才進訊息區，執行期間頁面得看得出它還在跑。
        也用來跑模組的某個 handler（回報這個問題）。每按一次另開程序時（D161），另開一條執行緒等它，
        工作執行緒馬上空出來：頁面開著的時候按別的模組也馬上開始跑。狀態列顯示還在跑的最後一個。"""
        def wait() -> None:
            self._mark(self._busy, info.title, True)
            try:
                core.press(info, handler, args, quiet)
            finally:
                self._mark(self._busy, info.title, False)
        threading.Thread(target=wait, daemon=True).start() if getattr(core, "separate", False) else wait()

    def paging(self, title: str, opened: bool) -> None:
        """工作程序裡的模組開了（opened）或關了頁面（D166）：頁面開著的期間狀態列不說它「執行中」。"""
        self._mark(self._pages, title, opened)

    def _mark(self, names: list[str], title: str, on: bool) -> None:
        """記下或拿掉一個標題，狀態列顯示還在跑、頁面又沒開著的最後一個。"""
        with self._lock:
            (names.append if on else names.remove)(title)
            shown = next((t for t in reversed(self._busy) if t not in self._pages), None)
        self._js("busy", shown)

    def menu(self, core: Core, info: ModuleInfo) -> None:
        """右鍵選單上模組提供的項目（見 Bridge.menu）。"""
        self.menu_items, labels = panel_menu.items(core, info)
        self._js("menu", str(info.folder), labels)

    def submit(self, job: Callable[[], object]) -> None:
        """排一件工作給工作執行緒，立刻回傳。"""
        self._jobs.put(job)

    def wait(self) -> None:
        """等排著的工作全部做完（測試用）。"""
        self._jobs.join()

    def find(self, id: str) -> ModuleInfo | None:
        """目前面板上資料夾是 id 的模組；不在面板上、或那個資料夾已經不是模組（被刪了）就回 None。"""
        return next((m for m in self.core.all_modules() if str(m.folder) == id and is_module(m.folder)), None)

    def root(self, path: str) -> Path | None:
        """目前面板上資料夾是 path 的那一組的資料夾；沒有這一組就回 None。"""
        return next((g.root for g in self.core.scope.groups if str(g.root) == path), None)

    def icon(self, info: ModuleInfo) -> dict | None:
        """info 的圖示（見 icon_for）。"""
        return icon_for(info, self._warned, self.log)

    def _js(self, name: str, *args: Any) -> None:
        """呼叫頁面的 iplot.<name>(…)。參數用 JSON 寫進去：JSON 就是合法的 JS 字面值，不另外轉義；
        非 ASCII 一律寫成 \\uXXXX，名稱裡有引號、反斜線、換行都不會壞。視窗關了就不做。"""
        if not self._closed:
            self.window.evaluate_js(f"iplot.{name}({', '.join(json.dumps(a) for a in args)})")

    def show(self, scope: Scope) -> None:
        """把範圍交給頁面，整個重畫。"""
        self._js("show", scope_json(scope, self.icon))

    def log(self, text: str) -> None:
        """訊息區末尾加一行。"""
        self.recent.add(text)
        self._js("log", text)

    def report(self, error: ErrorInfo) -> None:
        """訊息區顯示錯誤：白話一句，「打開檔案」與「詳細」由頁面排。頁面壞到顯示不了也不往外丟。
        有模組提供 panel.error（而且不是它自己出的錯）才有「回報這個問題」；這一筆也排一件工作交給它看一眼（D150）。"""
        if error.kind == "InputCancelled":  # 在提問框按了取消：自己的動作，訊息區只說一行，不是錯誤（體驗 2-08b）
            self.log(T["module_cancelled"].format(module=error.module))
            return
        sentence = self.core.describe(error)
        self.recent.add(sentence)
        self.errors.append((error, self.recent.lines()))
        reportable = self.reporter(error) is not None
        with contextlib.suppress(self.webview.JavascriptException):
            self._js("report", {**error_json(error, sentence), "id": len(self.errors) - 1, "reportable": reportable})
        if reportable:
            recent = self.errors[-1][1]
            self.submit(lambda: threading.Thread(target=self.hand_over, args=(error, recent, False), daemon=True).start())

    def reporter(self, error: ErrorInfo) -> ModuleInfo | None:
        """提供 panel.error 的第一個模組；它自己出的錯不交給它（不然它壞了就會一直轉）。"""
        found = [m for m in self.core.providers(ERROR_ROLE) if m.name != error.module]
        return found[0] if found else None

    def hand_over(self, error: ErrorInfo, recent: list[str], pressed: bool) -> None:
        """交給 panel.error 的提供者：pressed 是按了「回報這個問題」。沒按的時候它回 True 表示值得回報（例如它判斷
        學生作業的錯誤不算），面板再看節流、問「出錯了，要回報嗎？」，答回報就再交一次、pressed 是 True。"""
        info = self.reporter(error)
        if info is None:
            return
        handler = dict(info.provides)[ERROR_ROLE]
        if pressed:  # 它多半會開一頁：跟按下模組一樣另開執行緒等，工作執行緒不卡
            self.press(self.core, info, handler, (error, recent, True), quiet=True)
            return
        result = self.core.press(info, handler, (error, recent, False), quiet=True)
        if result.value is not True or not self.offer.due(error):
            return
        answer = self._dialog("offer", T["offer_report"].format(sentence=self.core.describe(error)))
        answer = answer if isinstance(answer, dict) else {}
        self.offer.muted = self.offer.muted or answer.get("mute") is True
        if answer.get("report") is True:
            self.press(self.core, info, handler, (error, recent, True), quiet=True)

    def _dialog(self, kind: str, *args: Any) -> Any:
        """推一個對話框給頁面，等頁面用 answer(編號, 值) 回來；視窗關掉、頁面重新載入都算取消（None）。"""
        event, box = threading.Event(), [None]
        with self._lock:
            if self._closed:
                return None
            ask_id = next(self._ids)
            self._waiting[ask_id] = (event, box)
        self._js(kind, ask_id, *args)
        event.wait()
        return box[0]

    def answer(self, ask_id: int, value: Any) -> None:
        """頁面回答了第 ask_id 個對話框；不認得的編號（答過了、取消了）不理。"""
        with self._lock:
            event, box = self._waiting.pop(ask_id, (None, None))
            if event is not None:
                box[0] = value
                event.set()

    def ask(self, prompt: str, default: str = "") -> str | None:
        """面板內的對話框問一個字串；按取消回 None。模組的 input() 也是這個。"""
        value = self._dialog("ask", prompt, default)
        return value if isinstance(value, str) else None

    def confirm(self, prompt: str) -> bool:
        """面板內的「確定／取消」對話框；按確定回 True。"""
        return self._dialog("confirm", prompt) is True

    def choose_files(self) -> list[Path]:
        """原生的檔案選擇視窗（D67）；按取消回空清單。"""
        found = self.window.create_file_dialog(self.webview.FileDialog.OPEN, allow_multiple=True)
        return [Path(p) for p in found or ()]

    def choose_folder(self) -> Path | None:
        """原生的資料夾選擇視窗；按取消回 None。"""
        found = self.window.create_file_dialog(self.webview.FileDialog.FOLDER)
        return Path(found[0]) if found else None
