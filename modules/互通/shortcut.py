"""捷徑：每個模組一個 macOS 的 .app，放在 modules/互通/捷徑/（Spotlight 搜得到，整個資料夾拖到 Dock 就是一排按鈕）。

.app 裡的指令稿交給記下的 Python 的 Python.app 開 run.py（D86）：macOS 的隱私權保護（TCC）就算在 Python 頭上，
iPLoT 放在「文件」「桌面」「下載項目」裡時，所有捷徑共用一次允許。沒有 Python.app 的 Python 才直接執行。
Info.plist 用 plistlib 寫；指令稿裡的路徑都經過 shlex.quote；只管 Info.plist 裡有 IPLoTInterop 的捷徑。"""

import contextlib
import hashlib
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import unicodedata
from pathlib import Path

from boot import python_app

FOLDER = "捷徑"
MAX_NAME_BYTES = 200  # 檔名上限是 255 bytes；留給「.app」與做的時候的「.tmp-」
EXECUTABLE = "iplot-run"
KEYS = ("IPLoTModule", "IPLoTPython", "IPLoTApp", "IPLoTRun", "IPLoTIcon")  # 任何一個跟現在的不一樣就重做
GONE = "這個捷徑找不到記下的 Python 或 iPLoT。在面板按一次「互通」，捷徑會重新整理。"
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _clean(titles: list[str]) -> str:
    """一路的顯示名稱接成「父 › 子」；/ 與 : 換成全形，控制字元拿掉，開頭的 . 拿掉。"""
    name = CONTROL.sub("", " › ".join(titles)).replace("/", "／").replace(":", "：").lstrip(".").strip()
    return name or "模組"


def _fit(name: str, suffix: str = "") -> str:
    """name＋suffix 的 UTF-8 不超過 MAX_NAME_BYTES；太長就把 name 截短、結尾加「…」。"""
    if len((name + suffix).encode()) <= MAX_NAME_BYTES:
        return name + suffix
    room = MAX_NAME_BYTES - len(("…" + suffix).encode())
    cut = name.encode()[:room].decode("utf-8", "ignore")
    return cut + "…" + suffix


def bundle_name(titles: list[str]) -> str:
    """捷徑的名稱（不含 .app）。"""
    return _fit(_clean(titles))


def names(entries: list[tuple[list[str], Path]]) -> dict[str, Path]:
    """名稱 → 模組資料夾。重名（截短之後、不分大小寫，APFS 就是這樣比的）依列出的順序加「 2」「 3」。"""
    result: dict[str, Path] = {}
    taken: set[str] = set()
    for titles, folder in entries:
        full, n = _clean(titles), 1
        name = _fit(full)
        while _key(name) in taken:
            n += 1
            name = _fit(full, f" {n}")
        taken.add(_key(name))
        result[name] = folder
    return result


