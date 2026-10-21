# 抄自 iPLoT v0.5.1 的 modules/工作坊/workshop.py（M7 之前）。測試用：0.5.1 的工作坊讀新的 index.json 是什麼樣子、install 收不收得下 build 打的 zip。不要改。
"""「工作坊」的做法：讀索引、算每個模組在這台電腦上的狀態、下載安裝、覆蓋前把舊資料夾整個存起來。
這裡都是普通的函式，旁邊的 iplot.py 只負責串起來，page.html 是列出清單的那一頁。

規矩（D70）：只寫進自己裝的那個 modules/<名稱>/ 與暫存資料夾；覆蓋前，舊資料夾整個存進它自己的 .history/；
從這裡裝進來的模組帶著空檔案 .unconfirmed，第一次執行前 iPLoT 會先問一次。"""
import contextlib
import hashlib
import html
import http.client
import json
import os
import shutil
import ssl
import threading
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime

ORIGIN, UNCONFIRMED = ".origin", ".unconfirmed"
# 各台電腦自己的東西：不進包、包裡夾帶了也不裝（跟 tools/publish.py 的 SKIP 要一樣）。
# 比對時不分大小寫：macOS 的檔案系統上「.Origin」跟「.origin」是同一個名字
SKIP = {".history", ".origin", ".unconfirmed", "__pycache__", ".ds_store"}
NETWORK = (OSError, http.client.HTTPException)  # 連不上、逾時、連到一半斷掉、伺服器沒回話
LABELS = {"absent": "未安裝", "installed": "已安裝", "update": "可更新", "modified": "已修改", "unknown": "版本未知",
          "bundled": "隨附模組"}
BUTTONS = {"absent": "安裝", "update": "更新", "modified": "覆蓋", "unknown": "覆蓋"}  # 已安裝、隨附模組的沒有按鈕
# iPLoT 自己要用的隨附模組：工作坊不覆蓋（覆蓋之後帶著 .unconfirmed，右鍵動作每次先問、啟動時要安裝介面卻沒辦法回答）
BUNDLED = ("作業系統", "更新", "工作坊")
BUNDLED_NOTE = "這是 iPLoT 自己要用的隨附模組，工作坊不覆蓋它；要換新版，自己把新的資料夾複製進 modules/。"
CONFIRM = "需要確認"  # 已修改、版本未知的要先確認才覆蓋：page.html 看到這個回答就不會當成裝好了
NEEDED = ("name", "version", "zip_url", "sha256")  # 索引的每一筆至少要有這幾項


def _context():
    """驗證 https 憑證用的設定。python.org 的 macOS Python 預設沒有根憑證（要另外執行 Install Certificates.command），
    那樣每個 https 網址都會驗證失敗；憑證庫是空的時候，改用 macOS 自己的那一份。驗證本身不關。"""
    context = ssl.create_default_context()
    if not context.cert_store_stats()["x509_ca"] and os.path.exists("/etc/ssl/cert.pem"):
        context.load_verify_locations("/etc/ssl/cert.pem")
    return context


def _open(url, timeout):
    """打開網址（https://、file:// 都行）。網址裡的中文與空白先寫成 %XX：urllib 只收 ASCII 的網址。"""
    return urllib.request.urlopen(urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~"), timeout=timeout,
                                  context=_context())


def read_index(url, timeout=15):
    """讀 index.json，回裡面的 modules 清單（版本一律當字串；同名的只留第一筆）。
    格式不對（不是 JSON、沒有 modules、某一筆缺項或型別不對）丟 ValueError。"""
    with _open(url, timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    entries = data.get("modules") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not all(isinstance(e, dict) and all(k in e for k in NEEDED) for e in entries):
        raise ValueError("index.json 的格式不對")
    if not all(isinstance(e[k], str) for e in entries for k in ("name", "zip_url", "sha256")):
        raise ValueError("index.json 裡的名稱、網址、sha256 應該都是文字")
    seen = {}
    for e in entries:
        seen.setdefault(e["name"], {**e, "version": str(e["version"])})
    return list(seen.values())


def read_origin(folder):
    """讀模組資料夾裡的 .origin（一行一個「key: value」）。沒有這個檔回 None；
    讀不懂、或少了 url／version／sha256／digest／files 任何一項，回空的 dict（當作壞掉）。"""
    try:
        lines = (folder / ORIGIN).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}
    pairs = [line.partition(": ") for line in lines if line.strip()]
    data = {key: value for key, sep, value in pairs if sep}
    complete = len(data) == len(pairs) and all(k in data for k in ("url", "version", "sha256", "digest", "files"))
    return data if complete else {}


