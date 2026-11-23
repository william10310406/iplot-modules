"""導覽列（D154）：面板外開的頁面（app.page）也有跟面板裡一樣的一排——主控面板、父層、子模組。
做法跟 ui/nav.py 一樣（載入後注入、_iplot_nav 只收編號、nav.js 一字不差），互通自己一份：互通不 import ui/（D80）。差別有三：
- 跳 = 另開一個程序（run.py <目標>），開成功才關掉這一頁：這個程序做完這一頁就結束了，同一個程序裡接不著下一個。
- 主控面板那一格只在最上層剛好一個「主控面板」、而且這一頁不是它開的時候才有。
- 核心 0.5、0.6 沒有 Core.running 與 scan.parent_of（0.7.0 才有，D152）：track 自己記，parent_of 自己算；有的話用核心的。"""

import json  # noqa: I001  core 在 iPLoT 是第一方、在 iplot-modules 是第三方：兩邊的 isort 要的空行不一樣
import os
import subprocess
import sys
from pathlib import Path

from boot import plain
from core import scan

JS = Path(__file__).with_name("nav.js")
RUN = Path(__file__).with_name("run.py")
PANEL = "主控面板"
PARENT = "↑ {title}"
NO_RUN = "找不到 run.py"
NOT_OPENED = "打不開『{title}』：{reason}。再按一次；還是不行就從 iPLoT 的面板打開它"
GONE = "找不到模組『{title}』，可能已經被移除了"
ENV = "IPLOT_CALENDAR"  # 行事曆自己另開的程序的記號：不留給再開出去的程序


def source() -> str:
    """nav.js 的文字：一個函式，收格子的清單。"""
    return JS.read_text(encoding="utf-8")


def track(core) -> None:
    """核心 0.5、0.6 沒有 Core.running：自己記正在執行的模組。app.run、app.open 最後都走 self.press，包住它就夠。
    有 running 的核心（0.7.0 起）什麼都不改。"""
    if hasattr(core, "running"):
        return
    core.running, inner = [], core.press

    def press(info, *args, **kwargs):
        core.running.append(info)
        try:
            return inner(info, *args, **kwargs)
        finally:
            core.running.pop()

    core.press = press


def parent_of(info, roots):
    """info 的父層模組；沒有就回 None。核心有 scan.parent_of（0.7.0 起）就用它，沒有就用同一個算法（D152）。"""
    if hasattr(scan, "parent_of"):
        return scan.parent_of(info, roots)
    up = info.folder.parent
    if up == info.root or not scan.is_module(up):
        return None
    top = up.parent == info.root
    return scan.module_info(up, info.root, next((r.level for r in roots if top and r.path == info.root), "child"))


def from_provider(core, owner, panel):
    """核心 0.8 起：問提供 page.top 的模組（隨附的「導覽列」，D159），面板裡開的頁面用的也是它，所以兩邊一樣（多了同一層，
    Discussion #9）。它的「主控面板」那一格目標是 None（關掉這一頁），在這裡換成「主控面板」模組；沒有那個模組就不列。
    沒有提供者、或回的東西不對，回 None。"""
    if not hasattr(core, "call"):
        return None
    got = core.call("page.top", owner)
    if not (isinstance(got, dict) and isinstance(got.get("cells"), list) and isinstance(got.get("targets"), list)
            and len(got["cells"]) == len(got["targets"])):
        return None
    found = []
    for cell, target in zip(got["cells"], got["targets"], strict=True):
        target = panel if target is None else target
        if target is not None and isinstance(cell, dict):
            found.append((cell.get("k", ""), target, cell.get("t", ""), cell.get("i", ""), cell.get("d", "")))
    return found


UP_FAILED = "它一開就結束了（原因記在 iPLoT 資料夾的 logs/separate.log）"


def _errlog(home: Path):
    """另開的程序的 stderr 要接到哪裡：logs/separate.log（附加），開不了就丟掉。"""
    try:
        (home / "logs").mkdir(exist_ok=True)
        return open(home / "logs" / "separate.log", "ab")  # noqa: SIM115  交給 Popen 之後就關
    except OSError:
        return subprocess.DEVNULL


def _spawn(popen, argv, home: Path, wait=None, **kw) -> bool:
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


class Nav:
    """一個頁面視窗的導覽列：格子與目標一一對應（主控面板、父層、子模組；沒有的就不列）。"""

    def __init__(self, window, core, log, popen=subprocess.Popen, environ=os.environ) -> None:
        owner = core.running[-1]  # 呼叫 app.page 的模組：最裡面那一個
        tops = [m for m in core.all_modules() if m.name == PANEL]  # 在面板外，all_modules 一律是最上層
        panel = tops[0] if len(tops) == 1 and owner.name != PANEL else None
        found = from_provider(core, owner, panel)
        if found is None:  # 核心 0.7 以前、或沒有「導覽列」模組：自己畫主控面板、父層、子模組
            up, kids = parent_of(owner, core.roots()), scan.find_children(owner.folder, owner.root)
            found = [("panel", panel, PANEL, "", "")] if panel else []
            if up:
                found.append(("parent", up, PARENT.format(title=up.title), "", up.description))
            found += [("child", m, m.title, m.icon or "", m.description) for m in kids]
        self.targets = [target for _, target, *_ in found]
        self.cells = [{"k": k, "t": t, "i": i, "d": d} for k, _, t, i, d in found]
        self.choice = None

        def _iplot_nav(i: int) -> None:
            if self.choice is not None or type(i) is not int or not 0 <= i < len(self.targets):  # 只認編號，不認 True、"1"、1.0
                return
            target = self.targets[i]
            if not scan.is_module(target.folder):
                return log(GONE.format(title=target.title))
            if not RUN.is_file():  # Popen 只在 Python 執行檔本身起不來時才丟 OSError：run.py 不在要先自己看
                return log(NOT_OPENED.format(title=target.title, reason=NO_RUN))
            self.choice = i  # 先記下：連按兩下時，後面那一下進來就看到了
            try:
                up = _spawn(popen, [sys.executable, str(RUN), str(target.folder)], RUN.parents[2],
                            env={k: v for k, v in environ.items() if k != ENV})
            except OSError as exc:
                up, why = False, plain(exc)
            else:
                why = UP_FAILED
            if not up:
                self.choice = None
                return log(NOT_OPENED.format(title=target.title, reason=why))
            window.destroy()  # 新的程序開起來了才關這一頁

        window.expose(_iplot_nav)
        window.events.loaded += lambda: window.evaluate_js(f"({source()})({json.dumps(self.cells)})")
