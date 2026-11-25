"""行事曆：打開就是這個月的月曆；每天寫行程、心情、看到了什麼、做了什麼，放圖片，存成一天一個資料夾並產生網頁。

上方的模組列叫得到任何模組；任何模組寫 app.run("行事曆") 就叫得到它。iPLoT 1.0 每按一次就在自己的程序裡跑（D161），
頁面開著不卡面板；同一時間只開一個，已經開著就叫到最前面（D164）。資料在 ~/Documents/行事曆
（⚙ 可以換），一天一個資料夾 <年>/<月>/<日>/，Finder 看得到；「發佈」只產生 發佈/ 資料夾，不上傳。"""
import base64
import binascii
import datetime
import functools
import os
import pathlib
import subprocess

# ── iPLoT ── 直接執行這個檔（python3 iplot.py）時交給 iPLoT 跑（python3 main.py --run）；從 iPLoT 裡執行時這段不做事。不要可以整段刪掉
import sys

if __name__ == "__main__" and "core.runner" not in sys.modules:
    import os
    import subprocess
    here = folder = os.path.dirname(os.path.abspath(__file__))
    main = None
    while main is None and folder != os.path.dirname(folder):  # 往上一層層找 iPLoT：模組在它裡面或旁邊都找得到
        folder = os.path.dirname(folder)
        try:
            names = [""] + sorted(os.listdir(folder))
        except OSError:
            names = [""]
        mains = (os.path.join(folder, n, "main.py") for n in names)
        main = next((m for m in mains if os.path.isfile(m) and os.path.isdir(os.path.join(os.path.dirname(m), "core"))), None)
    if main and not os.environ.get("IPLOT_DIRECT"):  # IPLOT_DIRECT=1：不交出去，照一般腳本跑（例如在編輯器裡除錯）
        sys.exit(subprocess.call([sys.executable, main, "--run", here, *sys.argv[1:]]))
    if not main:
        print("找不到 iPLoT（模組要放在 iPLoT 資料夾裡或它旁邊），照一般的 python3 iplot.py 跑", file=sys.stderr)
# ── iPLoT ──

import threading
import unicodedata

import diary
import pages
import photos

ICON = "📅"
NEEDS = ("os.activate",)  # 已經開著時叫它到最前面（D164）
PROVIDES = {"home": "run"}  # 在面板外跑完一個模組，小視窗的回去鈕回到這裡（D93；以前看名字，1.0 起看這個角色）
MIN_API = 7  # app.top_modules、每按一次在自己的程序裡跑（D161、D164）
OPEN = (".local", "開著")  # 頁面開著的那個程序拿著這個檔的鎖、寫著它的 pid；每台電腦自己的，不進上傳的包（規則 9）
SETTINGS = "設定.json"
HERE = pathlib.Path(__file__).resolve().parent
ICON_FILE = HERE / "icon.png"
ALREADY = "行事曆已經開著"
ALREADY_BEHIND = "行事曆已經開著（在 Dock 上找月曆的圖示）"
CANNOT_WRITE = "存不進去：{why}。字還在，等一下會再試"
BAD_CHARS = "這段文字裡有存不進去的字元，請改掉它再存"
UNREADABLE = "讀不到這個檔（不是 UTF-8），沒有覆寫它。用文字編輯器打開它、另存成 UTF-8，再回到這一天：{path}"
NOT_FOUND = "找不到「{name}」（可能被改名或刪掉了）"
CANNOT_LAUNCH = "打不開「{name}」：{why}。到 iPLoT 的面板直接雙擊它試試"
NO_PUBLIC = "還沒有打開「公開」的日子"
UNPUBLISHED = "沒有公開的日子了，已經拿掉 發佈/"
UPLOAD_NOTE = "上傳方式還沒設定：把『發佈』裡的東西放到網頁空間"


def set_dock_icon(path: pathlib.Path, platform: str = sys.platform) -> bool:
    """macOS：把這個程序在 Dock 上的圖示換成 path（交給主執行緒換）。其他系統、或載不進 AppKit 回 False。"""
    if platform != "darwin":
        return False
    try:
        import AppKit
        from PyObjCTools import AppHelper
    except ImportError:
        return False
    image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(path))
    if image is None:
        return False
    AppHelper.callAfter(AppKit.NSApplication.sharedApplication().setApplicationIconImage_, image)
    return True


LOCK_AT = 1 << 20  # Windows 鎖的那一格：在檔尾之後，不擋讀 pid


def hold(path: pathlib.Path):
    """拿「開著」的鎖：拿到了寫上這個程序的 pid、回打開的檔（關掉或程序結束鎖就放掉，不會留下過期的記號）；
    別的程序拿著（行事曆已經開著）回 None。鎖是系統的檔案鎖（macOS／Linux 的 flock、Windows 的 msvcrt）。
    Windows 的鎖會擋住別人讀那一段，所以鎖在 pid 後面很遠的一格（LOCK_AT），別人照樣讀得到 pid。"""
    path.parent.mkdir(exist_ok=True)
    f = open(path, "a+", encoding="utf-8")  # noqa: SIM115  開著的期間一直拿著，關頁面時才關
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(LOCK_AT)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    return f


