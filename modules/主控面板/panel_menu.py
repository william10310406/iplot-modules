"""右鍵選單上模組提供的項目（D159）：問每個提供 menu.module 的模組，它回（顯示的字, 函式名）的清單。
抄自 ui/menu.py（後備的 tkinter 面板用那一份；tools/copies.json 登記）。「menu.module」這個名字只有面板和提供它的模組知道，核心不知道。"""

from typing import Any

Core = ModuleInfo = Any  # 核心交來的物件：這裡只呼叫 each、讀欄位，不 import 核心

ROLE = "menu.module"


def items(core: Core, info: ModuleInfo) -> tuple[list[tuple[ModuleInfo, str, tuple]], list[str]]:
    """回（[(提供的模組, 函式名, (info,)), …], [顯示的字, …]），兩份一一對應；按第 i 項就是 core.press(*第一份[i])。
    回傳的不是字串對的清單就略過那一項，不讓一個寫錯的模組弄壞選單。"""
    picks, labels = [], []
    for provider, value in core.each(ROLE, info):
        for item in value if isinstance(value, list | tuple) else ():
            if isinstance(item, list | tuple) and len(item) == 2 and all(isinstance(x, str) for x in item):
                picks.append((provider, item[1], (info,)))
                labels.append(item[0])
    return picks, labels
