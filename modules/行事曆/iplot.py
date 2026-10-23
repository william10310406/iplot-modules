"""行事曆：打開就是這個月的月曆；每天寫行程、心情、看到了什麼、做了什麼，放圖片，存成一天一個資料夾並產生網頁。

上方的模組列叫得到任何模組；任何模組寫 app.run("行事曆") 就叫得到它。行事曆的頁面只在它自己另開的程序裡開（D89）：
在面板裡、或被別的模組叫到時，經「互通」的 run.py 另開一個程序；已經開著就叫到最前面。資料在 ~/Documents/行事曆
（⚙ 可以換），一天一個資料夾 <年>/<月>/<日>/，Finder 看得到；「發佈」只產生 發佈/ 資料夾，不上傳。"""
import base64
import binascii
import datetime
import functools
import os
import pathlib
import subprocess

# ── 互通 ── 直接執行這個檔（python3 iplot.py）時交給 iPLoT 用彈出式視窗跑；從 iPLoT 裡執行時這段不做事。不要可以整段刪掉
import sys

if __name__ == "__main__" and "core.runner" not in sys.modules:
    import os
    import subprocess
    here = folder = os.path.dirname(os.path.abspath(__file__))
    run = None
    while run is None and folder != os.path.dirname(folder):  # 往上一層層找 iPLoT：模組在它裡面或旁邊都找得到
        folder = os.path.dirname(folder)
        try:
            names = [""] + sorted(os.listdir(folder))
        except OSError:
            names = [""]
        runs = (os.path.join(folder, n, "modules", "互通", "run.py") for n in names)
        run = next((r for r in runs if os.path.isfile(r)), None)
    if run and not os.environ.get("IPLOT_DIRECT"):  # IPLOT_DIRECT=1：不交出去，照一般腳本跑（例如在編輯器裡除錯）
        sys.exit(subprocess.call([sys.executable, run, here, *sys.argv[1:]]))
    if not run:
        print("找不到 iPLoT 的「互通」（先在工作坊裝「互通」；模組要放在 iPLoT 資料夾裡或它旁邊），照一般的 python3 iplot.py 跑",
              file=sys.stderr)
# ── 互通 ──

import threading
import unicodedata

import diary
import pages
import photos

try:  # 在 iPLoT 裡一定在；直接 python3 iplot.py（IPLOT_DIRECT=1）時 core 不在 sys.path 上
    from core import scan
    from core.text import SYSTEM_MODULE
except ImportError:
    scan, SYSTEM_MODULE = None, "作業系統"

ICON = "📅"
ENV = "IPLOT_CALENDAR"  # 行事曆自己另開的程序：一開始就從環境變數拿掉，之後從它開的子程序不會繼承
PID = ".pid"
SETTINGS = "設定.json"
HERE = pathlib.Path(__file__).resolve().parent
ICON_FILE = HERE / "icon.png"
RUN_PY = ("modules", "互通", "run.py")
NO_INTEROP = "行事曆要用「互通」另開視窗：到工作坊裝「互通」"
OPENED = "打開行事曆"
ALREADY = "行事曆已經開著"
ALREADY_BEHIND = "行事曆已經開著（在 Dock 上找月曆的圖示）"
CANNOT_WRITE = "存不進去：{why}。字還在，等一下會再試"
UNREADABLE = "讀不到這個檔（不是 UTF-8），沒有覆寫它：{path}"
NOT_FOUND = "找不到「{name}」（可能被改名或刪掉了）"
CANNOT_LAUNCH = "打不開「{name}」：{why}"
NO_PUBLIC = "還沒有打開「公開」的日子"
UNPUBLISHED = "沒有公開的日子了，已經拿掉 發佈/"
UPLOAD_NOTE = "上傳方式還沒設定：把『發佈』裡的東西放到網頁空間"
PANEL = "主控面板"
# macOS 14 起，自己不在最前面的 App 叫別人到最前面會被拒絕；不是 App 的一般 python 程序叫就可以（跟「主控面板」同一段）。
# 被拒絕時交給這一小段在子程序裡叫：argv 是 [-c, lib 的路徑, pid]
HELPER = ("import sys\n"
          "sys.path.insert(0, sys.argv[1])\n"
          "import AppKit\n"
          "app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(int(sys.argv[2]))\n"
          "sys.exit(0 if app is not None and app.activateWithOptions_("
          "AppKit.NSApplicationActivateIgnoringOtherApps) else 1)\n")


def _ps() -> str:
    """所有程序的 pid 與完整指令。一定用 UTF-8 的 locale 叫 ps（從 Dock 開的程式沒有 locale，中文路徑會變成跳脫字）；-ww 不截斷。"""
    try:
        return subprocess.run(["ps", "-axww", "-o", "pid=,command="], capture_output=True, encoding="utf-8",
                              errors="replace", env={**os.environ, "LC_ALL": "en_US.UTF-8"}, check=False).stdout
    except OSError:
        return ""


