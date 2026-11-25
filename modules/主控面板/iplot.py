"""主控面板：打開 iPLoT 的面板；已經開著就叫到最前面。任何模組寫 app.run("主控面板") 就會用到這裡。
面板本身也在這個資料夾（panel_web.py 與頁面的三個檔）：iPLoT 開起來時，開機程式在主程序裡執行這裡的 start（D162）。"""
import contextlib
import errno
import os
import pathlib
import re
import subprocess

# ── iPLoT ── 直接執行這個檔（python3 iplot.py）時交給 iPLoT 跑（python3 main.py --run）；從 iPLoT 裡執行時這段不做事。不要可以整段刪掉
import sys

if __name__ == "__main__" and "core.runner" not in sys.modules:
    import os
    import subprocess
    here = folder = os.path.dirname(os.path.abspath(__file__))
    main = None
    while main is None and folder != os.path.dirname(folder):  # 往上一層層找 iPLoT：模組在它裡面或旁邊都找得到
        folder = os.path.dirname(folder)
        try:
            names = [""] + sorted(os.listdir(folder))
        except OSError:
            names = [""]
        mains = (os.path.join(folder, n, "main.py") for n in names)
        main = next((m for m in mains if os.path.isfile(m) and os.path.isdir(os.path.join(os.path.dirname(m), "core"))), None)
    if main and not os.environ.get("IPLOT_DIRECT"):  # IPLOT_DIRECT=1：不交出去，照一般腳本跑（例如在編輯器裡除錯）
        sys.exit(subprocess.call([sys.executable, main, "--run", here, *sys.argv[1:]]))
    if not main:
        print("找不到 iPLoT（模組要放在 iPLoT 資料夾裡或它旁邊），照一般的 python3 iplot.py 跑", file=sys.stderr)
# ── iPLoT ──

ICON = "🎛️"
PROVIDES = {"main": "start"}  # 開機程式要的面板（D162）
# 工作坊裝來的模組要提供這些角色時，「要允許嗎？」用這些名字說（D166）
ROLE_NAMES = {"main": "iPLoT 的主畫面", "menu.module": "右鍵選單裡的項目", "panel.error": "面板上的錯誤要不要回報"}
NEEDS = ("menu.module", "panel.error", "os.activate", "os.app_name")  # 右鍵選單多的項目、錯誤那一列的「回報這個問題」、叫面板到最前面
MIN_API = 7  # app.panel（D164）
REASONS = {errno.ENOENT: "找不到 Python 或 iPLoT 的 main.py", errno.EACCES: "沒有權限", errno.EPERM: "沒有權限",
           errno.ENOMEM: "記憶體不夠", errno.EAGAIN: "系統現在開不了新的程式"}


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


UP_FAILED = "它一開就結束了（原因記在 iPLoT 資料夾的 logs/separate.log）"


def _errlog(home: pathlib.Path):
    """另開的程序的 stderr 要接到哪裡：logs/separate.log（附加），開不了就丟掉。"""
    try:
        (home / "logs").mkdir(exist_ok=True)
        return open(home / "logs" / "separate.log", "ab")  # noqa: SIM115  交給 Popen 之後就關
    except OSError:
        return subprocess.DEVNULL


def _spawn(popen, argv, home: pathlib.Path, wait=None, **kw) -> bool:
    """另開一個程序，等 wait 秒（環境變數 IPLOT_START_WAIT，預設 1）：這段時間裡出錯結束了（匯入就失敗、Python 起不來）
    回 False，丟出去就當成功的做法不再用（D160 第 3 條）。stderr 接到 logs/separate.log，原因才留得下來。
    Popen 本身失敗照樣丟 OSError。抄本：行事曆、主控面板、互通的 nav.py 各一份，要一樣（tools/copies.json）。"""
    import time
    err = _errlog(home)
    try:
        proc = popen(argv, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err, **kw)
    finally:
        if err is not subprocess.DEVNULL:
            err.close()
    deadline = time.monotonic() + (float(os.environ.get("IPLOT_START_WAIT", "1")) if wait is None else wait)
    while time.monotonic() < deadline:
        code = proc.poll()
        if code is not None:
            return code == 0
        time.sleep(0.05)
    return True


def launch(home: pathlib.Path, python: str, popen=subprocess.Popen) -> bool:
    """開一個新的面板：跟這個程序分開（關掉這個模組的小視窗不會連帶關掉面板）。一開就結束了回 False。"""
    return _spawn(popen, [python, str(home / "main.py")], home, cwd=str(home))


def open_panel(app, home: pathlib.Path, *, ps=_ps, lsof=_lsof, popen=subprocess.Popen, platform: str | None = None,
               me: int | None = None) -> None:
    """三種情況：面板開的（app.panel 有值）：面板就是開這個程序的那一個，本來就在最前面，說一句；
    不是面板開的（python3 main.py --run）、面板開著：請作業系統的 os.activate 叫它到最前面；面板沒開：開一個。"""
    platform = platform or sys.platform
    if app.panel is not None:
        app.log("主控面板已經開著")
        return
    pid = find_panel(home, ps, lsof, me) if platform == "darwin" else None
    if pid is not None:
        app.log("主控面板已經開著，叫到最前面了" if app.call("os.activate", pid) else "主控面板已經開著，但沒辦法把它叫到最前面。到 Dock 點一下 Python 的圖示")
        return
    try:
        up = launch(home, sys.executable, popen)
    except OSError as exc:
        app.log(f"打不開主控面板：{REASONS.get(exc.errno, '系統不讓打開')}。確認 iPLoT 資料夾還在，再雙擊一次")  # 原因是中文（體驗 7-08）
        return
    app.log("打開主控面板" if up else f"打不開主控面板：{UP_FAILED}。再雙擊一次")
    if platform != "darwin":
        app.log("這個系統還不會把開著的面板叫到最前面")


def start(app, core, note=None, err=None, *, execv=os.execv):
    """開機程式交來 app 與核心（指令集）：開網頁面板，視窗關掉才回來（D162）。note 是要先寫進訊息區的話，
    err 是 config.py 的錯誤。lib/ 裡沒有 pywebview、或它找不到能用的視窗套件時丟 ImportError，開機程式會去裝、或退到後備面板。"""
    from panel_web import WebPanel  # 這個資料夾的檔：開機程式把資料夾放在 sys.path 最前面

    with contextlib.suppress(Exception):  # Dock 上寫「iPLoT」，不是「Python」（D166）；要在開視窗之前，做不到也照開
        core.call_here("os.app_name", "iPLoT")
    panel = WebPanel(app.home, app.version, False)
    core.view = panel
    panel.attach(core)
    if note is not None:
        panel.submit(lambda: panel.log(note))  # 頁面就緒之後才送得出去，先排著
    if err is not None:
        panel.submit(lambda: panel.report(err))
    try:
        panel.run()
    except panel.webview.WebViewException as exc:
        raise ImportError(str(exc)) from exc
    if panel.restarting:  # 按了「重新啟動」（app.restart，D166）：整個 iPLoT 從頭再來，啟動參數照舊
        os.chdir(app.home)
        execv(sys.executable, [sys.executable, str(pathlib.Path(app.home) / "main.py"), *sys.argv[1:]])


def run(app):
    """打開主控面板，或叫到最前面。"""
    open_panel(app, app.home)
