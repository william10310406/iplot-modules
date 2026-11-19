"""另開程序：有頁面的模組在網頁面板裡按下時，經 run.py 另開一個程序開頁面，面板不會被卡住。

為什麼：網頁面板只有一條工作執行緒，`app.page` 等到視窗關掉才回來（ui/web.py 的 WebPanel.page），頁面開著的期間，
在面板上按別的模組都只會排隊，關掉之後才一次跳出來。行事曆早就這樣繞開（D89）；這裡把它的做法抽出來給每個模組用。

用法（模組的 run 裡、app.page 之前）：

    if not separate.here(app):
        return

here(app) 回 True：就在這個程序裡開頁面——已經是另開的程序（捷徑、run.py）、tkinter 面板、沒有 run.py、另開失敗。
回 False：已經另開了，或同一個模組早就開著、叫到最前面了；模組直接結束。
同一個模組只開一個：另開的程序把自己的 pid 寫進模組資料夾的 .pid，結束時拿掉。

別的模組的 sys.path[0] 是它自己的資料夾，所以要用檔案路徑載入這個檔（importlib.util.spec_from_file_location），
這個檔也因此只 import 標準庫。要在 Python 3.8 讀得懂（跟 run.py、boot.py 一樣）。"""

from __future__ import annotations

import atexit
import errno
import os
import subprocess
import sys
import unicodedata
from pathlib import Path

PID = ".pid"
RUN_PY = ("modules", "互通", "run.py")
OPENED = "在另一個視窗打開「{title}」"
ALREADY = "「{title}」已經開著"
ALREADY_BEHIND = "「{title}」已經開著（在 Dock 上找 Python 的圖示）"
FAILED = "沒辦法另開視窗（{why}），改在這裡打開「{title}」；開著的期間，面板上按別的模組會等它關掉才跑"
REASONS = {errno.ENOENT: "找不到檔案或資料夾", errno.EACCES: "沒有權限", errno.EPERM: "沒有權限",
           errno.ENOMEM: "記憶體不夠", errno.EAGAIN: "系統現在開不了新的程式"}
# macOS 14 起，自己不在最前面的 App 叫別人到最前面會被拒絕；不是 App 的一般 python 程序叫就可以（跟「主控面板」「行事曆」同一段）。
HELPER = ("import sys\n"
          "sys.path.insert(0, sys.argv[1])\n"
          "import AppKit\n"
          "app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(int(sys.argv[2]))\n"
          "sys.exit(0 if app is not None and app.activateWithOptions_("
          "AppKit.NSApplicationActivateIgnoringOtherApps) else 1)\n")


def _ps() -> str:
    """所有程序的 pid 與完整指令。一定用 UTF-8 的 locale 叫 ps（從 Dock 開的程式沒有 locale，中文路徑會變成跳脫字）；-ww 不截斷。"""
    try:
        return subprocess.run(["ps", "-axww", "-o", "pid=,command="], capture_output=True, encoding="utf-8",
                              errors="replace", env={**os.environ, "LC_ALL": "en_US.UTF-8"}, check=False).stdout
    except OSError:
        return ""


def activate(pid: int, platform: str = sys.platform, run=subprocess.run) -> bool:
    """把 pid 叫到最前面；macOS 以外、或載不進 AppKit 就回 False。"""
    if platform != "darwin":
        return False
    try:
        import AppKit
    except ImportError:
        return False
    app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is not None and app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps):
        return True
    lib = str(Path(AppKit.__file__).parents[1])
    try:
        done = run([sys.executable, "-c", HELPER, lib, str(pid)], stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def running_pid(folder: Path, ps=_ps, me: int | None = None) -> int | None:
    """資料夾裡 .pid 記的程序還活著、而且它的指令是 run.py 開這個資料夾（指令的結尾是這個資料夾），才回它的 pid；
    否則 None（過期、pid 被別的程式重用了、是自己）。用結尾比，「工作坊」才不會被當成「工作坊 2」。"""
    me = os.getpid() if me is None else me
    try:
        pid = int((folder / PID).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if pid == me:
        return None
    target = unicodedata.normalize("NFC", str(folder))
    for line in unicodedata.normalize("NFC", ps()).splitlines():
        pid_text, _, command = line.strip().partition(" ")
        if pid_text == str(pid):
            command = command.rstrip()
            return pid if "run.py" in command and command.endswith(target) else None
    return None


def _claim(folder: Path, at_exit) -> None:
    """另開的程序：把自己的 pid 寫進 .pid，結束時拿掉；寫不進去就算了（只是少了「已經開著」的判斷）。"""
    pid_file = folder / PID
    try:
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        return

    def cleanup() -> None:
        try:
            if pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
                pid_file.unlink()
        except OSError:
            pass

    at_exit(cleanup)


def here(app, *, modules=sys.modules, ps=_ps, popen=subprocess.Popen, activate=activate,
         platform: str | None = None, me: int | None = None, python: str = sys.executable,
         at_exit=atexit.register) -> bool:
    """這個模組的頁面要不要在這個程序裡開（見檔頭）。"""
    folder, title = app.module.folder, app.module.title
    pid = running_pid(folder, ps, me)
    if pid is not None:
        shown = activate(pid, platform or sys.platform)
        app.log((ALREADY if shown else ALREADY_BEHIND).format(title=title))
        return False
    if "ui.web" not in modules or "ui.tk" in modules:  # 不在網頁面板裡：另開的程序、捷徑，或 tkinter 面板（沒有頁面）
        if "ui.tk" not in modules:
            _claim(folder, at_exit)
        return True
    run_py = Path(app.home).joinpath(*RUN_PY)
    if not run_py.is_file():
        return True
    try:
        popen([python, str(run_py), str(folder)], start_new_session=True,
              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        app.log(FAILED.format(why=REASONS.get(exc.errno, "系統拒絕了"), title=title))
        return True
    app.log(OPENED.format(title=title))
    return False