def open_pid(path: pathlib.Path) -> int | None:
    """開著的那個程序的 pid；讀不到（檔壞了、沒寫完）回 None。"""
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def open_or_focus(app, folder: pathlib.Path, *, hold=hold, api=None) -> None:
    """同一時間只開一個行事曆：已經開著 → 請作業系統模組叫它到最前面（叫不動就說去哪裡找）；沒開 → 開頁面，關掉才回來。
    頁面在這次按下的程序裡開（D161），面板不會被卡住。"""
    lock = hold(folder.joinpath(*OPEN))
    if lock is None:
        pid = open_pid(folder.joinpath(*OPEN))
        app.log(ALREADY if pid is not None and app.call("os.activate", pid) else ALREADY_BEHIND)
        return
    try:
        app.page("行事曆", (folder / "page.html").read_text(encoding="utf-8"), api or Api(app, folder / SETTINGS))
    finally:
        lock.close()


def _guarded(method):
    """Api 的公開方法：抓同一把鎖（pywebview 每個呼叫各開一條執行緒，app.open／trash 改的是整個程序的狀態）；
    日期格式不對、寫不進去，變成 {"error": 一句話} 給頁面的狀態列，不丟 traceback、不叫 app.log。"""
    @functools.wraps(method)
    def call(self, *args):
        with self._lock:
            try:
                return method(self, *args)
            except UnicodeError:  # 也是 ValueError，要排在前面：存不了的字元，不貼 Python 的英文原文（體驗 6-02）
                return {"error": BAD_CHARS}
            except ValueError as exc:
                return {"error": str(exc)}
            except OSError as exc:
                return {"error": CANNOT_WRITE.format(why=diary.reason(exc))}
    return call


