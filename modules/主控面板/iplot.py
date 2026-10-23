"""主控面板：打開 iPLoT 的面板；已經開著就叫到最前面。任何模組寫 app.run("主控面板") 就會用到這裡。"""
import os
import pathlib
import re
import subprocess

# ── 互通 ── 直接執行這個檔（python3 iplot.py）時交給 iPLoT 用彈出式視窗跑；從 iPLoT 裡執行時這段不做事。不要可以整段刪掉
import sys

if __name__ == "__main__" and "core.runner" not in sys.modules:
    import os
    import subprocess
    here = folder = os.path.dirname(os.path.abspath(__file__))
    run = None
    while run is None and folder != os.path.dirname(folder):  # 往上一層層找 iPLoT：模組在它裡面或旁邊都找得到
        folder = os.path.dirname(folder)
        try:
            names = [""] + sorted(os.listdir(folder))
        except OSError:
            names = [""]
        runs = (os.path.join(folder, n, "modules", "互通", "run.py") for n in names)
        run = next((r for r in runs if os.path.isfile(r)), None)
    if run and not os.environ.get("IPLOT_DIRECT"):  # IPLOT_DIRECT=1：不交出去，照一般腳本跑（例如在編輯器裡除錯）
        sys.exit(subprocess.call([sys.executable, run, here, *sys.argv[1:]]))
    if not run:
        print("找不到 iPLoT 的「互通」（先在工作坊裝「互通」；模組要放在 iPLoT 資料夾裡或它旁邊），照一般的 python3 iplot.py 跑",
              file=sys.stderr)
# ── 互通 ──

ICON = "🎛️"
# macOS 14 起，自己不在最前面的 App 叫別人到最前面會被拒絕；不是 App 的一般 python 程序叫就可以（2026-10-07 量過）。
# 被拒絕時交給這一小段在子程序裡叫：argv 是 [-c, lib 的路徑, pid]
HELPER = ("import sys\n"
          "sys.path.insert(0, sys.argv[1])\n"
          "import AppKit\n"
          "app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(int(sys.argv[2]))\n"
          "sys.exit(0 if app is not None and app.activateWithOptions_("
          "AppKit.NSApplicationActivateIgnoringOtherApps) else 1)\n")


def in_panel(modules=sys.modules) -> bool:
    """現在是不是在面板的程序裡（網頁面板或 tkinter 面板）。"""
    return "ui.web" in modules or "ui.tk" in modules


def _ps() -> str:
    """所有程序的 pid 與完整指令。一定用 UTF-8 的 locale 叫 ps：沒設定 locale 時（從 Spotlight、Dock 開的程式就是），
    ps 把中文路徑寫成 M-fM^H… 這種跳脫字（2026-10-07 在 Mac 上看到的）；-ww 不截斷。"""
    try:
        return subprocess.run(["ps", "-axww", "-o", "pid=,command="], capture_output=True, encoding="utf-8",
                              errors="replace", env={**os.environ, "LC_ALL": "en_US.UTF-8"}, check=False).stdout
    except OSError:
        return ""


def _lsof(pid: int) -> str:
    try:
        return subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True,
                              check=False).stdout
    except OSError:
        return ""


def _same(a: str, b: pathlib.Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def find_panel(home: pathlib.Path, ps=_ps, lsof=_lsof, me: int | None = None) -> int | None:
    """開著的面板的 pid：指令有 python（不分大小寫）也有 main.py 的程序，不算自己；指令裡有 <iPLoT>/main.py 就算，
    只寫 main.py 的（iPLoT.command 就是這樣開的）再看它的工作目錄是不是 iPLoT。找不到回 None。"""
    import unicodedata  # 檔頭只放排在 sys 之前的 import：那一小段的 import sys 接在它們後面（ruff 的 I001）

    me = os.getpid() if me is None else me
    target = unicodedata.normalize("NFC", str(home / "main.py"))  # 同一個路徑可能是 NFC 或 NFD，兩邊都換成 NFC 再比
    for line in unicodedata.normalize("NFC", ps()).splitlines():
        pid_text, _, command = line.strip().partition(" ")
        if not pid_text.isdigit() or int(pid_text) == me:
            continue
        if "python" not in command.lower() or "main.py" not in command:
            continue
        if target in command:
            return int(pid_text)
        if re.search(r"(^|\s)main\.py(\s|$)", command):
            cwd = next((row[1:] for row in lsof(int(pid_text)).splitlines() if row.startswith("n")), "")
            if cwd and _same(cwd, home):
                return int(pid_text)
    return None


def activate(pid: int | None, platform: str = sys.platform, run=subprocess.run) -> bool:
    """把 pid（None 是自己）叫到最前面；macOS 以外、或載不進 AppKit（lib/ 裡的 pyobjc）就回 False。"""
    if platform != "darwin":
        return False
    try:
        import AppKit
    except ImportError:
        return False
    running = AppKit.NSRunningApplication
    app = running.currentApplication() if pid is None else running.runningApplicationWithProcessIdentifier_(pid)
    if app is not None and app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps):
        return True
    lib = str(pathlib.Path(AppKit.__file__).parents[1])
    target = os.getpid() if pid is None else pid
    try:
        done = run([sys.executable, "-c", HELPER, lib, str(target)], stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def launch(home: pathlib.Path, python: str, popen=subprocess.Popen) -> None:
    """開一個新的面板：跟這個程序分開（關掉這個模組的小視窗不會連帶關掉面板）。"""
    popen([python, str(home / "main.py")], cwd=str(home), start_new_session=True,
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_panel(app, home: pathlib.Path, *, modules=None, ps=_ps, lsof=_lsof, popen=subprocess.Popen, activate=activate,
               platform: str | None = None, me: int | None = None) -> None:
    """三種情況：在面板的程序裡（叫自己到最前面）；在面板外、面板開著（叫它到最前面）；在面板外、面板沒開（開一個）。"""
    modules = sys.modules if modules is None else modules
    platform = platform or sys.platform
    if in_panel(modules):
        if platform == "darwin":
            activate(None, platform)
        app.log("主控面板已經開著")
        return
    pid = find_panel(home, ps, lsof, me) if platform == "darwin" else None
    if pid is not None:
        app.log("主控面板已經開著，叫到最前面了" if activate(pid, platform) else "主控面板已經開著，但沒辦法把它叫到最前面")
        return
    try:
        launch(home, sys.executable, popen)  # 在面板外：互通的 run.py 已經確認過這個 Python 跑得動面板（D86）
    except OSError as exc:
        app.log(f"打不開主控面板：{exc}")
        return
    app.log("打開主控面板")
    if platform != "darwin":
        app.log("這個系統還不會把開著的面板叫到最前面")


def run(app):
    """打開主控面板，或叫到最前面。"""
    open_panel(app, app.home)
