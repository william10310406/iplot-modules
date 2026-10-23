"""同步：讓捷徑跟上模組（macOS），把這一次的問題寫下來。不改任何模組檔案（D87）。

只在兩個時機做：run.py 每次跑完、在面板按「互通」。沒有背景程式（D84）。同一時間只有一個在做（.lock）。
同步只寫「互通」自己的資料夾。舊模組要加上那一小段，只能在「互通」的狀態頁按「加上」（iplot.py 的 patch），
只限 iPLoT 的 modules/。這裡另外放兩件狀態頁也用的事：列出所有模組（modules）、為什麼不加（why_not）。"""

import ast
import contextlib
import os
import sys
import time
from pathlib import Path

import shortcut

from core import scan
from core.text import SYSTEM_MODULE
from core.types import Config, ModuleInfo, Root

LOCK, ERRORS = ".lock", ".sync-error"
STALE = 120  # 秒：比這個舊的鎖當作上次沒清掉
BUNDLED = ("作業系統", "更新", "工作坊")  # iPLoT 自己要用的三個隨附模組，不加那一小段
TK = ("tkinter", "_tkinter", "turtle")  # 在面板外開不了它們的視窗（run.py 擋著）


def modules(home: Path, config: Config) -> list[tuple[ModuleInfo, list[str]]]:
    """ROOTS 底下所有模組，一路往下到每一層；每個模組帶著它一路的顯示名稱（給捷徑的「父 › 子」）。"""
    found: list[tuple[ModuleInfo, list[str]]] = []

    def walk(info: ModuleInfo, titles: list[str]) -> None:
        found.append((info, titles))
        for child in scan.find_children(info.folder, info.root):
            walk(child, [*titles, child.title])

    for group in scan.find_modules(scan.roots_from_config(home, config.roots)):
        for info in group.modules:
            walk(info, [info.title])
    return found


def why_not(info: ModuleInfo, roots: list[Root]) -> str | None:
    """這個模組不加那一小段的原因；可以加就回 None（還要再看在不在 modules/ 裡、讀不讀得懂，見 iplot.py 的 candidates）。"""
    if info.file.is_symlink():
        return "是符號連結"
    if (info.folder / ".origin").exists():
        return "工作坊裝來的"  # 加了會變「已修改」（D77）
    if info.level == "here" and info.name in BUNDLED:
        return "隨附模組"
    if any(r.level == "extra" and r.path == info.root for r in roots):
        return "在 ROOTS 另外加的資料夾裡"  # 那一小段在那裡找不到 iPLoT
    if _uses_tk(info.file):
        return "用了 tkinter 或 turtle"  # 加了之後直接執行會交給 run.py，而 run.py 開不了 tkinter 的視窗
    return None


def _uses_tk(file: Path) -> bool:
    """iplot.py 裡有沒有 import tkinter／turtle（任何一層、任何寫法）；讀不懂就當作沒有（讀不懂的另外不列成候選）。"""
    try:
        tree = ast.parse(file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, SyntaxError):
        return False
    for node in ast.walk(tree):
        names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                 else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
        if any(n.split(".")[0] in TK for n in names):
            return True
    return False


def _lock(path: Path, now) -> bool:
    """拿鎖；別人拿著而且不到 STALE 秒就回 False。"""
    for _ in range(2):
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            with contextlib.suppress(OSError):
                if now() - path.stat().st_mtime <= STALE:
                    return False
                path.unlink()
    return False


def _write(path: Path, text: str) -> None:
    """先寫暫存檔再換上去：紀錄永遠不會只寫到一半。"""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def sync(home: Path, config: Config, python: str, folder: Path, platform: str = sys.platform,
         now=time.time) -> list[str]:
    """同步一次（folder 是 modules/互通）：做捷徑、寫 .sync-error。不改任何模組檔案（D87）。
    回這一次的問題，一個一句；有人正在同步就跳過、回空清單。"""
    lock = folder / LOCK
    if not _lock(lock, now):
        return []
    try:
        problems: list[str] = []
        if platform == "darwin":
            wanted = shortcut.names([(titles, info.folder) for info, titles in modules(home, config)
                                     if not (info.level == "here" and info.name == SYSTEM_MODULE)])
            problems += shortcut.sync(folder / shortcut.FOLDER, wanted, python, folder / "run.py")
        try:
            if problems:
                _write(folder / ERRORS, "".join(p + "\n" for p in problems))
            else:
                (folder / ERRORS).unlink(missing_ok=True)
        except OSError as exc:
            problems.append(f"紀錄寫不進去：{exc}")
        return problems
    finally:
        lock.unlink(missing_ok=True)
