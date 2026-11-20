"""工作坊自己更新自己：清單裡有維護者上傳、比自己新的「工作坊」，就先把自己換成那一版，再打開清單（D158）。

為什麼：工作坊是用來修其他模組的那一個，它自己一定要能開。核心的「更新」會順便換隨附模組（D156），但沒用「更新」升級、
或檔案被改過的電腦就換不到；2026-11-19 研究助理的老闆就卡在這裡（互通、工作坊都還是 0.5 那時候的）。
只有工作坊自己會自動更新，其他模組不會（研究助理：「不然很搞人，像 Windows 強迫更新那樣」）。

規矩：
- 只認清單裡 author 是維護者（workshop.MAINTAINERS）的那一筆；別人上傳一個叫「工作坊」的模組不會被裝進來。
- 下載的包 sha256 要對、最上層要是「工作坊/」、裡面要有 iplot.py、workshop.py、page.html。
- 換之前整個資料夾存進 .history/（跟工作坊覆蓋別的模組一樣）；換到一半出錯就照那份放回去。
- 不放 .unconfirmed、不寫 .origin：它還是隨附模組，下一次核心更新照樣可以換它。
- 任何一步不對都只是「這次不更新」，照舊用現在這一版打開清單，不會讓工作坊打不開。

這個檔只用標準庫與旁邊的 workshop.py，要在 iPLoT 0.5 以後每一版核心上都能跑（tests/test_workshop_every_core.py）。"""

import json
import re
import shutil
import unicodedata
import zipfile
from pathlib import Path

NAME = "工作坊"
NEEDED = ("iplot.py", "workshop.py", "page.html")


def own_version(folder):
    """工作坊自己的版本：CHANGELOG.md 最上面那一節的版本號；讀不到（0.7.3 以前的工作坊沒有 CHANGELOG）回 "0"。"""
    try:
        text = (Path(folder) / "CHANGELOG.md").read_text(encoding="utf-8-sig")
    except (OSError, ValueError):
        return "0"
    found = re.search(r"^## \[(\d+(?:\.\d+)*)\]", text, re.M)
    return found.group(1) if found else "0"


def newer_entry(entries, folder, workshop):
    """清單裡維護者上傳、比 folder 裡這一版新的「工作坊」那一筆；沒有回 None。"""
    mine = own_version(folder)
    for e in entries:
        if (isinstance(e.get("name"), str) and unicodedata.normalize("NFC", e["name"]) == NAME
                and workshop.by_maintainer(e.get("author")) and workshop._newer(mine, e["version"])):
            return e
    return None


def update(entry, folder, workshop):
    """把 folder（工作坊自己的資料夾）換成 entry 那一版，回新的版本號。不對就丟 ValueError、資料夾不動；
    寫到一半出錯丟 workshop.NotInstalled（訊息說放回去了沒有）；連不上丟 workshop.NETWORK 裡的例外。"""
    folder = Path(folder)
    tmp = folder.parent / ".workshop-self-tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        package = workshop.download(entry["zip_url"], tmp / "package.zip", entry["sha256"])
        with zipfile.ZipFile(package) as z:
            names = [unicodedata.normalize("NFC", n) for n in z.namelist()]
            if any(not n.startswith(NAME + "/") or ".." in n.split("/") for n in names):
                raise ValueError(f"包的最上層不是「{NAME}/」")
            z.extractall(tmp / "unpacked")
        unpacked = next(p for p in (tmp / "unpacked").iterdir() if unicodedata.normalize("NFC", p.name) == NAME)
        files = workshop._files(unpacked)
        missing = [n for n in NEEDED if n not in [rel for rel, _ in files]]
        if missing:
            raise ValueError("包裡少了 " + "、".join(missing))
        if own_version(unpacked) != str(entry["version"]):
            raise ValueError(f"包裡的版本是 {own_version(unpacked)}，清單寫的是 {entry['version']}")
        saved = workshop.snapshot(folder)
        try:
            for rel, source in files:
                target = folder / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            shutil.rmtree(folder / "__pycache__", ignore_errors=True)
        except OSError as exc:
            back = workshop._rollback(folder, saved)
            done = "已從快照放回" if back else f"放回時出錯，快照在 {saved}"
            raise workshop.NotInstalled(f"{workshop.plain(exc).partition('。')[0]}；沒有換成，{done}") from exc
    except StopIteration:
        raise ValueError(f"包裡沒有「{NAME}」資料夾") from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return own_version(folder)


def describe(exc, workshop):
    """自動更新沒成功時給人看的原因（中文，一句）。"""
    if isinstance(exc, workshop.NETWORK) and not isinstance(exc, workshop.NotInstalled):
        return workshop.plain(exc)
    if isinstance(exc, (ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError)):
        return str(exc) or type(exc).__name__
    return str(exc)