class Api:
    """頁面的 JS 用 pywebview.api.<方法> 呼叫的入口（設計第 7 節的 15 個方法）。自己的屬性一律底線開頭（頁面碰不到）；
    頁面傳進來的只有日期、名稱、圖片的檔名與內容，沒有一個方法收路徑；路徑一律是絕對的。"""

    def __init__(self, app, settings_file: pathlib.Path, *, default_root: pathlib.Path | None = None,
                 run=subprocess.run, platform: str = sys.platform, today=datetime.date.today,
                 dock_icon=set_dock_icon) -> None:
        self._app, self._settings = app, pathlib.Path(settings_file).absolute()
        self._default_root = (default_root or pathlib.Path.home() / "Documents" / "行事曆").absolute()
        self._run, self._platform = run, platform
        self._today, self._dock_icon, self._icon_done = today, dock_icon, False
        self._lock = threading.Lock()

    def _root(self) -> pathlib.Path:
        return diary.load_root(self._settings, self._default_root)

    def _images(self, date: str) -> list[dict]:
        folder = diary.day_folder(self._root(), date)
        return [{"name": name, "src": photos.thumbnail_url(folder, name, run=self._run, platform=self._platform)}
                for name in diary.read_day(self._root(), date)["images"]]

    def _settings_now(self) -> dict:
        root = self._root()
        return {"folder": str(root), "public_days": len(diary.all_days(root, public_only=True))}

    def _scan(self) -> list:
        """每個根目錄最上層現在的模組，每次重掃（設計第 15 節第 7 條）；不含行事曆自己與碰作業系統的模組（提供 os.*）。"""
        return [m for m in self._app.top_modules() if m.folder != HERE
                and not any(role.startswith("os.") for role, _ in m.provides)]

    @_guarded
    def month(self, ym):
        if not self._icon_done:
            self._icon_done = True
            if self._platform == "darwin" and ICON_FILE.exists():
                self._dock_icon(ICON_FILE, self._platform)
        root = self._root()
        missing = root != self._default_root.resolve() and not root.exists()  # 換過的資料夾不在了：外接碟沒接上（體驗 6-09）
        return {"ym": ym, "today": self._today().isoformat(), "days": diary.month_summary(root, ym), "folder": str(root),
                **({"missing": True} if missing else {})}

    @_guarded
    def year(self, y):
        root, year = self._root(), diary.parse_year(y)
        months = {}
        for m in range(1, 13):
            days = diary.month_summary(root, f"{year:04d}-{m:02d}")
            if days:
                months[f"{m:02d}"] = {d: info["mood"] for d, info in days.items()}
        return {"y": y, "months": months}

    @_guarded
    def day(self, date):
        return {**diary.read_day(self._root(), date), "images": self._images(date)}

    @_guarded
    def save(self, date, fields):
        fields = fields if isinstance(fields, dict) else {}
        wanted = {k: v for k, v in fields.items() if k in ("行程", "看到", "做了") and isinstance(v, str)}
        if "mood" in fields or "note" in fields:
            mood, note = fields.get("mood", ""), fields.get("note", "")
            wanted["心情"] = diary.mood_text(mood if isinstance(mood, str) else "", note if isinstance(note, str) else "")
        root = self._root()
        result = diary.save_day(root, date, wanted, self._app.config.history_keep)
        if result["changed"]:
            pages.rebuild_after_save(root, date)
        return {"saved": result["changed"], "unreadable": [UNREADABLE.format(path=p) for p in result["unreadable"].values()]}

    @_guarded
    def set_public(self, date, on):
        root = self._root()
        diary.set_public(root, date, bool(on))
        pages.rebuild_after_save(root, date)
        return {"public": diary.read_day(root, date)["public"]}

    @_guarded
    def add_image(self, date, name, data):
        name = photos.clean_name(name)
        folder = diary.day_folder(self._root(), date)
        try:
            raw = base64.b64decode(str(data).split(",", 1)[-1], validate=True)
        except (binascii.Error, ValueError):
            return {"images": self._images(date), "error": photos.NOT_IMAGE.format(name=name)}
        saved, problem = photos.add_image(folder, name, raw, run=self._run, platform=self._platform)
        if saved is not None:
            pages.rebuild_after_save(self._root(), date)
        return {"images": self._images(date), **({"error": problem} if problem else {})}

    @_guarded
    def remove_image(self, date, name):
        name, root = photos.clean_name(name), self._root()
        folder = diary.day_folder(root, date)
        if name in diary.read_day(root, date)["images"]:
            stem = pathlib.Path(name).stem
            pairs = pathlib.Path(name).suffix.lower() in (".jpg", ".jpeg")  # 只有 JPG 是 HEIC 轉出來的那一張
            for path in sorted(folder.iterdir()):
                same = path.name == name or (pairs and path.stem == stem and path.suffix.lower() in photos.HEIC)
                if same and path.is_file():
                    self._app.trash(path)
                    (folder / photos.THUMBS / f"{path.name}.jpg").unlink(missing_ok=True)
            pages.rebuild_after_save(root, date)
        return {"images": self._images(date)}

    @_guarded
    def open_page(self, kind, key):
        """「看網頁」：開那一頁的本機網頁；還沒產生過就先產生（便宜），再交給 app.open。"""
        root = self._root()
        if kind == "day":
            path, build = diary.day_folder(root, key) / "index.html", lambda: pages.build_day(root, key)
        elif kind == "month":
            y, m = diary.parse_ym(key)
            path, build = root / f"{y:04d}" / f"{m:02d}" / "index.html", lambda: pages.build_month(root, key)
        elif kind == "year":
            path, build = root / f"{diary.parse_year(key):04d}" / "index.html", lambda: pages.build_year(root, key)
        elif kind == "index":
            path, build = root / "index.html", lambda: pages.build_index(root)
        else:
            raise ValueError(f"日期格式不對：{kind}")
        if not path.exists():
            build()
        self._app.open(path)
        return {}

    @_guarded
    def publish(self):
        root = self._root()
        days = len(diary.all_days(root, public_only=True))
        if not days:  # 取消了最後一個公開的日子：上一次產生的 發佈/ 不能留著（照著再上傳，那幾天就還在網路上）
            return {"note": UNPUBLISHED} if pages.unpublish(root) else {"error": NO_PUBLIC}
        problems = []
        folder = pages.publish(root, run=self._run, platform=self._platform, problems=problems)
        self._app.open(folder)
        return {"days": days, "folder": str(folder), "problems": problems, "note": UPLOAD_NOTE}

    @_guarded
    def modules(self):
        """模組列：面板（提供 main 的）不放在列裡，放在右邊的「圖示面板」；回它的名字，沒有面板是 ""。"""
        found = self._scan()
        panels = [m for m in found if any(role == "main" for role, _ in m.provides)]
        return {"modules": [{"name": m.name, "icon": m.icon or m.title[:1], "title": m.title}
                            for m in found if m not in panels],
                "panel": panels[0].name if len(panels) == 1 else ""}

    @_guarded
    def launch(self, name):
        """開始跑模組列上的一個模組（app.start：它在自己的程序裡跑，行事曆不用等它）。"""
        wanted = unicodedata.normalize("NFC", str(name))
        found = [m for m in self._scan() if unicodedata.normalize("NFC", m.name) == wanted]
        if len(found) != 1:
            return {"error": NOT_FOUND.format(name=name)}
        try:
            self._app.start(found[0])
        except OSError as exc:
            return {"error": CANNOT_LAUNCH.format(name=name, why=diary.reason(exc))}
        return {}

    @_guarded
    def settings(self):
        return self._settings_now()

    def change_folder(self):
        """換資料夾：選擇視窗開著的期間不拿鎖（頁面的存照樣能進來）；選了才抓鎖寫設定。不搬資料。"""
        chosen = self._app.choose_folder()
        with self._lock:
            if chosen is not None:
                try:
                    diary.save_root(self._settings, pathlib.Path(chosen).absolute())
                except OSError as exc:
                    return {"error": CANNOT_WRITE.format(why=diary.reason(exc))}
            return self._settings_now()

    @_guarded
    def reveal_folder(self):
        root = self._root()
        root.mkdir(parents=True, exist_ok=True)
        self._app.open(root)
        return {}

    @_guarded
    def rebuild(self):
        return {"pages": len(pages.rebuild_all(self._root()))}


def run(app):
    """打開行事曆，或叫到最前面。"""
    open_or_focus(app, HERE)

