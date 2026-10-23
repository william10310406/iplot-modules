"""行事曆的資料（D90）：一天一個資料夾 <資料夾>/<YYYY>/<MM>/<DD>/，裡面是純文字與圖片，Finder 看得到、文字編輯器改得了。

行程.txt、看到.txt、做了.txt：UTF-8 文字，存成空的就刪掉那個檔。
心情.txt：第一行是五個表情之一或空行，第二行起是一句話；第一行不是那五個之一（例如用文字編輯器改過）就當作沒有表情。
公開：空檔案，有就是公開。覆寫或刪掉文字檔之前，舊的那一份存進 .history/<欄位>-<YYYYmmdd-HHMMSS>.txt。
這個檔只用標準庫、不 import core：直接 python3 iplot.py 時也載得進來。"""

import datetime
import json
import os
import re
import shutil
from pathlib import Path

FIELDS = ("行程", "心情", "看到", "做了")
MOODS = ("😄", "🙂", "😐", "😟", "😢")
PUBLIC = "公開"
IMAGES = (".jpg", ".jpeg", ".png", ".gif", ".heic", ".heif")
HISTORY = ".history"
DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})", re.ASCII)
YM = re.compile(r"(\d{4})-(\d{2})", re.ASCII)
YEAR = re.compile(r"\d{4}", re.ASCII)
SNAPSHOT = re.compile(r"(?P<field>.+)-(?P<stamp>\d{8}-\d{6})(?:-(?P<n>\d+))?\.txt", re.ASCII)
FIRST_LINE_FROM = ("行程", "做了", "看到")
SNAPSHOT_EVERY = datetime.timedelta(minutes=10)  # 同一個欄位的上一份快照不到這麼久，就不存新的（檔案照樣覆寫）


def _now() -> datetime.datetime:
    return datetime.datetime.now()


def parse_date(text: str) -> datetime.date:
    """YYYY-MM-DD → date；格式不對或不是真的日子（2026-02-30）丟 ValueError。"""
    m = DATE.fullmatch(text) if isinstance(text, str) else None
    try:
        if m is None:
            raise ValueError
        return datetime.date(*(int(g) for g in m.groups()))
    except ValueError:
        raise ValueError(f"日期格式不對：{text}") from None


def parse_ym(text: str) -> tuple[int, int]:
    m = YM.fullmatch(text) if isinstance(text, str) else None
    if m is None or not 1 <= int(m.group(2)) <= 12:
        raise ValueError(f"日期格式不對：{text}")
    return int(m.group(1)), int(m.group(2))


def parse_year(text: str) -> int:
    if not (isinstance(text, str) and YEAR.fullmatch(text)):
        raise ValueError(f"日期格式不對：{text}")
    return int(text)


def day_folder(root: Path, date: str) -> Path:
    d = parse_date(date)
    return Path(root) / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.day:02d}"


