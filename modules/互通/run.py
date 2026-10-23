"""「互通」的入口：在面板外跑一個模組，跟在面板裡一樣拿得到 app；對話框與輸出用彈出式視窗（D81）。

用法：<python> <iPLoT>/modules/互通/run.py <目標> [參數…]
  目標：模組資料夾的路徑、iplot.py 的路徑，或最上層模組的名稱。
  參數：當作檔案路徑（以呼叫時的工作目錄為準），交給模組的 on_files(app, paths)；沒有就執行 run(app)。
結束碼：0 模組跑完沒出錯；1 模組出錯、取消執行、找不到模組、按了停止；2 開不起來（Python、iPLoT 的位置、核心版本、pywebview）。

捷徑、模組檔頭的那一小段（D84）、一行指令，最後都進到這裡。這個檔要在 Python 3.8 讀得懂（用錯 Python 的人也要拿到一句話）：
檔頭只 import 標準庫與 boot；core、popup、sync 在確認過 Python 之後才 import。"""

from __future__ import annotations

import contextlib
import os
import sys
import time
import unicodedata
from pathlib import Path

import boot

OK, FAILED, CANNOT_START = 0, 1, 2
NOT_A_MODULE = "不是模組：{path}（資料夾裡沒有 iplot.py）"
GONE = "找不到這個模組：{path}。它可能被改名或刪掉了；捷徑已經重新整理。"
NO_TK = ("在面板外跑的模組不能開 tkinter 視窗（彈出式視窗用的是 pywebview）；"
         "要用 tkinter，請從面板的安全模式執行：python3 main.py --safe")
OUTSIDE = "「互通」要放在 iPLoT 的 modules/ 裡才能用：{path}"
NO_POPUP = "彈出式視窗開不起來：{reason}"
USAGE = "用法：python3 run.py <模組資料夾或名稱> [檔案…]"
OURS = ("boot", "popup", "sync", "snippet", "shortcut")  # 這個資料夾自己的檔：用完就從 sys.modules 拿掉


class NoTk:
    """擋住 import tkinter，跟 main.py 的 NoTk 同一個理由：主執行緒被 pywebview 佔著，模組在別的執行緒開 tkinter 視窗，
    整個程序會被作業系統中止，連一句錯誤都來不及說。擋在 import 這一步，它就只是一個一般的模組錯誤。"""

    def find_spec(self, name, path=None, target=None):
        if name in ("tkinter", "_tkinter"):
            raise ImportError(NO_TK)


def _expand(text: str) -> Path:
    """~ 換成家目錄；「~打錯的名字/…」找不到那個使用者時 pathlib 丟 RuntimeError，那就照字面。"""
    try:
        return Path(text).expanduser()
    except RuntimeError:
        return Path(text)


def resolve(core, target: str, cwd: Path):
    """目標 → (ModuleInfo, None)，或 (None, 說明為什麼的那一句)。名稱只找最上層（D83）。"""
    from core import scan
    from core.text import T

    path = _expand(target)
    path = path if path.is_absolute() else cwd / path
    if path.exists():
        folder = path.parent if path.is_file() and path.name == scan.MARKER else path
        if not scan.is_module(folder):
            return None, NOT_A_MODULE.format(path=folder)
        folder = folder.resolve()
        for root in core.roots():  # 第一個包含它的根目錄；直接在根目錄底下是那一組，再下去是 child
            try:
                depth = len(folder.relative_to(root.path).parts)
            except ValueError:
                continue
            return scan.module_info(folder, root.path, root.level if depth == 1 else "child"), None
        return scan.module_info(folder, folder.parent, "extra"), None
    if "/" in target or target.startswith("~"):
        return None, GONE.format(path=target)
    name = unicodedata.normalize("NFC", target)
    found = [m for m in core.all_modules() if m.name == name]
    if len(found) == 1:
        return found[0], None
    paths = "\n".join(str(m.folder) for m in found)
    return None, T["ambiguous" if found else "not_found"].format(name=name, paths=paths)


def back_button(core, info, candidates):
    """跑完之後的回去鈕跑哪個模組：依序找（行事曆、主控面板），最上層剛好一個、而且跑的不是它自己，就是它（D93、D88）；
    都不是回 None（不給）。"""
    names = [m.name for m in core.all_modules()]
    for name in candidates:
        if info is not None and info.name != name and names.count(name) == 1:
            return name
    return None


def main(argv: list[str], *, home: Path | None = None, folder: Path | None = None, webview=None,
         cwd: Path | None = None) -> int:
    """跑一次：確認 Python、核對核心版本、記下 Python，開小視窗跑模組，跑完同步一次。回結束碼。"""
    here = os.path.abspath(__file__)
    folder = folder or Path(here).parent
    if not argv:
        print(USAGE, file=sys.stderr)
        return FAILED
    home = home or boot.iplot_home(here)
    if home is None:
        boot.alert("互通", OUTSIDE.format(path=folder))
        return CANNOT_START
    problem = boot.ensure_python(home, folder, here, argv)
    if problem is None:
        import core
        from core.app import App

        problem = boot.check_version(core.__version__, App.api_version, boot.own_version(folder))
    if problem is not None:
        boot.alert("互通", problem)
        return CANNOT_START
    boot.remember_python(folder, sys.executable)
    return _run(argv, home, folder, webview, cwd or Path.cwd())


def _run(argv: list[str], home: Path, folder: Path, webview, cwd: Path) -> int:
    import popup as popup_module
    import sync

    from core.core import Core, load_config

    for name in OURS:  # 模組自己有同名的 helper（例如 sync.py）時，import 得到的是它自己的
        sys.modules.pop(name, None)
    real = webview is None
    if real:
        import webview  # lib/ 裡的 pywebview（boot.ensure_python 已經確認載得進來）
    config, config_error = load_config(home / "config.py")
    dock = popup_module.mac_dock if real and sys.platform == "darwin" else None
    popup = popup_module.Popup(home, webview, dock=dock)
    core = Core(home, config, popup)
    popup.attach(core)
    core.rescan()  # 在面板外一律是最上層
    info, problem = resolve(core, argv[0], cwd)
    popup.title = info.title if info is not None else "互通"
    back = back_button(core, info, (popup_module.CALENDAR, popup_module.PANEL))
    files = [cwd / _expand(a) for a in argv[1:]]

    def job() -> int:
        if config_error is not None:
            popup.report(config_error)
        start, outcome, code = time.perf_counter(), "error", FAILED
        if problem is not None:
            popup.log(problem)
        else:
            # quiet：核心的「完成（x 秒）」那一行不送；小視窗自己決定要不要顯示完成
            result = (core.press(info, "on_files", (files,), quiet=True) if files
                      else core.press(info, quiet=True))
            if result.ok:
                outcome, code = "ok", OK
            elif result.error is None:  # 工作坊裝來的模組，第一次問的時候按了取消
                outcome = "cancelled"
        popup.done(outcome, time.perf_counter() - start, back=back)
        with contextlib.suppress(Exception):  # 同步出錯不能讓模組的結果變成錯的；它自己的問題寫在 .sync-error
            sync.sync(home, config, boot.recorded_python(folder) or sys.executable, folder)
        return code

    guard = NoTk()
    sys.meta_path.insert(0, guard)
    try:
        return popup.run(job)
    except webview.WebViewException as exc:
        boot.alert("互通", NO_POPUP.format(reason=exc))
        return CANNOT_START
    finally:
        sys.meta_path.remove(guard)


if __name__ == "__main__":
    code = main(sys.argv[1:])
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # 模組自己開的非 daemon 執行緒不能讓程序賴著不走
