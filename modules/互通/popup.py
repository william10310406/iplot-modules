"""彈出式視窗：面板外跑模組時的 View（D81）。平常藏著，有話才出來。

照核心的 View 做八個方法（docs/07 第 13 節）。執行緒的做法跟網頁面板一樣：主執行緒是 pywebview 的事件迴圈，
模組在工作執行緒上跑；頁面呼叫 Python 的方法只排工作、立刻回傳；對話框用 threading.Event 等頁面回答。
不 import ui/（ui/ 是核心的一部分，D80）；錯誤講成一句話用 core.errors.describe。"""

import contextlib
import itertools
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.errors import describe
from core.types import ErrorInfo, Scope

PAGE = Path(__file__).with_name("popup.html")
PANEL = "主控面板"  # 跑完之後底下那一列的回去鈕：最上層剛好一個「行事曆」就回行事曆（D93），否則回主控面板（D88）
CALENDAR = "行事曆"


def mac_dock(regular: bool) -> None:
    """macOS：藏著的期間不在 Dock（accessory），顯示時回到一般的 App（regular）。Task 0 量過：
    pywebview 在 import 平台模組時就設成 regular，所以先 import 它、再改。"""
    import AppKit
    import webview.platforms.cocoa  # noqa: F401  （設 regular 的那一行在這裡跑，要在它之後改）
    from PyObjCTools import AppHelper

    app = AppKit.NSApplication.sharedApplication()
    policy = (AppKit.NSApplicationActivationPolicyRegular if regular
              else AppKit.NSApplicationActivationPolicyAccessory)
    if threading.current_thread() is threading.main_thread():
        app.setActivationPolicy_(policy)
    else:
        AppHelper.callAfter(app.setActivationPolicy_, policy)


class Bridge:
    """頁面的 JS 用 pywebview.api.<方法> 呼叫的入口；小視窗放在 _popup，攤出去的只有這五個方法。"""

    def __init__(self, popup: "Popup") -> None:
        self._popup = popup

    def answer(self, ask_id: int, value: Any) -> None:
        """回答第 ask_id 個對話框：字串、true／false，或 null（取消）。"""
        self._popup.answer(ask_id, value)

    def open_error(self, error_id: int) -> None:
        """「打開檔案」：用編輯器打開第 error_id 筆錯誤的檔案，跳到那一行。"""
        self._popup.open_error(error_id)

    def stop(self) -> None:
        """「停止」：結束這一個程序（結束碼 1）。面板不受影響。"""
        self._popup.exit(1)

    def close(self) -> None:
        """「關閉」與倒數結束：關掉小視窗。"""
        self._popup.window.destroy()

    def panel(self) -> None:
        """回去鈕：跑最上層那個模組（「行事曆」或「主控面板」）；沒出錯就關掉小視窗（D93、D88）。"""
        self._popup.open_panel()


