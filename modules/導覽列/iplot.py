"""導覽列：有頁面的模組，頁面最上面多一排——主控面板、上一層、同一層、下一層，按一格就跳過去。"""
from pathlib import Path

ICON = "🧭"
# iPLoT 0.8 起面板開頁面時問「誰提供頁面上方的那一排（page.top）」（D159）；核心不知道導覽列。
# 「互通」另開的頁面也問同一個，所以兩邊長得一樣（Discussion #9）
PROVIDES = {"page.top": "bar"}
# 用到的模組（D160 R5）：第一格回主控面板
NEEDS = ("主控面板",)
JS = Path(__file__).with_name("nav.js")
PANEL = "主控面板"
T = {
    "hello": "導覽列：打開有頁面的模組（例如行事曆、工作坊），頁面最上面那一排就是這裡畫的。",
    "panel": "主控面板",
    "parent": "↑ {title}",
}


def run(app):
    app.log(T["hello"])


def bar(app, owner):
    """開頁面的模組是 owner：回 {"js": 畫那一排的函式, "cells": 格子, "targets": 每一格跳到的模組}。
    格子依序是主控面板（目標 None：只關掉這一頁）、上一層、同一層的其他模組、下一層。"""
    from core import scan  # 讀資料夾用核心的掃描，看到的跟面板一樣；只讀、不執行任何模組

    roots = scan.roots_from_config(Path(app.home), app.config.roots)
    up = scan.parent_of(owner, roots)
    if up is not None:
        same = scan.find_children(up.folder, owner.root)
    else:
        same = [m for g in scan.find_modules(roots) if g.root == owner.root for m in g.modules]
    same = [m for m in same if m.folder != owner.folder and m.name != PANEL]  # 「主控面板」已經是第一格
    kids = scan.find_children(owner.folder, owner.root)
    found = [("panel", None, T["panel"], "", "")]
    if up is not None:
        found.append(("parent", up, T["parent"].format(title=up.title), "", up.description))
    found += [("sibling", m, m.title, m.icon or "", m.description) for m in same]
    found += [("child", m, m.title, m.icon or "", m.description) for m in kids]
    return {"js": JS.read_text(encoding="utf-8"), "targets": [t for _, t, *_ in found],
            "cells": [{"k": k, "t": t, "i": i, "d": d} for k, _, t, i, d in found]}