def activate(pid: int | None, platform: str = sys.platform, run=subprocess.run) -> bool:
    """把 pid（None 是自己）叫到最前面；macOS 以外、或載不進 AppKit 就回 False。照抄「主控面板」的做法。"""
    if platform != "darwin":
        return False
    try:
        import AppKit
    except ImportError:
        return False
    running = AppKit.NSRunningApplication
    app = running.currentApplication() if pid is None else running.runningApplicationWithProcessIdentifier_(pid)
    if app is not None and app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps):
        return True
    lib = str(pathlib.Path(AppKit.__file__).parents[1])
    target = os.getpid() if pid is None else pid
    try:
        done = run([sys.executable, "-c", HELPER, lib, str(target)], stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


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


def running_pid(folder: pathlib.Path, pid_file: pathlib.Path, ps=_ps, me: int | None = None) -> int | None:
    """.pid 記的程序還活著、而且它的指令裡有互通的 run.py 與這個資料夾，才回它的 pid；否則 None（過期）。"""
    me = os.getpid() if me is None else me
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if pid == me:
        return None
    target = unicodedata.normalize("NFC", str(folder))
    for line in unicodedata.normalize("NFC", ps()).splitlines():
        pid_text, _, command = line.strip().partition(" ")
        if pid_text == str(pid):
            return pid if "run.py" in command and target in command else None
    return None


def launch(home: pathlib.Path, folder: pathlib.Path, *, popen=subprocess.Popen, python: str = sys.executable,
           environ=os.environ) -> None:
    """經互通的 run.py 另開一個行事曆的程序（跟這個程序分開；IPLOT_CALENDAR=1 記號）。"""
    popen([python, str(home.joinpath(*RUN_PY)), str(folder)], env={**environ, ENV: "1"}, start_new_session=True,
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_or_focus(app, folder: pathlib.Path, *, environ=os.environ, ps=_ps, popen=subprocess.Popen, activate=activate,
                  platform: str | None = None, me: int | None = None, api=None) -> None:
    """設計第 3.1 節的三步：已經開著 → 叫到最前面；這是行事曆自己另開的程序 → 開頁面；其他 → 另開一個。"""
    platform = platform or sys.platform
    pid = running_pid(folder, folder / PID, ps, me)
    if pid is not None:
        app.log(ALREADY if platform == "darwin" and activate(pid, platform) else ALREADY_BEHIND)
        return
    if environ.get(ENV):
        environ.pop(ENV, None)
        diary.write_text(folder / PID, str(os.getpid()))
        try:
            app.page("行事曆", (folder / "page.html").read_text(encoding="utf-8"), api or Api(app, folder / SETTINGS))
        finally:
            (folder / PID).unlink(missing_ok=True)
        return
    if not app.home.joinpath(*RUN_PY).is_file():
        app.log(NO_INTEROP)
        return
    try:
        launch(app.home, folder, popen=popen, environ=environ)
    except OSError as exc:
        app.log(f"打不開行事曆：{exc}")
        return
    app.log(OPENED)


def _guarded(method):
    """Api 的公開方法：抓同一把鎖（pywebview 每個呼叫各開一條執行緒，app.open／trash 改的是整個程序的狀態）；
    日期格式不對、寫不進去，變成 {"error": 一句話} 給頁面的狀態列，不丟 traceback、不叫 app.log。"""
    @functools.wraps(method)
    def call(self, *args):
        with self._lock:
            try:
                return method(self, *args)
            except ValueError as exc:
                return {"error": str(exc)}
            except OSError as exc:
                return {"error": CANNOT_WRITE.format(why=exc.strerror or exc)}
    return call


class Api:
    """頁面的 JS 用 pywebview.api.<方法> 呼叫的入口（設計第 7 節的 15 個方法）。自己的屬性一律底線開頭（頁面碰不到）；
    頁面傳進來的只有日期、名稱、圖片的檔名與內容，沒有一個方法收路徑；路徑一律是絕對的。"""

    def __init__(self, app, settings_file: pathlib.Path, *, default_root: pathlib.Path | None = None,
                 run=subprocess.run, popen=subprocess.Popen, platform: str = sys.platform, environ=os.environ,
                 today=datetime.date.today, dock_icon=set_dock_icon) -> None:
        self._app, self._settings = app, pathlib.Path(settings_file).absolute()
        self._default_root = (default_root or pathlib.Path.home() / "Documents" / "行事曆").absolute()
        self._run, self._popen, self._platform, self._environ = run, popen, platform, environ
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

    def _scan(self, panel: bool) -> list:
        """最上層（與 ROOTS）現在的模組，每次重掃（設計第 15 節第 7 條）；不含作業系統與行事曆自己。"""
        if scan is None:
            return []
        roots = scan.roots_from_config(self._app.home, self._app.config.roots)
        found = [m for group in scan.find_modules(roots) for m in group.modules]
        skip = {SYSTEM_MODULE, HERE.name} | (set() if panel else {PANEL})
        return [m for m in found if m.name not in skip]

    @_guarded
    def month(self, ym):
        if not self._icon_done:
            self._icon_done = True
            if self._platform == "darwin" and ICON_FILE.exists():
                self._dock_icon(ICON_FILE, self._platform)
        root = self._root()
        return {"ym": ym, "today": self._today().isoformat(), "days": diary.month_summary(root, ym), "folder": str(root)}

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
        mods = self._scan(panel=False)
        everything = [m.name for m in self._scan(panel=True)]
        return {"modules": [{"name": m.name, "icon": m.icon or m.title[:1], "title": m.title} for m in mods],
                "panel": everything.count(PANEL) == 1}

    @_guarded
    def launch(self, name):
        wanted = unicodedata.normalize("NFC", str(name))
        found = [m for m in self._scan(panel=True) if unicodedata.normalize("NFC", m.name) == wanted]
        if len(found) != 1:
            return {"error": NOT_FOUND.format(name=name)}
        run_py = self._app.home.joinpath(*RUN_PY)
        if not run_py.is_file():
            return {"error": NO_INTEROP}
        try:
            self._popen([sys.executable, str(run_py), str(found[0].folder)],
                        env={k: v for k, v in self._environ.items() if k != ENV}, start_new_session=True,
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            return {"error": CANNOT_LAUNCH.format(name=name, why=exc)}
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
                    return {"error": CANNOT_WRITE.format(why=exc.strerror or exc)}
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

