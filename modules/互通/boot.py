"""「互通」的開場：找 iPLoT、確認 Python 對不對、提示框（D86）。1.0 起不看核心的版本（互通 1.0 只跟 iPLoT 1.0 一起來，
從工作坊裝到舊版上時，工作坊與面板會說「請先更新」），也不 import 核心（D164）。

run.py 一開始就用這個檔，那時候跑的可能是系統內建的舊 Python（從 Spotlight、Dock 開的程式拿不到終端機的 PATH），
所以這個檔只用 Python 3.8 就有的語法、只 import 標準庫（跟 main.py 的 D46 同一個理由）。"""

from __future__ import annotations

import contextlib
import errno
import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

REEXEC = "IPLOT_INTEROP_REEXEC"  # 換過一次 Python 的記號：換過還不行就說一句，不再換
RECORD = ".python"
OLD = "互通需要 Python 3.10 以上，這個是 {version}。先在面板按一次「互通」，讓它記下面板用的 Python。"
NO_LIB = ("這個 Python（{exe}）載不進 iPLoT 的介面套件：{reason}（lib/ 可能是給別的 Python 裝的）。"
          "先在面板按一次「互通」，讓它記下面板用的 Python。")
STILL = "換成記下的 Python（{exe}）還是開不起來：{reason}。在面板按一次「互通」重新記下。"
ALERT = ["osascript", "-e", "on run argv",
         "-e", "display alert (item 1 of argv) message (item 2 of argv) as critical", "-e", "end run"]


REASONS = {errno.ENOSPC: "磁碟滿了", errno.EACCES: "沒有權限", errno.EPERM: "沒有權限", errno.EROFS: "資料夾是唯讀的",
           errno.ENOENT: "找不到檔案或資料夾", errno.ENOTDIR: "路徑上有一段不是資料夾", errno.ENAMETOOLONG: "名稱太長"}


def plain(exc: BaseException) -> str:
    """寫檔、改檔、做捷徑失敗的原因：一句中文，不貼系統的英文原文（Permission denied、codec can't decode…）（體驗 7-01）。
    互通不 import 核心，所以這裡自己帶一份（跟核心的 core.errors.reason 說法一樣）。"""
    if isinstance(exc, UnicodeError):
        return "檔案不是 UTF-8 的文字"
    if isinstance(exc, OSError):
        return REASONS.get(exc.errno, "系統不讓寫入或打開")
    return "內容讀不懂"


def iplot_home(run_file: str) -> Path | None:
    """run.py 往上兩層（modules/互通/run.py → iPLoT）；那裡有 main.py 與 modules/ 才是 iPLoT。"""
    home = Path(os.path.abspath(run_file)).parent.parent.parent
    if (home / "main.py").is_file() and (home / "modules").is_dir():
        return home
    return None


def alert(title: str, message: str, platform: str = sys.platform, call=subprocess.call) -> None:
    """還沒有小視窗可用時的唯一出口：一律寫 stderr；macOS 再跳提示框。字只當參數傳，絕不拼進 AppleScript。"""
    print(message, file=sys.stderr, flush=True)
    if platform == "darwin":
        with contextlib.suppress(OSError):
            call([*ALERT, title, message])


def python_app(exe: str) -> Path | None:
    """exe 這個 Python 的 Python.app（python.org 與 Homebrew 的 framework 版才有）；沒有就回 None。
    捷徑交給它開，macOS 的隱私權保護（TCC）就算在 Python 頭上，所有捷徑共用一次允許（D86）。"""
    path = Path(os.path.realpath(exe))
    for i, part in enumerate(path.parts):
        if part.endswith(".app") and path.parts[i + 1:i + 3] == ("Contents", "MacOS"):
            return Path(*path.parts[:i + 1])
    app = path.parent.parent / "Resources" / "Python.app"
    return app if (app / "Contents" / "MacOS").is_dir() else None


def same_python(a: str, b: str) -> bool:
    """同一個 Python：同一個檔，或同一個 Python.app（bin/python3 與 Python.app 裡的執行檔是同一個）。"""
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    app = python_app(a)
    return app is not None and app == python_app(b)


def recorded_python(folder: Path) -> str | None:
    """modules/互通/.python 記的 Python；沒有就回 None。"""
    try:
        return (folder / RECORD).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def remember_python(folder: Path, exe: str) -> None:
    """記下跑得動的 Python。跟記著的是同一個就不寫；寫的時候先寫暫存檔再換上去，不會寫到一半。"""
    old = recorded_python(folder)
    if old is not None and same_python(old, exe):
        return
    tmp = folder / f"{RECORD}.{os.getpid()}.tmp"
    tmp.write_text(exe, encoding="utf-8")
    os.replace(tmp, folder / RECORD)


def own_version(folder: Path) -> str:
    """「互通」自己的版本：CHANGELOG.md 最上面那一節的版本號；讀不到回 "?"。"""
    try:
        text = (folder / "CHANGELOG.md").read_text(encoding="utf-8-sig")
    except (OSError, ValueError):
        return "?"
    found = re.search(r"^## \[(\d+(?:\.\d+)*)\]", text, re.M)
    return found.group(1) if found else "?"


def ensure_python(home: Path, folder: Path, run_file: str, argv: list[str], *, version=sys.version_info,
                  importer=importlib.import_module, environ=os.environ, execv=os.execv,
                  exe: str = sys.executable) -> str | None:
    """確認這個 Python 跑得動 iPLoT：3.10 以上，而且載得進 lib/ 的 pywebview（小視窗要用）。
    跑不動時，有記下的、存在的、不是這一個的 Python，又還沒換過，就換成它重跑一次（os.execv 不回來）；
    否則回第 8 節那一句。跑得動回 None。sys.path 最前面放 iPLoT、再來 lib/（跟 main.py 一樣）。"""
    sys.path[:0] = [str(home), str(home / "lib")]
    reason = None
    if tuple(version[:2]) < (3, 10):
        reason = "這個是 Python {}，要 3.10 以上".format(".".join(str(v) for v in version[:3]))
    else:
        try:
            importer("webview")
        except Exception as exc:  # noqa: BLE001  lib/ 的編譯檔是給別的 Python 的：什麼錯都有可能
            reason = str(exc) or type(exc).__name__
    if reason is None:
        environ.pop(REEXEC, None)
        return None
    rec = recorded_python(folder)
    usable = rec is not None and os.path.isfile(rec) and not same_python(rec, exe)
    if usable and REEXEC not in environ:
        environ[REEXEC] = "1"
        try:
            execv(rec, [rec, run_file, *argv])
        except OSError as exc:
            return STILL.format(exe=rec, reason=exc)
        return None
    if REEXEC in environ and rec is not None:
        return STILL.format(exe=rec, reason=reason)
    if tuple(version[:2]) < (3, 10):
        return OLD.format(version=".".join(str(v) for v in version[:3]))
    return NO_LIB.format(exe=exe, reason=reason)