def write_origin(folder, data):
    (folder / ORIGIN).write_text("".join(f"{key}: {value}\n" for key, value in data.items()), encoding="utf-8")


def _local(parts):
    """路徑裡有沒有哪一段是各台電腦自己的名字（SKIP）；不分大小寫。"""
    return any(part.casefold() in SKIP for part in parts)


def _files(folder):
    """folder 裡算數的檔案（相對路徑, 路徑），照相對路徑排序；SKIP 裡的名字不管在哪一層都不算。"""
    found = [(p.relative_to(folder).as_posix(), p) for p in folder.rglob("*")
             if p.is_file() and not _local(p.relative_to(folder).parts)]
    return sorted(found)


def digest(folder, files):
    """files（相對路徑的清單）這些檔在 folder 裡現在的摘要：照路徑的順序，把「路徑＋內容」一個個餵進 sha256。
    改了其中一個、少了其中一個都會變；清單以外的檔（模組自己存的設定、資料）不算。"""
    h = hashlib.sha256()
    for rel in sorted(files):
        path = folder / rel
        h.update(rel.encode("utf-8") + b"\0" + (path.read_bytes() if path.is_file() else b"<missing>") + b"\0")
    return h.hexdigest()


def _module_dirs(folder, rels):
    """要放 .unconfirmed 的資料夾（相對路徑，"" 是模組資料夾自己）：包裡（rels）與磁碟上現在每一個有 iplot.py 的資料夾。
    磁碟上的也要：包可能只帶了下一層模組旁邊的 helper.py，那個 iplot.py 是上一版留下、確認過的，執行它一樣跑了新下載的程式。"""
    on_disk = [p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.name == "iplot.py"]
    return {rel.rpartition("/")[0] for rel in [*rels, *on_disk]
            if rel.rpartition("/")[2] == "iplot.py" and not _local(rel.split("/"))}


def _newer(current, latest):
    try:
        return tuple(int(p) for p in str(latest).split(".")) > tuple(int(p) for p in str(current).split("."))
    except ValueError:
        return False


def _bundled(name, modules_dir):
    """name 是不是 BUNDLED 裡的一個。macOS 的檔名不分大小寫、也不分 Unicode 的寫法（相容表意字「更」就是「更」），
    所以先正規化再比；資料夾在的話，再問檔案系統是不是同一個資料夾。"""
    if unicodedata.normalize("NFC", name).casefold() in {b.casefold() for b in BUNDLED}:
        return True
    folder = modules_dir / name
    with contextlib.suppress(OSError):
        return folder.exists() and any((modules_dir / b).exists() and folder.samefile(modules_dir / b) for b in BUNDLED)
    return False


def state(entry, modules_dir):
    """索引裡這一筆，在這台電腦上是什麼狀態：
    bundled iPLoT 自己要用的隨附模組（BUNDLED），工作坊不碰；absent 沒有這個資料夾；
    unknown 資料夾在但不是從工作坊裝的（沒有 .origin）；
    modified 當初裝進來的檔有被改過、刪掉（或 .origin 壞了）；update 沒改過、索引的版本比較新；
    installed 沒改過、已經是這一版。模組自己另外存的檔不算改過。"""
    if _bundled(entry["name"], modules_dir):
        return "bundled"
    folder = modules_dir / entry["name"]
    if not folder.exists():
        return "absent"
    origin = read_origin(folder)
    if origin is None:
        return "unknown"
    try:
        files = json.loads(origin.get("files", ""))
        same = isinstance(files, list) and origin["digest"] == digest(folder, [str(f) for f in files])
    except (ValueError, OSError):
        same = False
    if not same:
        return "modified"
    return "update" if _newer(origin["version"], entry["version"]) else "installed"


