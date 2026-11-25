"""同步：讓捷徑跟上模組（macOS），把這一次的問題寫下來。不改任何模組檔案（D87）。

只在兩個時機做：run.py 每次跑完、在面板按「互通」。沒有背景程式（D84）。同一時間只有一個在做（.lock）。
同步只寫「互通」自己的資料夾。舊模組要加上那一小段，只能在「互通」的狀態頁按「加上」（iplot.py 的 patch），
只限 iPLoT 的 modules/。這裡另外放兩件狀態頁也用的事：列出所有模組（modules）、為什麼不加（why_not）。"""

import contextlib
import os
import sys
import time
from pathlib import Path

import shortcut
from boot import plain

LOCK, ERRORS = ".lock", ".sync-error"
STALE = 120  # 秒：比這個舊的鎖當作上次沒清掉
# iPLoT 自己要用的隨附模組：不加那一小段（加了會讓它跟隨附的那一份不一樣，0.8 驗收的小問題 3）
BUNDLED = ("作業系統", "更新", "工作坊", "整理", "導覽列", "頁面")


def modules(app) -> list:
    """ROOTS 底下所有模組，一路往下到每一層；每個模組帶著它一路的顯示名稱（給捷徑的「父 › 子」）。回 [(ModuleInfo, 名稱們)]。"""
    found = []

    def walk(info, titles: list[str]) -> None:
        found.append((info, titles))
        for child in app.children_of(info):
            walk(child, [*titles, child.title])

    for info in app.top_modules():
        walk(info, [info.title])
    return found


def levels(app) -> dict:
    """每個根目錄是哪一種：{根目錄的路徑: "here"（modules/）、"parent"（上一層）或 "extra"（ROOTS 另外加的）}。"""
    return {info.root: info.level for info in app.top_modules()}


def is_system(info) -> bool:
    """碰作業系統的模組（宣告 os.* 的，隨附的「作業系統」）：不做捷徑、不算在「能在面板外打開」裡。不看名字（D164）。"""
    return info.level != "child" and any(role.startswith("os.") for role, _ in info.provides)


def why_not(info, levels: dict) -> str | None:
    """這個模組不加那一小段的原因；可以加就回 None（還要再看在不在 modules/ 裡、讀不讀得懂，見 iplot.py 的 candidates）。"""
    if info.file.is_symlink():
        return "是符號連結"
    if _from_workshop(info):
        return "工作坊裝來的"  # 自己或上面任何一層是工作坊裝來的：加了會讓那一個變「已修改」（D77）
    if info.level == "here" and info.name in BUNDLED:
        return "隨附模組"
    if levels.get(info.root) == "extra":
        return "在 ROOTS 另外加的資料夾裡"  # 那一小段在那裡找不到 iPLoT
    return None


def _from_workshop(info) -> bool:
    """模組資料夾往上到根目錄（不含根目錄本身），任何一層有 .origin 就是工作坊裝來的。"""
    folder = info.folder
    while folder != info.root and folder != folder.parent:
        if (folder / ".origin").exists():
            return True
        folder = folder.parent
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


def sync(app, python: str, folder: Path, platform: str = sys.platform, now=time.time) -> list[str]:
    """同步一次（folder 是 modules/互通）：做捷徑、寫 .sync-error。不改任何模組檔案（D87）。
    回這一次的問題，一個一句；有人正在同步就跳過、回空清單。"""
    lock = folder / LOCK
    if not _lock(lock, now):
        return []
    try:
        problems: list[str] = []
        if platform == "darwin":
            wanted = shortcut.names([(titles, info.folder) for info, titles in modules(app) if not is_system(info)])
            problems += shortcut.sync(folder / shortcut.FOLDER, wanted, python, folder / "run.py")
        try:
            if problems:
                _write(folder / ERRORS, "".join(p + "\n" for p in problems))
            else:
                (folder / ERRORS).unlink(missing_ok=True)
        except OSError as exc:
            problems.append(f"紀錄寫不進去：{plain(exc)}")
        return problems
    finally:
        lock.unlink(missing_ok=True)
