"""設定.json 的讀寫：這個模組自己的設定，各台電腦自己的（網址等於密碼，所以檔案權限是 0600）。

格式是一個 JSON 物件，之後要加欄位不用改格式：現在有 "資料夾"（日記資料夾）與 "LINE"（url、auto_copy；
之後多的寫入金鑰也放在 "LINE" 底下）。每次寫都是「讀出來、改一個鍵、寫回去」，不認得的鍵原樣保留。
write_private 也給別的小檔用（LINE 的快取、已複製的紀錄）。
這個檔只用標準庫、不 import core：直接 python3 iplot.py 時也載得進來。"""

import json
import os
from collections.abc import Callable
from pathlib import Path


def write_private(path: Path, text: str) -> None:
    """先寫同資料夾的暫存檔（權限 0600）再 os.replace：不會寫到一半，檔案也不會有別人可讀的瞬間。失敗時不留暫存檔。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.chmod(tmp, 0o600)  # 暫存檔本來就在的話，open 不會改它的權限
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read(path: Path) -> dict:
    """設定檔的內容；沒有、壞掉（不是 UTF-8、不是 JSON）、不是物件都回 {}。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def update(path: Path, mutate: Callable[[dict], None]) -> dict:
    """讀出來、交給 mutate 改、寫回去；回寫回去的內容。不認得的鍵原樣保留；寫不進去的 OSError 往外丟。"""
    data = read(path)
    mutate(data)
    write_private(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return data


def line(path: Path) -> dict:
    """"LINE" 那一區；沒有或不是物件回 {}。"""
    section = read(path).get("LINE")
    return section if isinstance(section, dict) else {}


def line_section(data: dict) -> dict:
    """data（read 的結果，要改的那一份）裡的 "LINE" 區；沒有或不是物件就換成新的空物件放進去，回它。給 update 的 mutate 用。"""
    if not isinstance(data.get("LINE"), dict):
        data["LINE"] = {}
    return data["LINE"]