def _stamped(folder, suffix):
    """folder 底下一個帶日期時間的新檔名；同一秒內的第二個加 -2。"""
    stamp, n = f"{datetime.now():%Y%m%d-%H%M%S}", 1
    path = folder / f"{stamp}{suffix}"
    while path.exists():
        n += 1
        path = folder / f"{stamp}-{n}{suffix}"
    return path


def _kept(parts):
    """路徑是不是在快照住的那個資料夾——模組資料夾最上層的 .history/——裡面；不分大小寫：macOS 上本來就有的
    .History/ 跟 .history/ 是同一個資料夾。下一層子模組自己的 .history/（核心替它存的上一版）不算：它跟著進快照、放回來。"""
    return bool(parts) and parts[0].casefold() == ".history"


def snapshot(folder):
    """把整個模組資料夾（.history/ 自己除外）壓成 .history/<日期時間>-folder.zip，回那個檔。
    寫到一半出錯（OSError）就把寫了一半的 zip 刪掉再丟出去。"""
    (folder / ".history").mkdir(exist_ok=True)
    saved = _stamped(folder / ".history", "-folder.zip")
    files = [(p.relative_to(folder).as_posix(), p) for p in sorted(folder.rglob("*"))
             if p.is_file() and not _kept(p.relative_to(folder).parts)]
    try:
        with zipfile.ZipFile(saved, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as z:  # 1980 年以前的檔也收
            for rel, path in files:
                z.write(path, rel)
    except OSError:
        with contextlib.suppress(OSError):
            saved.unlink()
        raise
    return saved


def download(url, dest, sha256, timeout=60):
    """把 url 下載到 dest，回 dest。內容的 sha256 對不上就把 dest 刪掉、丟 ValueError。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    with _open(url, timeout) as r, dest.open("wb") as f:
        for chunk in iter(lambda: r.read(1 << 16), b""):
            h.update(chunk)
            f.write(chunk)
    if h.hexdigest() != str(sha256).lower():
        dest.unlink()
        raise ValueError("下載的檔案跟索引寫的 sha256 對不上")
    return dest


def _clear(folder, rel):
    """準備好寫 folder/rel：一路上的資料夾建起來；擋路的東西拿掉——該是資料夾的地方有個檔案、該是檔案的地方有個資料夾，
    或是符號連結（不順著它寫到模組資料夾外面）。被拿掉的東西都在覆蓋前存的那份快照裡。回要寫的路徑。"""
    path, parts = folder, rel.split("/")
    for part in parts[:-1]:
        path = path / part
        if path.is_symlink() or path.is_file():
            path.unlink()
        path.mkdir(exist_ok=True)
    path = path / parts[-1]
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    return path


class NeedsConfirmation(Exception):
    """包裡的檔會蓋掉或拿掉模組自己存的檔（不在 .origin 的 files 裡）：要先問過才裝（D77）。"""


def _clashes(folder, rels, listed):
    """把包裡的 rels 放進 folder 時，會被蓋掉或拿掉、又不是當初裝進來的（不在 listed 裡）那些本機檔，相對路徑。
    看三種：同名的檔（蓋掉）、同名的資料夾裡的檔（整個資料夾拿掉）、擋在路上的檔（要建資料夾的地方有個檔）。"""
    hit = set()
    for rel in rels:
        parts = rel.split("/")
        for i in range(1, len(parts) + 1):
            path = folder.joinpath(*parts[:i])
            if path.is_symlink() or path.is_file():
                hit.add("/".join(parts[:i]))
                break
            if i == len(parts) and path.is_dir():
                hit.update(p.relative_to(folder).as_posix() for p in path.rglob("*") if p.is_symlink() or p.is_file())
    return sorted(h for h in hit if h not in listed and not _local(h.split("/")))


class NotInstalled(OSError):
    """裝到一半出錯、已經（或沒能）放回原樣。訊息就是要給人看的那一句。"""


def _contents(folder):
    """folder 裡的檔案（相對路徑 → 內容），挑法跟 snapshot 一樣：.history/ 以外的每一個檔。"""
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*")
            if p.is_file() and not _kept(p.relative_to(folder).parts)}


def _readable(saved):
    """快照讀得到、每個檔都解得開（testzip）才算。"""
    try:
        with zipfile.ZipFile(saved) as z:
            return z.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


def _rollback(folder, saved):
    """裝到一半出錯：把模組資料夾放回裝之前的樣子，回有沒有放回去。saved 是覆蓋前存的快照；None 表示原本沒有這個資料夾。
    讓安裝失敗的原因（鎖定的檔、唯讀的資料夾）通常也讓這裡刪不掉、寫不回去：遇到錯不停下來，能刪的刪、能放的放，
    最後逐檔跟快照比，一樣才算放回去了。快照讀不到的話一樣都不刪（刪了就補不回來）。
    沒放回去的話，留下來的每個模組資料夾都放 .unconfirmed（裡面可能有新下載的程式）。"""
    if saved is None:
        shutil.rmtree(folder, ignore_errors=True)
        back = not folder.exists()
    elif not _readable(saved):
        back = False
    else:
        for path in folder.iterdir():
            if not _kept([path.name]):
                with contextlib.suppress(OSError):
                    shutil.rmtree(path, ignore_errors=True) if path.is_dir() and not path.is_symlink() else path.unlink()
        try:
            with zipfile.ZipFile(saved) as z:
                for member in z.infolist():
                    with contextlib.suppress(OSError):
                        z.extract(member, folder)
                back = _contents(folder) == {m.filename: z.read(m) for m in z.infolist() if not m.is_dir()}
        except (OSError, zipfile.BadZipFile):
            back = False
    if not back:
        for rel in _module_dirs(folder, []):
            with contextlib.suppress(OSError):
                (folder / rel / UNCONFIRMED).touch()
    return back


def install(entry, modules_dir, confirmed=False):
    """照索引的這一筆安裝（或覆蓋）一個模組，回安裝後的狀態。不對就丟 ValueError，模組資料夾不動：
    名稱要是單純的資料夾名；sha256 要對；zip 的最上層要剛好是 <名稱>/，裡面要有 iplot.py。
    從工作坊裝過的（有 .origin）、包裡的檔又會蓋掉或拿掉模組自己存的檔（不在 .origin 的 files 裡）：
    沒有 confirmed 就丟 NeedsConfirmation，模組資料夾不動（D77）。
    資料夾已經在的話，先整個存進它的 .history/，再把包裡的檔案蓋上去（包裡沒有的舊檔案留著）；
    蓋到一半出錯（OSError）就照那份快照放回原樣，丟 NotInstalled，訊息照實說放回去了沒有、沒放回的話快照在哪裡。
    包裡與磁碟上每一個有 iplot.py 的資料夾都先放好 .unconfirmed，才開始放程式。"""
    name = entry["name"]
    if not isinstance(name, str) or not name.strip() or name.startswith(".") or set(name) & set("/\\"):
        raise ValueError("索引裡的模組名稱不是單純的資料夾名")
    if _bundled(name, modules_dir):
        raise ValueError(f"「{name}」是 iPLoT 自己要用的隨附模組，工作坊不覆蓋它")
    folder, tmp = modules_dir / name, modules_dir / ".workshop-tmp"
    if folder.is_symlink():
        raise ValueError(f"「{name}」是一個符號連結，不裝進去")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        package = download(entry["zip_url"], tmp / "package.zip", entry["sha256"])
        with zipfile.ZipFile(package) as z:
            names = z.namelist()
            if any(not n.startswith(name + "/") or ".." in n.split("/") for n in names):
                raise ValueError(f"zip 的最上層不是「{name}/」")
            z.extractall(tmp / "unpacked")
        files = _files(tmp / "unpacked" / name)
        if "iplot.py" not in [rel for rel, _ in files]:
            raise ValueError("包裡沒有 iplot.py")
        origin = read_origin(folder) if folder.exists() else None
        if origin and not confirmed:
            try:
                listed = json.loads(origin["files"])
            except ValueError:
                listed = []
            if _clashes(folder, [rel for rel, _ in files], listed if isinstance(listed, list) else []):
                raise NeedsConfirmation(name)
        try:
            saved = snapshot(folder) if folder.exists() else None
        except OSError as exc:
            raise NotInstalled(f"{exc}；沒有裝成，還沒動到資料夾（存快照時出錯）") from exc
        try:
            folder.mkdir(exist_ok=True)
            for rel in _module_dirs(folder, [rel for rel, _ in files]):  # 先放標記，才放程式
                _clear(folder, f"{rel}/{UNCONFIRMED}" if rel else UNCONFIRMED).touch()
            for rel, source in files:
                shutil.copyfile(source, _clear(folder, rel))
            listed = [rel for rel, _ in files]
            write_origin(folder, {"url": entry["zip_url"], "version": entry["version"], "sha256": entry["sha256"],
                                  "digest": digest(folder, listed), "files": json.dumps(listed, ensure_ascii=False),
                                  "installed": f"{datetime.now():%Y-%m-%d %H:%M:%S}"})
        except OSError as exc:
            unreadable = saved is not None and not _readable(saved)
            back = _rollback(folder, saved)
            if saved is None:
                done = "沒有裝成，裝了一半的資料夾已經拿掉" if back else f"沒有裝成，裝了一半的資料夾拿不掉：{folder}"
            elif unreadable:
                done = f"沒有裝成，快照讀不到、沒有放回，資料夾現在是新舊混合：{folder}"
            else:
                done = "沒有裝成，已從快照放回" if back else f"沒有裝成，放回時出錯，快照在 {saved}"
            raise NotInstalled(f"{exc}；{done}") from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return state(entry, modules_dir)


def render(entries, modules_dir, template):
    """把索引變成 page.html 裡的一列列（放進 template 的 {rows}）。索引是從網路來的，裡面的字一律當文字，不當 HTML。"""
    rows = []
    for entry in entries:
        now = state(entry, modules_dir)
        name = html.escape(str(entry["name"]), quote=True)
        button = (f'<button type="button" data-name="{name}" data-ask="{int(now in ("modified", "unknown"))}">'
                  f"{BUTTONS[now]}</button>") if now in BUTTONS else ""
        note = f'<div class="note">{BUNDLED_NOTE}</div>' if now == "bundled" else ""
        notes = entry.get("notes") or ""  # 這一版改了什麼（D78）；舊的索引沒有這一項
        notes = f'<div class="notes">這一版：{html.escape(str(notes))}</div>' if notes else ""
        rows.append(
            f'<tr><td class="icon">{html.escape(str(entry.get("icon") or ""))}</td>'
            f'<td><b>{name}</b><div class="desc">{html.escape(str(entry.get("description") or ""))}</div>{notes}{note}</td>'
            f'<td class="ver">{html.escape(str(entry["version"]))}</td>'
            f'<td class="state">{LABELS[now]}</td><td class="act">{button}</td></tr>')
    head, mark, tail = template.rpartition("{rows}")  # 只換最後一個：前面的說明文字裡提到它也沒關係
    return head + "\n".join(rows) + tail if mark else template


class Api:
    """工作坊那一頁的 JS 呼叫的入口（pywebview.api.install）。屬性都以底線開頭：公開的只有 install。"""

    def __init__(self, app, entries, modules_dir):
        self._app, self._entries, self._modules_dir = app, entries, modules_dir
        self._lock = threading.Lock()  # 清單頁可以連按兩列；安裝一次只做一個（它們共用暫存資料夾）

    def install(self, name, confirmed=False):
        """安裝、更新或覆蓋 name，回新的狀態（中文）。已修改、版本未知的，還有更新會蓋掉模組自己存的檔的（D77），
        要 confirmed 才做，否則回 CONFIRM、什麼都不動。出錯回一句「無法安裝：…」，不丟例外。"""
        entry = next((e for e in self._entries if e["name"] == name), None)
        if entry is None:
            return f"無法安裝：清單裡沒有「{name}」"
        try:
            with self._lock:
                if state(entry, self._modules_dir) in ("modified", "unknown") and not confirmed:
                    return CONFIRM
                return LABELS[install(entry, self._modules_dir, confirmed)]
        except NeedsConfirmation:
            return CONFIRM
        except zipfile.BadZipFile:
            return "無法安裝：下載的檔案不是 zip"
        except (ValueError, KeyError, TypeError) as exc:  # sha256 不符、包的內容不對、索引那一筆的型別不對
            return f"無法安裝：{exc}"
        except NotInstalled as exc:  # 寫檔出錯：訊息裡已經說了放回去了沒有
            return f"無法安裝：{exc}"
        except NETWORK as exc:  # 連不上、下載到一半斷了
            return f"無法安裝：{getattr(exc, 'reason', exc)}"