class Popup:
    """面板外的 View：一個藏著的 460×320 小視窗。log、report、ask、confirm、選檔案、選資料夾、跑太久，才把它叫出來。"""

    def __init__(self, home: Path, webview: Any, title: str = "iPLoT", busy_after: float = 1.0,
                 exit: Callable[[int], Any] = os._exit, dock: Callable[[bool], None] | None = None) -> None:
        self.home, self.webview, self.title, self.busy_after = home, webview, title, busy_after
        self.exit, self._dock = exit, dock
        self.core: Any = None
        self.window: Any = None
        self.errors: list[ErrorInfo] = []
        self._lock = threading.Lock()
        self._running = threading.Lock()  # 模組在跑的期間拿著；「打開檔案」等它跑完才做（runner 一次只跑一個）
        self._panel = threading.Lock()  # 回去鈕一次只跑一個：連按兩下不會開兩次
        self._back: str | None = None  # 回去鈕跑的模組名稱；done 時由 run.py 給
        self._paging = False  # app.page 的視窗開著：小視窗不因「跑太久」出來，關它也只是藏起來
        self._said = 0  # 小視窗說過幾次話（訊息、錯誤、執行中、問問題、跑完）；選檔案時用來判斷能不能藏回去
        self._ids = itertools.count(1)
        self._waiting: dict[int, tuple[threading.Event, list]] = {}
        self._worker: threading.Thread | None = None
        self._result: list = [1]
        self._shown = self._closed = self._finished = self._job_done = False

    def attach(self, core: Any) -> None:
        """接上 Core。"""
        self.core = core

    def run(self, job: Callable[[], int]) -> int:
        """開藏著的小視窗，進入 pywebview 的事件迴圈（佔住主執行緒）；頁面載入後在工作執行緒上跑 job。
        視窗關掉、事件迴圈結束之後等 job 做完，回它的結果。"""
        self._shown = self._closed = self._finished = self._job_done = False
        self._worker, self._result, self._back, self._paging = None, [1], None, False
        self.window = self.webview.create_window(
            self.title, url=PAGE.as_uri(), js_api=Bridge(self), width=460, height=320, min_size=(360, 220),
            hidden=True)
        self.window.events.loaded += lambda: self._loaded(job)
        self.window.events.closing += self._closing
        if self._dock:
            self._dock(False)
        self.webview.start()
        if self._worker is not None:
            self._worker.join()
        return self._result[0]

    def _loaded(self, job: Callable[[], int]) -> None:
        """頁面載入完成：先給頁面標題，再開工作執行緒；只做一次（重新載入不再跑一次）。"""
        self._js("init", {"title": self.title})
        if self._worker is None:
            self._worker = threading.Thread(target=self._work, args=(job,), daemon=True)
            self._worker.start()

    def _work(self, job: Callable[[], int]) -> None:
        timer = threading.Timer(self.busy_after, self._busy)
        timer.daemon = True
        with self._running:
            timer.start()
            try:
                self._result[0] = job()
            finally:
                timer.cancel()
                self._job_done = True

    def _busy(self) -> None:
        """跑了 busy_after 秒還沒結束：叫出來，顯示「執行中：<名稱>…」與「停止」。app.page 開著的時候不算：
        頁面就是模組的畫面（行事曆整天開著），多一個「執行中」的小視窗只會擋路。"""
        if not self._job_done and not self._finished and not self._paging:
            self._reveal()
            self._js("busy", self.title)

    def _reveal(self) -> None:
        """第一次有話要說：回到 Dock、顯示小視窗。之後不再做。"""
        with self._lock:
            if self._shown or self._closed:
                return
            self._shown = True
        if self._dock:
            self._dock(True)
        self.window.show()

    def _closing(self) -> bool | None:
        """使用者關掉小視窗：等著的對話框當作取消；模組還沒跑完就是「停止」，結束這個程序（結束碼 1）。
        app.page 的視窗開著、小視窗也看得見時例外：只把它藏起來（回 False，pywebview 就不關它），之後有話還能再出來。
        藏著的小視窗被問到，只會是整個 App 要結束（⌘Q、登出、關機：pywebview 會問每一個視窗）——那時不能擋。"""
        if self._paging and self._shown:
            self._cancel()
            self._hide()
            return False
        stopping = not self._job_done and not self._finished
        self._cancel(closed=True)
        if stopping:
            self.exit(1)

    def _hide(self) -> None:
        """藏回去：下一次有話要說時 _reveal 會再叫出來。App 留在 Dock（頁面開著，要找得回來）。"""
        with self._lock:
            if not self._shown:
                return
            self._shown = False
        self.window.hide()

    def _cancel(self, closed: bool = False) -> None:
        with self._lock:
            self._closed = self._closed or closed
            for event, _ in self._waiting.values():
                event.set()
            self._waiting.clear()

    def done(self, outcome: str, seconds: float, back: str | None = None) -> None:
        """模組跑完了：outcome 是 "ok"、"cancelled" 或 "error"。小視窗沒出現過、又沒出錯，就直接關；
        否則交給頁面：成功是「完成（x 秒），3 秒後關閉」的倒數，出錯是「出錯了」與「關閉」。
        back 是回去鈕上的名字、按下去跑的模組（D93：「行事曆」或「主控面板」；給不給、給哪個由 run.py 決定）。"""
        self._finished, self._back = True, back
        if not self._shown and outcome != "error":
            self.window.destroy()
            return
        self._reveal()
        self._js("done", outcome, round(seconds, 1), back)

    def open_panel(self) -> None:
        """回去鈕：在另一條執行緒上、等模組與同步跑完（跟「打開檔案」一樣），用這個 Core 跑最上層的 back 那個模組
        （「行事曆」或「主控面板」）。沒出錯就關掉小視窗；出錯照一般的錯誤顯示，小視窗留著。沒有 back 就不做事。
        程序的結束碼不變（還是原本那個模組的）。"""
        back = self._back
        if back is None:
            return

        def go() -> None:
            if not self._panel.acquire(blocking=False):
                return
            try:
                with self._running:
                    try:
                        result = self.core.run_by_name(back)
                    except LookupError as exc:  # 跑完之後才被刪掉、或有兩個
                        self.log(str(exc))
                        return
                if result.ok:
                    self.window.destroy()
            finally:
                self._panel.release()

        threading.Thread(target=go, daemon=True).start()

    def open_error(self, error_id: int) -> None:
        """「打開檔案」：在另一條執行緒上交給「作業系統」模組的 edit；模組還在跑的話等它跑完。"""
        if not (isinstance(error_id, int) and 0 <= error_id < len(self.errors)):
            return
        error = self.errors[error_id]
        if error.file is None:
            return

        def edit() -> None:
            with self._running:
                self.core.action("edit", error.file, self.core.config.editor, error.line)

        threading.Thread(target=edit, daemon=True).start()

    def _js(self, name: str, *args: Any) -> None:
        """呼叫頁面的 iplot.<name>(…)，參數寫成 JSON；視窗關了就不做。"""
        if name != "init":
            self._said += 1
        if not self._closed:
            with contextlib.suppress(Exception):  # 頁面壞了、視窗正在關：說不出來也不往外丟
                self.window.evaluate_js(f"iplot.{name}({', '.join(json.dumps(a) for a in args)})")

    def _dialog(self, kind: str, *args: Any) -> Any:
        """推一個對話框給頁面，等頁面用 answer(編號, 值) 回來；視窗關掉算取消（None）。"""
        self._reveal()
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
        """頁面回答了第 ask_id 個對話框；不認得的編號不理。"""
        with self._lock:
            event, box = self._waiting.pop(ask_id, (None, None))
            if event is not None:
                box[0] = value
                event.set()

    # View 的八個方法

    def show(self, scope: Scope) -> None:
        """小視窗沒有模組的清單：不做事。"""

    def log(self, text: str) -> None:
        """訊息區加一行（模組 print 的輸出也是，跑完時一行行送進來）。"""
        self._reveal()
        self._js("log", text)

    def report(self, error: ErrorInfo) -> None:
        """顯示錯誤：白話一句、「打開檔案」、「詳細」（traceback）。"""
        self._reveal()
        self.errors.append(error)
        self._js("report", {"kind": error.kind, "message": error.message,
                            "file": None if error.file is None else str(error.file), "line": error.line,
                            "traceback": error.traceback_text, "sentence": describe(error),
                            "id": len(self.errors) - 1})

    def ask(self, prompt: str, default: str = "") -> str | None:
        """小視窗裡的對話框問一個字串；按取消回 None。模組的 input() 也是這個。"""
        value = self._dialog("ask", prompt, default)
        return value if isinstance(value, str) else None

    def confirm(self, prompt: str) -> bool:
        """小視窗裡的「確定／取消」；按確定回 True。"""
        return self._dialog("confirm", prompt) is True

    def page(self, title: str, html: str, api: object | None) -> None:
        """另開一個 640×520 的視窗顯示一頁 HTML（app.page），關掉才回來；不會因此把小視窗叫出來。
        開之前回到一般的 App（在 Dock、在 ⌘-Tab 裡）：被別的視窗蓋住時要找得回來，模組在等它關。"""
        if self._dock:
            self._dock(True)
        self._paging = True
        try:
            window = self.webview.create_window(title, html=html, js_api=api, width=640, height=520)
            closed = threading.Event()
            window.events.closed += closed.set
            closed.wait()
        finally:
            self._paging = False

    def choose_files(self) -> list[Path]:
        """先叫出小視窗，再開原生的檔案選擇視窗；按取消回空清單。小視窗原本藏著、選的期間又沒說話，選完就藏回去。"""
        hidden, said = not self._shown, self._said
        self._reveal()
        try:
            found = self.window.create_file_dialog(self.webview.FileDialog.OPEN, allow_multiple=True)
        finally:
            if hidden and self._said == said:  # 對話框開著的期間有話要說（例如「執行中」）就留著
                self._hide()
        return [Path(p) for p in found or ()]

    def choose_folder(self) -> Path | None:
        """先叫出小視窗，再開原生的資料夾選擇視窗；按取消回 None。小視窗原本藏著、選的期間又沒說話，選完就藏回去。"""
        hidden, said = not self._shown, self._said
        self._reveal()
        try:
            found = self.window.create_file_dialog(self.webview.FileDialog.FOLDER)
        finally:
            if hidden and self._said == said:  # 對話框開著的期間有話要說（例如「執行中」）就留著
                self._hide()
        return Path(found[0]) if found else None
