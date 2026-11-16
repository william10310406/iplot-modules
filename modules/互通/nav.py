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


class Nav:
    """一個頁面視窗的導覽列：格子與目標一一對應（主控面板、父層、子模組；沒有的就不列）。"""

    def __init__(self, window, core, log, popen=subprocess.Popen, environ=os.environ) -> None:
        owner = core.running[-1]  # 呼叫 app.page 的模組：最裡面那一個
        up, kids = parent_of(owner, core.roots()), scan.find_children(owner.folder, owner.root)
        tops = [m for m in core.all_modules() if m.name == PANEL]  # 在面板外，all_modules 一律是最上層
        found = [("panel", tops[0], PANEL, "", "")] if len(tops) == 1 and owner.name != PANEL else []
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
                popen([sys.executable, str(RUN), str(target.folder)], env={k: v for k, v in environ.items() if k != ENV},
                      start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL)
            except OSError as exc:
                self.choice = None
                return log(NOT_OPENED.format(title=target.title, reason=plain(exc)))
            window.destroy()  # 新的程序開起來了才關這一頁

        window.expose(_iplot_nav)
        window.events.loaded += lambda: window.evaluate_js(f"({source()})({json.dumps(self.cells)})")
