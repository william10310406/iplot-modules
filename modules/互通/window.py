"""在小視窗裡跑一個模組（角色 run.outside，D163）：python3 main.py --run 找好模組、交過來，這裡開彈出式視窗、
按下它、跑完同步一次捷徑，回結束碼。只用交進來的 app 與 core 的公開方法（D164）。"""

import contextlib
import sys
import time
from pathlib import Path

import boot

OK, FAILED = 0, 1
NO_POPUP = "彈出式視窗開不起來：{reason}。再打開一次；還是不行就從 iPLoT 的面板打開這個模組"


def back_to(core, info):
    """跑完之後的回去鈕：提供 home 的模組（行事曆，D93），沒有就是面板（提供 main 的，D88）；剛好一個、而且不是跑的那一個
    才給，否則 None。不看名字（D164）。"""
    for role in ("home", "main"):
        found = core.providers(role)
        if len(found) == 1 and (info is None or found[0].folder != info.folder):
            return found[0]
    return None


def popup_for(core, home: Path, webview=None):
    """彈出式視窗，接上 core（它之後要說的話都進這個視窗）。webview 是 None 就用 lib/ 裡的 pywebview；
    沒有就丟 ImportError，main.py 改在終端機跑。"""
    import popup as popup_module

    real = webview is None
    if real:
        try:
            import webview  # lib/ 裡的 pywebview
        except ImportError:
            raise  # 沒有它也能跑：main.py 接到 ImportError 就改在終端機跑（D163）
    dock = popup_module.mac_dock if real and sys.platform == "darwin" else None
    popup = popup_module.Popup(home, webview, dock=dock)
    core.view = popup
    popup.attach(core)
    return popup


def outside(app, core, folder: Path, info, files, problem, config_error, webview=None) -> int:
    """在小視窗裡跑 info，跑完同步一次捷徑，回結束碼。"""
    import sync

    popup = popup_for(core, Path(app.home), webview)
    popup.title = info.title if info is not None else "互通"
    with contextlib.suppress(Exception):  # Dock 上寫模組的名字，不是「Python」（D166）；要在開視窗之前，做不到也照開
        core.call_here("os.app_name", popup.title)
    back = back_to(core, info)

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
            elif result.error is None or result.error.kind == "InputCancelled":  # 第一次問的時候、或模組的提問框按了取消
                outcome = "cancelled"
        popup.done(outcome, time.perf_counter() - start, back=back)
        with contextlib.suppress(Exception):  # 同步出錯不能讓模組的結果變成錯的；它自己的問題寫在 .sync-error
            sync.sync(app, boot.recorded_python(folder) or sys.executable, folder)
        return code

    try:
        return popup.run(job)
    except popup.webview.WebViewException as exc:
        boot.alert("互通", NO_POPUP.format(reason=exc))
        return 2
