"""整理：面板上右鍵任何一個模組，就有「改名…」「移到垃圾桶…」。只動你自己新增的模組；隨附的、從工作坊裝來的有保護。"""
import errno
import os
import unicodedata

ICON = "🧹"
# iPLoT 0.8 起面板問「誰提供右鍵選單（menu.module）」，這個模組回它的兩項（D159）。核心不知道「整理」，也不知道選單
PROVIDES = {"menu.module": "items"}

# 隨附的模組（核心的包帶的）：iPLoT 的功能要靠它們，不讓人在面板上改名或刪除（D155）。
# tests/test_modify.py 對照 git 的內容，包多一個、少一個都會紅
BUNDLED = frozenset({"主控面板", "互通", "作業系統", "回報與討論", "工作坊", "打開核心原始碼", "更新", "行事曆", "重新啟動",
                     "開Terminal", "開工", "整理", "導覽列"})
FORBIDDEN_CHARS = set('/\\:*?"<>|')
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

T = {
    "hello": "整理：在面板上右鍵任何一個模組，就有「改名…」「移到垃圾桶…」。",
    "menu_rename": "改名…",
    "menu_remove": "移到垃圾桶…",
    "ask_rename": "『{name}』的新名稱",
    "bad_name": "名稱不能是空白、以 . 開頭、結尾是 . 或空白、含 / \\ : * ? \" < > |，"
                "也不能是 CON、NUL 這類 Windows 保留字（模組要能複製到任何系統）",
    "name_taken": "這裡已經有叫『{name}』的東西了（大小寫不同也算同一個），換一個名稱",
    "rename_failed": "沒有把『{name}』改名：{message}。它如果正開著，先關掉再試一次；它的資料夾沒有動",
    "renamed": "已把『{old}』改名為『{new}』",
    "protected_bundled": "『{name}』是 iPLoT 隨附的模組，iPLoT 的功能要靠它，不能從這裡改名或刪除。不想用它的話，什麼都不用做",
    "protected_parent": "『{name}』是『{parent}』的一部分，不能單獨改名或刪除；要處理就處理『{parent}』",
    "protected_workshop": "『{name}』是從工作坊裝來的，改了名字工作坊就認不得它、也沒辦法更新。不要它的話，可以移到垃圾桶，之後在工作坊還能再裝",
    "confirm_remove": "要把『{title}』移到垃圾桶嗎？\n整個資料夾（{folder}）都會移走，裡面的檔案也是。"
                      "要找回來，到垃圾桶（Windows 是資源回收筒）裡找，可以放回原來的位置。",
    "confirm_remove_workshop": "\n它是從工作坊裝來的，之後想再用，也可以到工作坊重新安裝。",
    "removed": "已把『{title}』移到垃圾桶。要找回來，到垃圾桶（Windows 是資源回收筒）裡找",
    "remove_failed": "沒有把『{title}』移到垃圾桶，它還在原來的地方。確認它沒有被別的程式開著，再試一次",
    "no_permission": "沒有權限",
    "refused": "系統拒絕了這個動作",
}


class BadName(ValueError):
    """名稱不可攜（跟 iPLoT 新增模組時擋的同一套，D54）。"""


def run(app):
    app.log(T["hello"])


def items(app, info):
    """右鍵選單上這個模組要多的項目：（顯示的字, 按下時呼叫的函式名）。函式收 (app, info)。"""
    return [(T["menu_rename"], "rename"), (T["menu_remove"], "remove")]


def refusal(info, home, rename):
    """不能動就回一句話（說為什麼、現在可以怎麼做），可以動回 None。
    隨附的模組（modules/ 底下名字在 BUNDLED 裡的）、它們底下的子模組，一律不能改名或刪除；
    別的模組底下的子模組，要處理就處理整個父層；從工作坊裝來的（資料夾裡有 .origin）不能改名，可以刪。"""
    top = (home / "modules").resolve()
    for folder in (info.folder, *info.folder.parents):
        if folder == info.root or folder == folder.parent:
            break
        if folder.parent == top and folder.name in BUNDLED:
            return T["protected_bundled"].format(name=info.name if folder == info.folder else folder.name)
        if folder != info.folder and (folder / ".origin").is_file():
            return T["protected_parent"].format(name=info.name, parent=folder.name)
    if rename and (info.folder / ".origin").is_file():
        return T["protected_workshop"].format(name=info.name)
    return None


def _bad_name(name):
    return (not name.strip() or name.startswith(".") or name != name.rstrip(". ")
            or any(c in FORBIDDEN_CHARS or ord(c) < 32 for c in name) or name.split(".")[0].upper() in RESERVED)


def target(info, new):
    """改名後的資料夾；名稱沒變回 None。名稱不可攜丟 BadName；同一層已經有同名的（不分大小寫、不分 NFC／NFD，
    各系統都一樣擋，因為模組以後會被複製到別的電腦）丟 FileExistsError。只改大小寫不算撞名。"""
    new = unicodedata.normalize("NFC", new.strip())
    if _bad_name(new):
        raise BadName(new)
    if new == unicodedata.normalize("NFC", info.folder.name):
        return None
    key = new.casefold()
    for name in os.listdir(info.folder.parent):
        if name != info.folder.name and unicodedata.normalize("NFC", name).casefold() == key:
            raise FileExistsError(new)
    return info.folder.with_name(new)


def rename(app, info, new=None):
    """模組的資料夾改名（模組的名字就是資料夾的名字）。new 沒給就問。資料夾裡的東西（.history、設定、子模組）跟著走；
    從別處用名字呼叫它的模組要自己跟著改。改不成就在訊息區說為什麼、回 None。"""
    if why := refusal(info, app.home, True):
        return app.log(why)
    if new is None and (new := app.ask(T["ask_rename"].format(name=info.name), info.name)) is None:
        return None
    try:
        folder = target(info, new)
        if folder is None:
            return None
        info.folder.rename(folder)
    except BadName:
        return app.log(T["bad_name"])
    except FileExistsError:
        return app.log(T["name_taken"].format(name=new.strip()))
    except OSError as exc:
        why = T["no_permission"] if exc.errno in (errno.EACCES, errno.EPERM) else T["refused"]
        return app.log(T["rename_failed"].format(name=info.name, message=why))
    app.rescan()
    app.log(T["renamed"].format(old=info.name, new=folder.name))
    return folder


def remove(app, info):
    """把模組的資料夾移到系統垃圾桶（永遠不直接刪除，可以放回）：先問一次，取消就什麼都不動。回有沒有移走。"""
    if why := refusal(info, app.home, False):
        app.log(why)
        return False
    ask = T["confirm_remove"].format(title=info.title, folder=info.folder)
    if not app.confirm(ask + (T["confirm_remove_workshop"] if (info.folder / ".origin").is_file() else "")):
        return False
    app.trash(info.folder)
    gone = not info.folder.exists()
    app.log(T["removed" if gone else "remove_failed"].format(title=info.title))
    app.rescan()
    return gone