def _key(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def script(python: str, run: Path, module: Path, name: str) -> str:
    """捷徑的指令稿。記下的 Python 或 run.py 不在了（換了 Python、iPLoT 搬了家、刪了互通）就跳提示框說怎麼辦。"""
    q, app = shlex.quote, python_app(python)
    lines = ["#!/bin/sh",
             f"# 「互通」做的捷徑：用跟面板同一個 Python 打開「{CONTROL.sub('', name)}」",
             f"py={q(python)}", f"run={q(str(run))}"]
    missing = '[ ! -x "$py" ] || [ ! -f "$run" ]'
    if app is not None:
        lines.append(f"app={q(str(app))}")
        missing += ' || [ ! -d "$app" ]'
    lines += [f"if {missing}; then",
              "  exec /usr/bin/osascript -e 'on run argv' "
              "-e 'display alert (item 1 of argv) message (item 2 of argv) as critical' -e 'end run' "
              f"{q('互通')} {q(GONE)}",
              "fi"]
    if app is not None:
        lines.append(f'exec /usr/bin/open -n -a "$app" --args "$run" {q(str(module))}')
    else:
        lines.append(f'exec "$py" "$run" {q(str(module))}')
    return "\n".join(lines) + "\n"


def _now(module: Path, python: str, run: Path) -> dict:
    """捷徑寫進 Info.plist、同步時拿來比的值。IPLoTApp 是 Python.app 的路徑：Homebrew 的 Python 升小版本時，
    python 的路徑不變、Python.app 卻搬到新的資料夾，指令稿要跟著重做。"""
    app = python_app(python)
    return {"IPLoTModule": str(module), "IPLoTPython": python, "IPLoTApp": "" if app is None else str(app),
            "IPLoTRun": str(run), "IPLoTIcon": _icon_stamp(module)}


def _icon_stamp(module: Path) -> str:
    try:
        return str((module / "icon.png").stat().st_mtime_ns)
    except OSError:
        return ""


def write(base: Path, name: str, module: Path, python: str, run: Path, sips=subprocess.call) -> Path:
    """做一個捷徑：先寫到 base/.tmp-<name>.app，做好才換成 base/<name>.app。模組有 icon.png 才轉圖示，轉不出來就當作沒有。"""
    tmp, final = base / f".tmp-{name}.app", base / f"{name}.app"
    if final.exists() and read(final) is None:  # 不是互通做的（APFS 不分大小寫，同名的寫法不同也算）：不碰
        raise FileExistsError(f"那裡已經有一個不是「互通」做的 {final.name}，沒有動它")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "Contents" / "MacOS").mkdir(parents=True)
    info = {"CFBundleName": name, "CFBundleDisplayName": name, "CFBundleExecutable": EXECUTABLE,
            "CFBundleIdentifier": "local.iplot.interop." + hashlib.sha1(str(module).encode()).hexdigest()[:12],
            "CFBundlePackageType": "APPL", "CFBundleVersion": "1", "IPLoTInterop": 1, **_now(module, python, run)}
    if info["IPLoTIcon"]:
        icns = tmp / "Contents" / "Resources" / "icon.icns"
        icns.parent.mkdir()
        with contextlib.suppress(OSError):
            sips(["sips", "-s", "format", "icns", str(module / "icon.png"), "--out", str(icns)])
        if icns.is_file():
            info["CFBundleIconFile"] = "icon"
    (tmp / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
    exe = tmp / "Contents" / "MacOS" / EXECUTABLE
    exe.write_text(script(python, run, module, name), encoding="utf-8")
    os.chmod(exe, 0o755)
    if final.exists():
        shutil.rmtree(final)
    os.replace(tmp, final)
    return final


def read(bundle: Path) -> dict | None:
    """捷徑的 Info.plist；不是「互通」做的（沒有 IPLoTInterop）或讀不到就回 None。"""
    try:
        info = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    return info if isinstance(info, dict) and "IPLoTInterop" in info else None


def sync(base: Path, wanted: dict[str, Path], python: str, run: Path, sips=subprocess.call) -> list[str]:
    """讓 base 裡「互通」做的捷徑剛好是 wanted：多的拿掉、少的做、指向或內容過期的重做；別的東西一律不碰。
    回這一次的問題，一個一句。"""
    problems: list[str] = []
    base.mkdir(parents=True, exist_ok=True)
    have: dict[str, dict] = {}
    for p in base.iterdir():
        if p.name.startswith(".tmp-") and p.suffix == ".app":  # 上一次做到一半留下的
            shutil.rmtree(p, ignore_errors=True)
        elif p.suffix == ".app" and (info := read(p)) is not None:
            have[p.name[:-4]] = info
    for name in have.keys() - wanted.keys():
        try:
            shutil.rmtree(base / f"{name}.app")
        except OSError as exc:
            problems.append(f"捷徑「{name}」：拿不掉：{exc}")
    for name, module in wanted.items():
        now = _now(module, python, run)
        if name in have and all(have[name].get(k) == now[k] for k in KEYS):
            continue
        try:
            write(base, name, module, python, run, sips)
        except OSError as exc:
            problems.append(f"捷徑「{name}」：做不出來：{exc}")
    return problems
