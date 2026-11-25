"""「互通」的入口：捷徑與舊的那一小段（`# ── 互通 ──`）叫這裡。確認 Python 跑得動（從 Dock、Spotlight 開的常常是系統內建的
舊 Python），記下它，再交給 iPLoT 的 python3 main.py --run（D163）；找模組、開小視窗、跑都在那邊（角色 run.outside）。

用法：<python> <iPLoT>/modules/互通/run.py <目標> [參數…]
  目標：模組資料夾的路徑、iplot.py 的路徑，或最上層模組的名稱。參數：交給模組的 on_files(app, paths) 的檔案。
結束碼：0 模組跑完沒出錯；1 模組出錯、取消執行、找不到模組、按了停止；2 開不起來（Python、iPLoT 的位置、pywebview）。

這個檔要在 Python 3.8 讀得懂（用錯 Python 的人也要拿到一句話）：只 import 標準庫與 boot。1.0 起不 import 核心（D164）。"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path

import boot

OK, FAILED, CANNOT_START = 0, 1, 2
OUTSIDE = "「互通」要放在 iPLoT 的 modules/ 裡才能用：{path}。把整個「互通」資料夾搬進 iPLoT 的 modules/，再打開一次"
CRASHED = "互通沒做成。細節記在 iPLoT 資料夾的 logs/iplot.log；再打開一次，還是不行就把那個檔交給幫你的人。"
USAGE = "用法：python3 run.py <模組資料夾或名稱> [檔案…]"


def main(argv: list[str], *, home: Path | None = None, folder: Path | None = None, cwd: Path | None = None,
         call=subprocess.call) -> int:
    """確認 Python、記下它，交給 iPLoT 的 python3 main.py --run（它找模組、開小視窗、跑，D163）。回結束碼。"""
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
    if problem is not None:
        boot.alert("互通", problem)
        return CANNOT_START
    boot.remember_python(folder, sys.executable)
    return call([sys.executable, str(home / "main.py"), "--run", *argv], cwd=str(cwd or Path.cwd()))


def entry(argv: list[str]) -> int:
    """__main__ 的入口：main 沒接住的意外不能只是沒反應（從捷徑打開時 stderr 沒人看）：traceback 記進 iPLoT 的
    logs/iplot.log（找得到 iPLoT 的話），跳一個提示框說一句話（體驗 7-02）。"""
    try:
        return main(argv)
    except Exception:  # noqa: BLE001  最外層：什麼意外都只能變成一句話
        import traceback

        text = traceback.format_exc()
        print(text, file=sys.stderr)
        home = boot.iplot_home(os.path.abspath(__file__))
        if home is not None:
            with contextlib.suppress(OSError):
                (home / "logs").mkdir(exist_ok=True)
                with (home / "logs" / "iplot.log").open("a", encoding="utf-8", errors="replace") as f:
                    f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{text}\n")
        boot.alert("互通", CRASHED)
        return CANNOT_START


if __name__ == "__main__":
    code = entry(sys.argv[1:])
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # 模組自己開的非 daemon 執行緒不能讓程序賴著不走
