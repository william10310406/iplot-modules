"""互通：任何模組都能在面板外打開——Spotlight、Dock、一行指令、直接 python3 iplot.py。
按這裡會先同步一次捷徑，再顯示現在的狀態；舊模組要能直接執行，在狀態頁按「加上」。"""
import ast
import json
import pathlib
import shlex
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

ICON = "🔗"
HERE = pathlib.Path(__file__).resolve().parent
EXAMPLE = "開工"  # 指令的例子優先用它；沒有就用最上層第一個模組
# 這個檔被直接執行（python3 iplot.py）時，檔頭的 import 在那一小段之前跑，那時候 core 還不在 sys.path 上：
# 所以這裡只 import 標準庫，同一個資料夾的 boot、sync…與 core 都在函式裡才 import


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


def candidates(home: pathlib.Path, config) -> list:
    """可以加上那一小段的模組（D87）：在 iPLoT 的 modules/ 裡（包括它底下各層）、sync.why_not 回 None、
    還沒有記號、ast 讀得懂。上一層（".."）與 ROOTS 另外加的根目錄底下的一律不算。回 [(ModuleInfo, 一路的名稱)]。"""
    import snippet  # noqa: I001  core 在 iPLoT 是第一方、在 iplot-modules 是第三方：兩邊的 isort 要的空行不一樣
    import sync

    from core import scan

    roots = scan.roots_from_config(home, config.roots)
    here = next((r.path for r in roots if r.level == "here"), None)
    found = []
    for info, titles in sync.modules(home, config):
        if info.root != here or sync.why_not(info, roots) is not None:
            continue
        text = _read(info.file)
        if text is not None and not snippet.has(text) and _parses(text):
            found.append((info, titles))
    return found


def status(home: pathlib.Path, config, python: str, folder: pathlib.Path) -> dict:
    """狀態頁要的資料：幾個模組能在面板外打開、幾個能直接執行、可以加上那一小段的（名稱與 iplot.py 的路徑）、
    沒加的與原因、捷徑在哪、指令怎麼寫、上一次同步的問題。"""
    import shortcut  # noqa: I001  同上
    import snippet
    import sync

    from core import scan
    from core.text import SYSTEM_MODULE

    roots = scan.roots_from_config(home, config.roots)
    parent = next((r.path for r in roots if r.level == "parent"), None)
    can = {info.file for info, _ in candidates(home, config)}
    total, direct, listed, skipped, top = 0, 0, [], [], []
    for info, titles in sync.modules(home, config):
        name = " › ".join(titles)
        if info.level != "child":
            top.append(info.name)
        if not (info.level == "here" and info.name == SYSTEM_MODULE):
            total += 1
        reason, text = sync.why_not(info, roots), _read(info.file)
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
    others = [n for n in top if n not in ("互通", SYSTEM_MODULE)]
    example = EXAMPLE if EXAMPLE in top else (others[0] if others else "<模組名稱>")
    try:
        problems = (folder / sync.ERRORS).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        problems = []
    return {"total": total, "direct": direct, "candidates": listed, "skipped": skipped, "problems": problems,
            "python": python, "shortcuts": str(folder / shortcut.FOLDER), "mac": sys.platform == "darwin",
            "command": shlex.join([python, str(folder / "run.py"), example])}


def render(data: dict) -> str:
    """page.html，資料以 JSON 放進 <script type="application/json">；< 寫成 \\u003c，名稱裡有 </script> 也只是字。"""
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return (HERE / "page.html").read_text(encoding="utf-8").replace("__STATUS__", payload)


class Api:
    """狀態頁的 JS 用 pywebview.api.<方法> 呼叫的入口；自己的東西都以底線開頭，攤出去的只有這四個方法。"""

    def __init__(self, app, home: pathlib.Path, config, python: str, folder: pathlib.Path) -> None:
        self._app, self._home, self._config, self._python, self._folder = app, home, config, python, folder

    def reveal(self) -> None:
        """「在 Finder 中顯示」：捷徑的資料夾。"""
        import shortcut
        self._app.reveal(self._folder / shortcut.FOLDER)

    def copy(self, text: str) -> bool:
        """「複製」：把指令放進剪貼簿（macOS 的 pbcopy）；別的系統回 False，頁面說一句「請自己選取複製」。"""
        if sys.platform != "darwin":
            return False
        subprocess.run(["pbcopy"], input=str(text).encode(), check=False)
        return True

    def resync(self) -> dict:
        """「再同步一次」：同步之後回新的狀態，頁面用 textContent 重畫。"""
        import sync
        sync.sync(self._home, self._config, self._python, self._folder)
        return status(self._home, self._config, self._python, self._folder)

    def patch(self) -> dict:
        """「加上（N 個檔）」：不收頁面給的任何東西，在這裡重新算一次候選（candidates），每一個用 snippet.add 加上
        （它先存快照）。回補了哪些、問題（一個一句）、新的狀態，頁面用 textContent 重畫。"""
        import snippet

        done, problems = [], []
        for info, titles in candidates(self._home, self._config):
            name = " › ".join(titles)
            try:
                if snippet.add(info.file, self._config.history_keep):
                    done.append(name)
            except SyntaxError:
                problems.append(f"{name}：有語法錯誤，沒補")
            except (OSError, ValueError) as exc:
                problems.append(f"{name}：沒補：{exc}")
        return {"patched": done, "problems": problems,
                "status": status(self._home, self._config, self._python, self._folder)}


def run(app):
    """記下面板用的 Python、同步一次、打開狀態頁。"""
    import boot
    import sync

    boot.remember_python(HERE, sys.executable)
    python = boot.recorded_python(HERE) or sys.executable
    sync.sync(app.home, app.config, python, HERE)
    data = status(app.home, app.config, python, HERE)
    app.page("互通", render(data), Api(app, app.home, app.config, python, HERE))