def write_text(path: Path, text: str) -> None:
    """先寫同資料夾的暫存檔再 os.replace：不會寫到一半。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def _order(p: Path) -> tuple[str, int]:
    m = SNAPSHOT.fullmatch(p.name)
    return m.group("stamp"), int(m.group("n") or 0)


def _mine(folder: Path, field: str) -> list[Path]:
    """.history/ 裡這個欄位自己的快照，新的在前；檔名不是我們的格式的不算。"""
    try:
        found = [p for p in folder.iterdir() if (m := SNAPSHOT.fullmatch(p.name)) and m.group("field") == field]
    except OSError:
        return []
    return sorted(found, key=_order, reverse=True)


def snapshot(path: Path, keep: int) -> None:
    """path 在就把它複製進 .history/（同一秒的加 -2、-3），同一個欄位只留最新的 keep 份；別的檔不碰。
    同一個欄位的上一份快照不到 10 分鐘就不存：打字停 1 秒就存一次，一段長的編輯只留「開始之前」那一份。"""
    if not path.exists():
        return
    folder, now = path.parent / HISTORY, _now()
    mine = _mine(folder, path.stem)
    if mine:
        last = datetime.datetime.strptime(_order(mine[0])[0], "%Y%m%d-%H%M%S")
        if datetime.timedelta(0) <= now - last < SNAPSHOT_EVERY:
            return
    folder.mkdir(exist_ok=True)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    new, n = folder / f"{path.stem}-{stamp}.txt", 1
    while new.exists():
        n += 1
        new = folder / f"{path.stem}-{stamp}-{n}.txt"
    shutil.copyfile(path, new)
    for old in _mine(folder, path.stem)[max(keep, 0):]:
        old.unlink()


def read_text(path: Path) -> str | None:
    """不存在回 ""；不是 UTF-8 回 None（讀不到）。"""
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeDecodeError:
        return None


def mood_text(mood: str, note: str) -> str:
    if not mood and not note:
        return ""
    return f"{mood if mood in MOODS else ''}\n{note}"


def parse_mood(text: str) -> tuple[str, str]:
    first, _, rest = text.partition("\n")
    if first in MOODS:
        return first, rest
    if first == "":
        return "", rest
    return "", text


def _images(folder: Path) -> list[str]:
    try:
        names = [p.name for p in folder.iterdir()
                 if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in IMAGES]
    except OSError:
        return []
    stems = {Path(n).stem for n in names if Path(n).suffix.lower() in (".jpg", ".jpeg")}
    return sorted(n for n in names if not (Path(n).suffix.lower() in (".heic", ".heif") and Path(n).stem in stems))


def read_day(root: Path, date: str) -> dict:
    folder = day_folder(root, date)
    day = {"date": date, "mood": "", "note": "", "行程": "", "看到": "", "做了": "", "images": _images(folder),
           "public": (folder / PUBLIC).is_file(), "unreadable": {}}
    for field in FIELDS:
        text = read_text(folder / f"{field}.txt")
        if text is None:
            day["unreadable"][field] = str(folder / f"{field}.txt")
            text = ""
        if field == "心情":
            day["mood"], day["note"] = parse_mood(text)
        else:
            day[field] = text
    return day


def save_day(root: Path, date: str, fields: dict[str, str], keep: int) -> dict:
    """存這一天有給的欄位；回 {"changed": [欄位…], "unreadable": {欄位: 路徑}}。寫不進去的 OSError 往外丟。"""
    folder = day_folder(root, date)
    changed, unreadable = [], {}
    for field in FIELDS:
        if field not in fields:
            continue
        path, text = folder / f"{field}.txt", fields[field]
        now = read_text(path)
        if now is None:
            unreadable[field] = str(path)
            continue
        if now == text:
            continue
        snapshot(path, keep)
        if text == "":
            path.unlink(missing_ok=True)
        else:
            write_text(path, text)
        changed.append(field)
    return {"changed": changed, "unreadable": unreadable}


def has_content(root: Path, date: str) -> bool:
    folder = day_folder(root, date)
    for field in FIELDS:
        text = read_text(folder / f"{field}.txt")
        if text is None or text.strip():
            return True
    return bool(_images(folder))


def _numbered(folder: Path, digits: int) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.is_dir() and len(p.name) == digits and p.name.isascii()
                      and p.name.isdigit())
    except OSError:
        return []


def all_days(root: Path, public_only: bool = False) -> list[str]:
    """有內容的日子（YYYY-MM-DD），由舊到新；public_only 只留公開的。root 不存在回 []。"""
    days = []
    for y in _numbered(Path(root), 4):
        for m in _numbered(y, 2):
            for d in _numbered(m, 2):
                date = f"{y.name}-{m.name}-{d.name}"
                try:
                    parse_date(date)
                except ValueError:
                    continue
                if has_content(root, date) and (not public_only or (d / PUBLIC).is_file()):
                    days.append(date)
    return days


def first_line(day: dict) -> str:
    for field in FIRST_LINE_FROM:
        for line in day.get(field, "").splitlines():
            if line.strip():
                return line.strip()
    return ""


def month_summary(root: Path, ym: str, public_only: bool = False) -> dict[str, dict]:
    y, m = parse_ym(ym)
    folder = Path(root) / f"{y:04d}" / f"{m:02d}"
    summary = {}
    for d in _numbered(folder, 2):
        date = f"{y:04d}-{m:02d}-{d.name}"
        try:
            parse_date(date)
        except ValueError:
            continue
        if not has_content(root, date):
            continue
        day = read_day(root, date)
        if public_only and not day["public"]:
            continue
        summary[d.name] = {"mood": day["mood"], "first": first_line(day), "images": bool(day["images"]),
                           "public": day["public"]}
    return summary


def set_public(root: Path, date: str, on: bool) -> None:
    marker = day_folder(root, date) / PUBLIC
    if on:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    else:
        marker.unlink(missing_ok=True)


def load_root(settings_file: Path, default: Path) -> Path:
    """設定.json 的「資料夾」；沒有、壞掉就用 default。"""
    try:
        value = json.loads(Path(settings_file).read_text(encoding="utf-8")).get("資料夾")
    except (OSError, ValueError, AttributeError):
        value = None
    return Path(value if isinstance(value, str) and value else default).expanduser().resolve()


def save_root(settings_file: Path, root: Path) -> None:
    write_text(Path(settings_file), json.dumps({"資料夾": str(root)}, ensure_ascii=False, indent=2) + "\n")
