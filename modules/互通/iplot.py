"""互通：任何模組都能在面板外打開——Spotlight、Dock、一行指令、直接 python3 iplot.py。
按這裡會先同步一次捷徑，再顯示現在的狀態；舊模組要能直接執行，在狀態頁按「加上」。
1.0 起只透過 app 與傳進來的 core 碰 iPLoT（不 import 核心，D164）；要 iPLoT 1.0 以上。"""
import ast
import json
import pathlib
import shlex
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

ICON = "🔗"
PROVIDES = {"run.outside": "outside"}  # main.py --run 用彈出式視窗跑模組（D163）
ROLE_NAMES = {"run.outside": "在面板外打開模組的小視窗", "home": "小視窗跑完要回去的地方"}  # 「要允許嗎？」用（D166）
# 用到的角色（D160 R5）：跑完的回去鈕回提供 home 的（行事曆）或面板（main）；碰作業系統的（os.*）不做捷徑
NEEDS = ("home", "main", "os.app_name")
MIN_API = 7  # app.top_modules、app.children_of（D164）
HERE = pathlib.Path(__file__).resolve().parent
NEWER = "互通 1.0 要 iPLoT 1.0 以上：請按「更新」換成新版的 iPLoT。"
# 檔頭的 import 只放標準庫；同一個資料夾的 boot、sync…都在函式裡才 import


def _read(file: pathlib.Path) -> str | None:
    try:
        return file.read_text(encoding="utf-8-sig")
    except (OSError, ValueError):
        return None


def _parses(text: str) -> bool:
    try:
        ast.parse(text)
        return True
    except (SyntaxError, ValueError):
        return False


def candidates(app) -> list:
    """可以加上那一小段的模組（D87）：在 iPLoT 的 modules/ 裡（包括它底下各層）、sync.why_not 回 None、
    還沒有記號、ast 讀得懂。上一層（".."）與 ROOTS 另外加的根目錄底下的一律不算。回 [(ModuleInfo, 一路的名稱)]。"""
    import snippet
    import sync

    levels = sync.levels(app)
    here = next((root for root, level in levels.items() if level == "here"), None)
    found = []
    for info, titles in sync.modules(app):
        if info.root != here or sync.why_not(info, levels) is not None:
            continue
        text = _read(info.file)
        if text is not None and not snippet.has(text) and _parses(text):
            found.append((info, titles))
    return found


def status(app, python: str, folder: pathlib.Path) -> dict:
    """狀態頁要的資料：幾個模組能在面板外打開、幾個能直接執行、可以加上那一小段的（名稱與 iplot.py 的路徑）、
    沒加的與原因、捷徑在哪、指令怎麼寫、上一次同步的問題。"""
    import shortcut
    import snippet
    import sync

    levels = sync.levels(app)
    parent = next((root for root, level in levels.items() if level == "parent"), None)
    can = {info.file for info, _ in candidates(app)}
    total, direct, listed, skipped, top = 0, 0, [], [], []
    for info, titles in sync.modules(app):
        name = " › ".join(titles)
        if info.level != "child" and not sync.is_system(info) and info.folder != HERE:
            top.append(info.name)
        if not sync.is_system(info):
            total += 1
        reason, text = sync.why_not(info, levels), _read(info.file)
        if text is not None and snippet.has(text) and reason != "在 ROOTS 另外加的資料夾裡":
            direct += 1  # 自己帶著那一小段（工作坊裝來的新版、按過「加上」的）
        elif info.file in can:
            listed.append({"name": name, "path": str(info.file)})
        else:
            if info.root == parent:
                reason = "在 iPLoT 外面，不改"
            elif reason is None:
                reason = "讀不到" if text is None else "有語法錯誤"
            skipped.append({"name": name, "reason": reason})
    example = top[0] if top else "<模組名稱>"
    try:
        problems = (folder / sync.ERRORS).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        problems = []
    return {"total": total, "direct": direct, "candidates": listed, "skipped": skipped, "problems": problems,
            "python": python, "shortcuts": str(folder / shortcut.FOLDER), "mac": sys.platform == "darwin",
            "command": shlex.join([python, str(app.home / "main.py"), "--run", example])}


def render(data: dict) -> str:
    """page.html，資料以 JSON 放進 <script type="application/json">；< 寫成 \\u003c，名稱裡有 </script> 也只是字。"""
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return (HERE / "page.html").read_text(encoding="utf-8").replace("__STATUS__", payload)


class Api:
    """狀態頁的 JS 用 pywebview.api.<方法> 呼叫的入口；自己的東西都以底線開頭，攤出去的只有這四個方法。"""

    def __init__(self, app, python: str, folder: pathlib.Path) -> None:
        self._app, self._python, self._folder = app, python, folder

    def reveal(self) -> None:
        """「在 Finder 中顯示」：捷徑的資料夾。"""
        import shortcut
        self._app.reveal(self._folder / shortcut.FOLDER)

    def copy(self, text: str) -> bool:
        """「複製」：把指令放進剪貼簿（macOS 的 pbcopy）；別的系統、或叫不起來回 False，頁面說一句「請自己選取複製」。"""
        if sys.platform != "darwin":
            return False
        try:
            subprocess.run(["pbcopy"], input=str(text).encode(), check=False)
        except OSError:  # 叫不起來：頁面說「請自己選取上面那一行複製」，不是按了沒反應（體驗 7-03）
            return False
        return True

    def resync(self) -> dict:
        """「再同步一次」：同步之後回新的狀態，頁面用 textContent 重畫。"""
        import sync
        sync.sync(self._app, self._python, self._folder)
        return status(self._app, self._python, self._folder)

    def patch(self) -> dict:
        """「加上（N 個檔）」：不收頁面給的任何東西，在這裡重新算一次候選（candidates），每一個用 snippet.add 加上
        （它先存快照）。回補了哪些、問題（一個一句）、新的狀態，頁面用 textContent 重畫。"""
        import snippet
        from boot import plain

        done, problems = [], []
        for info, titles in candidates(self._app):
            name = " › ".join(titles)
            try:
                if snippet.add(info.file, self._app.config.history_keep):
                    done.append(name)
            except SyntaxError:
                problems.append(f"{name}：有語法錯誤，沒補")
            except (OSError, ValueError) as exc:
                problems.append(f"{name}：沒補：{plain(exc)}")
        return {"patched": done, "problems": problems,
                "status": status(self._app, self._python, self._folder)}


def run(app):
    """記下這個 Python、同步一次、打開狀態頁。iPLoT 1.0 每按一次就在自己的程序裡跑（D161），面板不會被卡住。"""
    import boot
    import sync

    if not hasattr(app, "top_modules"):  # 比 1.0 舊的 iPLoT 不看 MIN_API（從工作坊裝到舊版上的）
        return app.log(NEWER)
    boot.remember_python(HERE, sys.executable)
    python = boot.recorded_python(HERE) or sys.executable
    sync.sync(app, python, HERE)
    app.page("互通", render(status(app, python, HERE)), Api(app, python, HERE))
    return None


def outside(app, core, info, files, problem, config_error):
    """角色 run.outside（D163）：main.py --run 把找好的模組（找不到是 None 與 problem 那一句）交過來，
    在彈出式視窗裡跑、跑完同步一次捷徑，回結束碼。沒有 pywebview 丟 ImportError，main.py 改在終端機跑。"""
    import window

    return window.outside(app, core, HERE, info, files, problem, config_error)
