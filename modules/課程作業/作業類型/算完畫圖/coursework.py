"""作業的殼（docs/09_作業規範.md v2）：作業檔第二行的 ensure、最後一行的 main，加上 python coursework.py --check <檔>。
學生拿到的學生包裡，這個檔跟作業檔放在一起；老師的作業資料夾裡沒有它，iPLoT 另開程序時用 PYTHONPATH 指過來。

作業檔在 ensure 之前就 import coursework，所以這個檔頂層只 import 標準庫；numpy、matplotlib 在用到的函式裡才 import。
沒裝 python.org 的 Mac 打 python3 會是 Apple 的 3.9：這個檔的頂層 3.9 也讀得懂（不用 3.10 才有的語法），
ensure 第一件事檢查版本，說一句話就結束，不是一段 traceback。
從 modules/科學計算/hk_page.py 複製過來改的（那個檔不動）；pip 名對照表、import 掃描各自一份。
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import importlib.metadata
import os
import platform
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

NO_INSTALL = "CW_NO_INSTALL"  # 設了就不跑 pip，缺了只報（測試用）
FROM_IPLOT = "CW_FROM_IPLOT"  # iPLoT 另開的子程序都帶著：不自動補 REQUIRES、不問 case、文字開視窗
REEXEC = "CW_REEXEC"  # ensure 用 .venv 重跑時帶著：重跑的那一個還是不在 venv 裡就不再重跑（D144）
MIN_PYTHON = (3, 10)
# README 與錯誤句子都從這幾個常數來（學生包的 README 打包時代換進去，測試核對）
VERSION = "python3 --version"
MAKE_VENV = "python3 -m venv .venv"
RUN = "python3 {file}"
WIN_VERSION = "py --version"
WIN_MAKE_VENV = "py -m venv .venv"
REMAKE_VENV = "python3 -m venv --clear .venv"
WIN_REMAKE_VENV = "py -m venv --clear .venv"
WIN_RUN = "py {file}"
TOO_OLD = "這份作業要 Python 3.10 以上，現在是 {have}。照 README 第 1 步裝 python.org 的 Python，再用 python3 跑一次。"
OLD_VENV = (f"這個資料夾的 .venv 是用舊的 Python 建的。先照 README 第 3 步確認版本，再打 {REMAKE_VENV} 重建"
            f"（Windows 是 {WIN_REMAKE_VENV}），然後重跑。")  # D143
BROKEN_VENV = (f"這個資料夾的 .venv 壞了（裡面的 Python 認不出自己在 .venv 裡）。打 {REMAKE_VENV} 重建"
               f"（Windows 是 {WIN_REMAKE_VENV}），然後重跑。")  # D144
MARK = "課程.py"  # 老師的課程資料夾（跟框架的 course.MARK 同一個名字）
NAME_RE = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"  # pip 名只接這些字元，不經 shell
PIP_NAMES = {"cv2": "opencv-python", "PIL": "Pillow", "sklearn": "scikit-learn", "kan": "pykan", "mlx_lm": "mlx-lm",
             "pywt": "PyWavelets", "yaml": "PyYAML", "bs4": "beautifulsoup4", "skimage": "scikit-image",
             "dateutil": "python-dateutil", "mpl_toolkits": "matplotlib", "pylab": "matplotlib"}
APPLE_SILICON_ONLY = ("mlx-lm",)
NOT_PACKAGES = {"coursework"}  # 殼自己：跟作業檔放在一起，不是 pip 套件


# ── 套件 ──


def _normal(dist: str) -> str:
    return re.sub(r"[-_.]+", "-", dist).lower()


def imports_of(file: Path) -> set[str]:
    """檔裡所有 import 的頂層名字（連函式裡的，ast.walk 整棵樹；相對 import 不算）；讀不懂回空集合。"""
    try:
        tree = ast.parse(Path(file).read_text(encoding="utf-8-sig"))
    except (SyntaxError, ValueError, OSError):
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def third_party(names: set[str], folder: Path) -> set[str]:
    """扣掉標準庫、__future__、coursework、folder 裡同名的 .py 或資料夾。"""
    try:
        siblings = {p.stem if p.suffix == ".py" else p.name for p in Path(folder).iterdir()}
    except OSError:
        siblings = set()
    return set(names) - set(sys.stdlib_module_names) - {"__future__"} - NOT_PACKAGES - siblings


def dist_for(name: str) -> str:
    """import 名 → pip 名：裝了的照它自己的 metadata，沒裝的查對照表，都沒有就同名。"""
    found = importlib.metadata.packages_distributions().get(name)
    return found[0] if found else PIP_NAMES.get(name, name)


def _covered(requires: list[str]) -> set[str]:
    """REQUIRES 裡那些套件提供的 import 名（裝了的照 metadata；沒裝的當作提供同名的，再加對照表反查）。"""
    wanted = {_normal(r) for r in requires}
    names = {imp for imp, dists in importlib.metadata.packages_distributions().items()
             if any(_normal(d) in wanted for d in dists)}
    names |= {imp for imp, pip in PIP_NAMES.items() if _normal(pip) in wanted}
    names |= {r for r in requires} | {_normal(r).replace("-", "_") for r in requires}
    return names


def _forgotten(file: Path, requires: list[str]) -> list[str]:
    """檔裡 import 了、REQUIRES 沒寫的 pip 名（照 import 名排序，不重複）。"""
    file = Path(file)
    names = sorted(third_party(imports_of(file), file.parent) - _covered(requires))
    out, have = [], {_normal(r) for r in requires}
    for dist in map(dist_for, names):
        if _normal(dist) not in have:
            have.add(_normal(dist))
            out.append(dist)
    return out


def requires_line(source: str) -> tuple[int, int, str] | None:
    """頂層 REQUIRES = [...] 那一行：（行號, 結束行號, 那一行 list 後面的字（註解，含前面的空白）或 ""）。
    寫成好幾行的 list、不是 list 字面值、沒有 REQUIRES：回 None。"""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "REQUIRES" and isinstance(node.value, ast.List)):
            if node.lineno != node.end_lineno:
                return None
            # 行號照 ast 算（只認 \n、\r、\r\n；str.splitlines 還會在 \x0c、U+2028 斷行），col_offset 是 UTF-8 的 byte
            line = source.encode("utf-8").splitlines()[node.lineno - 1]
            return node.lineno, node.end_lineno, line[node.value.end_col_offset:].decode("utf-8")
    return None


def fill_requires(file: Path, extra: list[str]) -> bool:
    """把 extra 補進 file 裡 REQUIRES = [...] 那一行：雙引號、原來的順序在前、註解留著；其他行一個 byte 都不動。
    回有沒有改。寫成好幾行的 REQUIRES 不改，印一句叫人手動加。"""
    file = Path(file)
    data = file.read_bytes()
    bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
    source = data[len(bom):].decode("utf-8")
    found = requires_line(source)
    if found is None:
        if extra:
            print(f"REQUIRES 寫成好幾行（或不是一個 list），沒有自動補：請手動加 {'、'.join(extra)}")
        return False
    lineno, _, comment = found
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "REQUIRES")
    names = list(ast.literal_eval(node.value))
    have = {_normal(n) for n in names}
    for name in extra:
        if _normal(name) not in have:
            have.add(_normal(name))
            names.append(name)
    if len(names) == len(ast.literal_eval(node.value)):
        return False
    lines = data[len(bom):].splitlines(keepends=True)
    old = lines[lineno - 1]
    ending = old[len(old.rstrip(b"\r\n")):]
    lines[lineno - 1] = ("REQUIRES = [" + ", ".join(f'"{n}"' for n in names) + "]" + comment).encode("utf-8") + ending
    try:
        file.write_bytes(bom + b"".join(lines))
    except OSError:
        print(f"這個檔寫不進去，沒有自動補：請手動把 {'、'.join(extra)} 加進 REQUIRES")
        return False
    return True


def missing(requires: list[str]) -> list[str]:
    """requires 裡這個 Python 還沒裝的（不重複、照原順序）。"""
    out = []
    for name in requires:
        try:
            importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            if _normal(name) not in map(_normal, out):
                out.append(name)
    return out



def _venv_python(folder: Path) -> Path | None:
    """folder/.venv 的 Python；不在就 None。不 resolve：venv 的 python 是指到基底 Python 的連結。"""
    python = Path(folder) / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return python if python.is_file() else None


def venv_version(python: Path) -> tuple[int, ...] | None:
    """python 所在的 .venv 是用哪一版 Python 建的：讀 .venv/pyvenv.cfg 的 version（venv）或 version_info（uv）。
    不叫那個 Python。讀不到、讀不懂回 None。"""
    try:
        lines = (Path(python).parents[1] / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, IndexError):
        return None
    for line in lines:
        key, _, value = line.partition("=")
        if key.strip() in ("version", "version_info"):
            found = re.match(r"\s*(\d+)\.(\d+)", value)
            return (int(found.group(1)), int(found.group(2))) if found else None
    return None


def find_venv(file: Path) -> Path | None:
    """先看作業檔旁邊的 .venv（學生包），再往上找有 課程.py 的資料夾的 .venv（老師的課）。"""
    folder = Path(file).resolve().parent
    found = _venv_python(folder)
    if found:
        return found
    course = next((p for p in (folder, *folder.parents) if (p / MARK).is_file()), None)
    return _venv_python(course) if course else None


def _no_venv(need: list[str], file: Path) -> str:
    """不在 venv 裡、旁邊也沒有 .venv：照 README 的兩行做（跟 README 同一份常數）。"""
    name = Path(file).name
    return (f"缺 {'、'.join(need)}。這份作業的套件要裝在作業旁邊的 .venv 裡（不裝進電腦本身的 Python）。"
            "照 README 做：在這個資料夾打開終端機，打這兩行（第一行只要做一次）：\n"
            f"    {MAKE_VENV}\n"
            f"    {RUN.format(file=name)}\n"
            "Windows（未經實機驗證）：\n"
            f"    {WIN_MAKE_VENV}\n"
            f"    {WIN_RUN.format(file=name)}")


def ensure(requires: list[str], file: str, popen=subprocess.Popen, argv: list[str] | None = None,
           version=sys.version_info) -> None:
    """作業檔第二行：缺的套件在這一行裝好，裝完才往下 import。
    1. Python 不到 3.10：說一句話、結束碼 1。
    2. 不在 venv 裡（系統的 Python）：找得到 .venv（作業旁邊，或上面的課程資料夾）就用它重跑同一個檔、
       帶原本的參數、結束碼照它的（先重跑，不先查缺什麼；最多重跑一次）；找不到就只看缺不缺，缺了印 README 的兩行、結束碼 1，絕不叫 pip。
    3. 在 venv 裡：學生自己跑自己的檔時，先把 import 了、REQUIRES 沒寫的補進 REQUIRES 那一行；缺的裝進這個 venv。"""
    if tuple(version[:2]) < MIN_PYTHON:
        print(TOO_OLD.format(have=".".join(str(v) for v in version[:3])))
        sys.exit(1)
    requires = [requires] if isinstance(requires, str) else list(requires)
    argv = list(sys.argv if argv is None else argv)
    if sys.prefix == sys.base_prefix:
        python = find_venv(Path(file))
        if python is not None and os.environ.get(REEXEC):  # D144：已經用 .venv 重跑過，還是不在 venv 裡
            print(BROKEN_VENV)
            sys.exit(1)
        if python is not None:
            built = venv_version(python)
            if built is not None and built < MIN_PYTHON:  # D143：舊 Python 建的 .venv 不切進去，不然學生看到的是別的錯
                print(OLD_VENV)
                sys.exit(1)
            sys.exit(popen([str(python), str(Path(file).resolve()), *argv[1:]],
                           cwd=str(Path(file).resolve().parent), env={**os.environ, REEXEC: "1"}).wait())
        need = missing(requires)
        if need:  # D138：跟版本那句一樣說完就結束，學生看到的不是 traceback
            print(_no_venv(need, Path(file)))
            sys.exit(1)
        return
    extra = []
    own = bool(argv) and Path(file).resolve() == Path(argv[0]).resolve()
    if own and not os.environ.get(FROM_IPLOT):
        extra = _forgotten(Path(file), requires)
        if extra and fill_requires(Path(file), extra):
            print(f"已把 {'、'.join(extra)} 加進 REQUIRES")
    need = missing(requires + extra)
    if not need:
        return
    if os.environ.get(NO_INSTALL):
        raise RuntimeError(f"缺 {'、'.join(need)}；{NO_INSTALL} 設著，不裝")
    bad = [n for n in need if not re.fullmatch(NAME_RE, n)]  # fullmatch：$ 會放過結尾的換行
    if bad:
        raise RuntimeError(f"套件名字不合法：{'、'.join(bad)}")
    arm_mac = sys.platform == "darwin" and platform.machine() == "arm64"
    only = [n for n in need if _normal(n) in {_normal(x) for x in APPLE_SILICON_ONLY}]
    if only and not arm_mac:
        raise RuntimeError(f"{'、'.join(only)} 只有 Apple Silicon 的 Mac 裝得了：這份作業要在 Apple Silicon 的 Mac 上跑")
    print(f"在裝 {'、'.join(need)}（第一次要幾分鐘）…")
    argv_pip = [sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check", *need]
    if popen(argv_pip).wait() != 0:
        raise RuntimeError(f"裝不了 {'、'.join(need)}：在終端機 {sys.executable} -m pip install {' '.join(need)}")
    importlib.invalidate_caches()


# ── 跑：單獨跑是終端機選 case＋matplotlib 的視窗；iPLoT 另開的程序帶 --case 或 --all，文字也開視窗 ──


def _choose(cases: list[str], hw: dict, argv: list[str], ask, out) -> list[str] | None:
    """要跑哪幾個 case：--case <名> 直接指定、--all 全部；不然列出來問，0 是全部。選不了印一句、回 None。"""
    if "--all" in argv:
        return cases
    if "--case" in argv:
        i = argv.index("--case")
        name = argv[i + 1] if i + 1 < len(argv) else ""
        if name in cases:
            return [name]
        print(f"沒有 {name}：有 {'、'.join(cases)}", file=out)
        return None
    for n, name in enumerate(cases, 1):
        print(f"{n}) {name}  {hw['cases'][name].get('label', '')}", file=out)
    print("0) 全部", file=out)
    try:
        answer = ask("選：").strip()
    except EOFError:
        answer = ""
    number = int(answer) if answer.isdecimal() else -1  # ①、² 這種 isdigit 但 int() 不收的，當作沒選
    if number == 0:
        return cases
    if 1 <= number <= len(cases):
        return [cases[number - 1]]
    print(f"要選 0 到 {len(cases)} 之間的數字", file=out)
    return None


TEXT_FONTS = ("PingFang TC", "Heiti TC", "Microsoft JhengHei", "Noto Sans CJK TC", "Arial Unicode MS")


def _fonts() -> list[str]:
    """這台電腦裝了的中文字型，加 DejaVu Sans（只列裝了的：不然 matplotlib 一直警告）。"""
    from matplotlib import font_manager

    installed = {f.name for f in font_manager.fontManager.ttflist}
    return [f for f in TEXT_FONTS if f in installed] + ["DejaVu Sans"]


def _show_text(title: str, text: str, show_fn=None) -> None:
    """把文字放進一個 matplotlib 視窗（iPLoT 另開的程序沒有終端機，印出來沒人看得到）。"""
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(7, 6))
    try:
        with contextlib.suppress(AttributeError):
            fig.canvas.manager.set_window_title(f"{title}（文字）")
        fig.text(0.03, 0.97, text, va="top", ha="left", fontfamily=_fonts(), fontsize=11, wrap=True)
        (show_fn or plt.show)()
    finally:
        plt.close(fig)


HANDED_OVER = "[coursework] 視窗開不了，下面這段請 iPLoT 放進訊息區"  # D145：跟 SHOWN_MARK 一樣印到 stderr
HANDED_OVER_END = "[coursework] 放進訊息區的到這裡"


def _show_or_hand_over(title: str, text: str, show_fn=None) -> None:
    """開文字視窗；開不了（matplotlib 沒裝、壞了）就把同一段印到 stderr，夾在 HANDED_OVER 與 HANDED_OVER_END
    之間，iPLoT 的框架讀到就放進面板的訊息區（D145）。"""
    try:
        _show_text(title, text, show_fn)
    except Exception as exc:  # noqa: BLE001  視窗怎麼開不了都一樣：交給 iPLoT
        lines = [HANDED_OVER, f"{title}：視窗開不了（{exc}），內容放在這裡：", *text.splitlines(), HANDED_OVER_END]
        print("\n".join(lines), file=sys.stderr, flush=True)


def _header(hw: dict) -> list[str]:
    """NAME、NOTE（有才有）、DOCS（每個一行「顯示名：網址」）。"""
    lines = [hw["name"]]
    if hw.get("note"):
        lines += str(hw["note"]).splitlines()
    lines += [f"{title}：{url}" for title, url in hw.get("docs") or []]
    return lines


SHOWN_MARK = "[coursework] 錯誤已經開了視窗"  # iPLoT 另開時印到 stderr 的一行；框架看到它就不再開錯誤視窗（D142）


def main(hw: dict, argv: list[str] | None = None, ask=input, out=None, show_fn=None) -> int:
    """作業檔最後一行：先印 NAME、NOTE、DOCS；選 case（--case <名>、--all 不問）；每個 case 先 compute，
    印 text 與 stats，有 draw 就開一個 matplotlib 視窗（關掉才下一個）。iPLoT 另開的（CW_FROM_IPLOT）
    文字也開一個視窗，第一個的最前面放 NAME、NOTE、DOCS；視窗開不了就交給 iPLoT 的訊息區（D145）。
    一個 case 出錯印 traceback、接著跑下一個。
    結束碼：都好 0、有 case 出錯 1、選不了 2。"""
    out = out or sys.stdout
    with contextlib.suppress(AttributeError, ValueError):
        out.reconfigure(encoding="utf-8")
    header = _header(hw)
    for line in header:
        print(line, file=out)
    cases = list(hw["cases"])
    chosen = _choose(cases, hw, list(sys.argv[1:] if argv is None else argv), ask, out)
    if chosen is None:
        return 2
    failed, header_shown, marked = False, False, False
    for i, case in enumerate(chosen):
        print(f"── {case} ──", file=out)
        title = f"{hw['name']} — {case}"
        try:
            run = hw["compute"](case)
            lines = [run["text"]] if run.get("text") else []
            lines += [f"{key}：{value}" for key, value in (hw.get("stats") or (lambda r: []))(run)]
            for line in lines:
                print(line, file=out)
            if os.environ.get(FROM_IPLOT):  # 沒有終端機：第一個 case 連同 NAME、NOTE、DOCS 開文字視窗
                shown = (header + [""] + lines) if i == 0 else lines
                if shown:
                    header_shown = header_shown or i == 0
                    _show_or_hand_over(title, "\n".join(shown), show_fn)
            if hw.get("draw"):
                import matplotlib
                import matplotlib.pyplot as plt  # 只有要畫圖時才 import（頂層只 import 標準庫）

                matplotlib.rcParams["font.sans-serif"] = _fonts()
                fig = plt.figure(figsize=(7, 6))
                try:
                    with contextlib.suppress(AttributeError):
                        fig.canvas.manager.set_window_title(title)
                    ani = hw["draw"](fig, run)  # 動畫要抓著，不然一回來就被回收、畫面不動
                    (show_fn or plt.show)()
                    del ani
                finally:
                    plt.close(fig)  # draw 畫到一半壞了也關掉，不然下一個 case 的視窗會一起跳出來
        except Exception:  # noqa: BLE001  作業的 compute／draw 怎麼壞都印出來，接著跑下一個 case
            error = traceback.format_exc()
            print(error, end="", file=out)
            failed = True
            if os.environ.get(FROM_IPLOT):  # 沒有終端機：traceback 也開文字視窗，不然在 iPLoT 裡看不到
                shown = header + [""] if i == 0 and not header_shown else []
                header_shown = True
                _show_or_hand_over(title, "\n".join(shown + [f"{case} 出錯了：", error.rstrip()]), show_fn)
                if not marked:  # 告訴另開這個程序的框架：錯誤已經給人看了（視窗或訊息區），不用再開一個（D142）
                    print(SHOWN_MARK, file=sys.stderr, flush=True)
                    marked = True
    return 1 if failed else 0


# ── --check：docs/09 第 3 節的規則（表與 RULES 是同一份清單，測試核對）；只用 ast，不執行作業檔 ──

RULES = {
    "R1": "第一行是 REQUIRES = [...]，字串 list 的字面值",
    "R2": "第二行是 import coursework; coursework.ensure(REQUIRES, __file__)",
    "R3": "NAME 是字串",
    "R4": "DOCS 是 [(顯示名, 網址), …]，網址 http://、https:// 開頭",
    "R5": "NOTE 是字串",
    "R6": '有 DATA 的話，剛好是 Path(__file__).resolve().parent / "<代號>Space"，那個資料夾在',
    "R7": "CASES 是 dict 字面值：鍵是字串、值是 dict(…) 或 {…}、label 是字串",
    "R8": "compute 是頂層 def，一個參數",
    "R9": "draw 是頂層 def、兩個參數，或 draw = None",
    "R10": "stats 是頂層 def、一個參數，或 stats = None",
    "R11": "固定尾段三行照樣",
    "R12": ("用到的第三方套件都寫在 REQUIRES：import 名在對照表裡（cv2 → opencv-python 這種）而 REQUIRES 沒寫那個 pip 名才擋；"
            "不在對照表、也不是標準函式庫的只警告（打包也不擋），請老師確認 REQUIRES 有寫它的 pip 名"),
    "R13": "不 import tkinter、_tkinter、turtle（含子模組）",
    "R14": "不用 matplotlib 的 Tk 後端：backend_tkagg、backend_tk、FigureCanvasTkAgg、NavigationToolbar2Tk",
    "R15": '不換後端：matplotlib.use(…)、rcParams["backend"]',
    "R16": "不用 pyplot 開圖或拿圖：show、figure、subplots、subplot、gcf、gca、axes",
    "R17": "不讀鍵盤：input()、sys.stdin",
    "R18": "不自己開程式或網頁：os.system、os.popen、os.startfile、os.exec*、os.spawn*、subprocess、webbrowser",
    "R19": "不 os.chdir",
    "R20": "不寫絕對路徑",
    "R21": "不用舊格式的全域 t2026fscHOMEDIR、LF、LF_subWIN",
    "R22": "case 之間不共用狀態（不用 global；nonlocal 可以，draw 的 update 用它記狀態）",
    "R23": "寫檔只寫在 DATA 底下",
    "R24": "不要只指定一個字型",
    "R25": "不定義 iPLoT 的名字：run、on_files、on_error、TITLE、ICON",
    "R26": "不結束整個程式：sys.exit、exit、quit、os._exit",
    "R27": "檔是 UTF-8、語法對",
    "R28": ("作業檔在 Python 3.9 也解析得了（學生的 3.9 才看得到殼的版本提示，而不是語法錯誤）；"
            "用 ast.parse(…, feature_version=(3, 9)) 查，這是盡力而為，不保證抓到所有 3.10 以後的語法"),
}
ENSURE_LINE = "import coursework; coursework.ensure(REQUIRES, __file__)"
TAIL_KEYS = {"name": "NAME", "docs": "DOCS", "note": "NOTE", "cases": "CASES", "compute": "compute", "draw": "draw",
             "stats": "stats", "file": "__file__"}
TAIL_IF = 'if __name__ == "__main__":'
TAIL_RAISE = "raise SystemExit(coursework.main(HOMEWORK))"
NO_IMPORT = {"R13": ("tkinter", "_tkinter", "turtle"), "R18": ("subprocess", "webbrowser")}
TK_BACKEND = "matplotlib.backends.backend_tk"
TK_NAMES = ("FigureCanvasTkAgg", "NavigationToolbar2Tk")
PYPLOT_OPEN = ("show", "figure", "subplots", "subplot", "gcf", "gca", "axes")
RUN_CALLS = ("os.system", "os.popen", "os.startfile")
RUN_PREFIXES = ("os.exec", "os.spawn")
EXIT_CALLS = ("sys.exit", "exit", "quit", "os._exit")
OLD_GLOBALS = ("t2026fscHOMEDIR", "LF", "LF_subWIN")
IPLOT_NAMES = ("run", "on_files", "on_error", "TITLE", "ICON")
FONT_KEYS = ("font.family", "font.sans-serif")
# /x/、~/、X:\、X:/、\\ 開頭；"/" 這種一個字元的分隔符、"km/s" 不算
ABSOLUTE_RE = r"^(/[^/]+/|~/|[A-Za-z]:[\\/]|\\\\)"


@dataclass
class Problem:
    rule: str  # "R1"…"R28"
    line: int | None  # 第幾行；整個檔的問題（不是 UTF-8、讀不到）是 None
    text: str
    block: bool = True  # False：只警告，「檢查與打包」也不擋（D141：R12 不在對照表的 import）


def _code(line: str) -> str:
    """去註解、去頭尾空白（# 在字串裡的情形尾段與第二行沒有，不管）。"""
    return line.split("#", 1)[0].strip()


def _top(tree: ast.Module, name: str) -> ast.stmt | None:
    """頂層最後一個定義 name 的敘述（def 或 name = …）。"""
    found = None
    for node in tree.body:
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name) or (
                isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)):
            found = node
    return found


def _literal(node: ast.AST | None):
    try:
        return ast.literal_eval(node) if node is not None else None
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None


def _str_assign(tree: ast.Module, name: str, rule: str, what: str) -> list[Problem]:
    node = _top(tree, name)
    if node is None:
        return [Problem(rule, None, f"少了 {name}：{what}")]
    ok = isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    return [] if ok else [Problem(rule, node.lineno, f"{name} 要是字串，像 {what}")]


def _positional(node: ast.FunctionDef) -> int | None:
    """def 的位置參數個數；有 *args、**kw、只能用名字給的參數就回 None（殼只用位置給）。"""
    a = node.args
    if a.vararg or a.kwarg or a.kwonlyargs:
        return None
    return len(a.posonlyargs) + len(a.args)


def _function(tree: ast.Module, name: str, count: int, rule: str, may_be_none: bool) -> list[Problem]:
    node = _top(tree, name)
    alt = f"，或寫一行 {name} = None" if may_be_none else ""
    if node is None:
        return [Problem(rule, None, f"少了 {name}：要是頂層的 def，{count} 個參數{alt}")]
    if isinstance(node, ast.FunctionDef) and _positional(node) == count:
        return []
    if may_be_none and isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and node.value.value is None:
        return []
    return [Problem(rule, node.lineno, f"{name} 要是頂層的 def，剛好 {count} 個參數{alt}")]


def _requires(tree: ast.Module, lines: list[str]) -> tuple[list[Problem], list[str] | None]:
    """R1；回（問題, REQUIRES 裡的字串；不是字面值就 None，R12 不看）。"""
    node = tree.body[0] if tree.body else None
    is_req = (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
              and node.targets[0].id == "REQUIRES")
    other = _top(tree, "REQUIRES")
    value = _literal(other.value) if isinstance(other, ast.Assign) else None
    names = [v for v in value if isinstance(v, str)] if isinstance(value, (list, tuple)) else None
    want = '第一行要是 REQUIRES = ["numpy", "matplotlib"] 這樣：一行寫完的 list，裡面都是字串'
    if not (is_req and node.lineno == 1 and node.end_lineno == 1):
        return [Problem("R1", other.lineno if other else 1, want)], names
    if not (isinstance(node.value, ast.List) and isinstance(value, list) and all(isinstance(v, str) for v in value)):
        return [Problem("R1", 1, want)], names
    return [], names


def _data(tree: ast.Module, file: Path) -> list[Problem]:
    node = _top(tree, "DATA")
    if node is None:
        return []
    space = f"{Path(file).stem}Space"
    want = f'Path(__file__).resolve().parent / "{space}"'
    if not (isinstance(node, ast.Assign)
            and ast.dump(node.value) == ast.dump(ast.parse(want, mode="eval").body)):
        return [Problem("R6", node.lineno, f"DATA 要剛好寫成 DATA = {want}")]
    if not (Path(file).parent / space).is_dir():
        return [Problem("R6", node.lineno, f"DATA 指的資料夾 {space} 不在作業檔旁邊")]
    return []


def _cases(tree: ast.Module) -> list[Problem]:
    node = _top(tree, "CASES")
    if node is None:
        return [Problem("R7", None, '少了 CASES：要寫成 CASES = {"case-1": dict(…, label="…"), …}')]
    if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)):
        return [Problem("R7", node.lineno, 'CASES 要是 {"case-1": dict(…), …} 這樣的字面值')]
    out = []
    for key, value in zip(node.value.keys, node.value.values, strict=True):
        line = (key or value).lineno
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            out.append(Problem("R7", line, "CASES 的鍵要是字串常數（在 iPLoT 裡選 case 要靠它）"))
            continue
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "dict":
            label = next((k.value for k in value.keywords if k.arg == "label"), None)
        elif isinstance(value, ast.Dict):
            label = next((v for k, v in zip(value.keys, value.values, strict=True)
                          if isinstance(k, ast.Constant) and k.value == "label"), None)
        else:
            out.append(Problem("R7", line, f"CASES 的 {key.value} 要是 dict(…) 或 {{…}}"))
            continue
        if label is not None and not (isinstance(label, ast.Constant) and isinstance(label.value, str)):
            out.append(Problem("R7", label.lineno, f"CASES 的 {key.value} 的 label 要是字串"))
    return out


def _docs(tree: ast.Module) -> list[Problem]:
    node = _top(tree, "DOCS")
    want = '[("顯示名", "https://…"), …]，沒有就寫 DOCS = []'
    if node is None:
        return [Problem("R4", None, f"少了 DOCS：{want}")]
    if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.List):
        return [Problem("R4", node.lineno, f"DOCS 要寫成 {want}")]
    for item in node.value.elts:
        pair = _literal(item) if isinstance(item, ast.Tuple) else None
        if not (isinstance(pair, tuple) and len(pair) == 2 and all(isinstance(v, str) for v in pair)):
            return [Problem("R4", item.lineno, "DOCS 的每一個要是（顯示名, 網址）兩個字串的 tuple")]
        if not pair[1].startswith(("http://", "https://")):
            return [Problem("R4", item.lineno, f"DOCS 的網址要 http:// 或 https:// 開頭：{pair[1]}")]
    return []


def _tail(tree: ast.Module, lines: list[str]) -> list[Problem]:
    """R11：最後三行是 HOMEWORK = dict(…八個鍵…)、if __name__ == "__main__":、raise SystemExit(coursework.main(HOMEWORK))。"""
    end = len(lines)
    body = tree.body
    hw, last = (body[-2], body[-1]) if len(body) >= 2 else (None, None)
    ok_hw = (isinstance(hw, ast.Assign) and len(hw.targets) == 1 and isinstance(hw.targets[0], ast.Name)
             and hw.targets[0].id == "HOMEWORK" and isinstance(hw.value, ast.Call)
             and isinstance(hw.value.func, ast.Name) and hw.value.func.id == "dict" and not hw.value.args)
    if not ok_hw:
        return [Problem("R11", hw.lineno if hw else end, "倒數第三行要是固定尾段的 HOMEWORK = dict(…)，照 docs/09 第 1 節")]
    got = {k.arg: k.value.id if isinstance(k.value, ast.Name) else None for k in hw.value.keywords}
    if got != TAIL_KEYS:
        diff = sorted(set(TAIL_KEYS) ^ set(got) | {k for k in TAIL_KEYS if k in got and got[k] != TAIL_KEYS[k]})
        return [Problem("R11", hw.lineno, f"HOMEWORK = dict(…) 被改了（{'、'.join(diff)}）：照 docs/09 第 1 節那一行")]
    if not (isinstance(last, ast.If) and _code(lines[last.lineno - 1]) == TAIL_IF):
        return [Problem("R11", last.lineno, f"倒數第二行要是 {TAIL_IF}")]
    inner = last.body[0]
    if not (len(last.body) == 1 and not last.orelse and inner.lineno == inner.end_lineno == last.end_lineno
            and _code(lines[inner.lineno - 1]) == TAIL_RAISE):
        return [Problem("R11", inner.lineno, f"最後一行要是 {TAIL_RAISE}")]
    return []


def _import_lines(tree: ast.Module) -> list[tuple[str, int]]:
    """（頂層名字, 行號），連函式裡的；相對 import 不算。"""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(a.name.split(".")[0], node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.append((node.module.split(".")[0], node.lineno))
    return sorted(out, key=lambda x: x[1])


def _forgotten_lines(tree: ast.Module, file: Path, requires: list[str]) -> list[Problem]:
    """R12（D141）：import 了、REQUIRES 沒寫的；每個名字報一次，在第一個 import 它的那一行。
    import 名在對照表（PIP_NAMES）裡：知道 pip 名，REQUIRES 沒寫就擋。
    不在對照表：pip 名可能跟 import 名不同（import Crypto 是 pycryptodome），只警告、打包不擋。"""
    left = third_party({n for n, _ in _import_lines(tree)}, Path(file).parent) - _covered(requires)
    out, seen = [], {_normal(r) for r in requires}
    for name, line in _import_lines(tree):
        if name not in left or name in seen:
            continue
        seen.add(name)
        if name in PIP_NAMES:
            if _normal(PIP_NAMES[name]) not in seen:
                seen.add(_normal(PIP_NAMES[name]))
                out.append(Problem("R12", line, f"import 了 {name}，REQUIRES 沒寫：加上 \"{PIP_NAMES[name]}\""))
        else:
            out.append(Problem("R12", line, f"import 了 {name}：確認 REQUIRES 有寫它的 pip 名（常常跟 import 名一樣，"
                                            f"寫 \"{name}\"；不一樣的照套件的說明寫）", block=False))
    return out


def _newer_line(tree: ast.Module, exc: SyntaxError) -> int | None:
    """R28 的行號：檔裡有 match／except* 就報第一個的那一行（例外的行號常落在敘述結尾之後），不然照例外。"""
    newer = tuple(getattr(ast, n) for n in ("Match", "TryStar") if hasattr(ast, n))
    return min((n.lineno for n in ast.walk(tree) if newer and isinstance(n, newer)), default=exc.lineno)


def _aliases(tree: ast.Module) -> dict[str, str]:
    """檔裡的 import 綁了哪些名字、各指到什麼（plt → matplotlib.pyplot、figure → matplotlib.pyplot.figure）。"""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    out[a.asname] = a.name
                else:
                    top = a.name.split(".")[0]
                    out[top] = top
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _qual(node: ast.AST, aliases: dict[str, str]) -> str | None:
    """名字或屬性鏈的全名（照 import 換開）；不是這兩種回 None。"""
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _qual(node.value, aliases)
        return f"{base}.{node.attr}" if base else None
    return None


def _rc_sets(tree: ast.Module, aliases: dict[str, str]):
    """rcParams["鍵"] = 值 的（鍵, 值, 行號）。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                        and (_qual(t.value, aliases) or "").split(".")[-1] == "rcParams"):
                    yield t.slice.value, node.value, node.lineno


def _forbidden(tree: ast.Module) -> list[Problem]:
    """R13–R26：只看 ast 看得到的（docs/09 第 3 節「擋到哪裡」那一欄）。"""
    aliases, out = _aliases(tree), []

    def add(rule, line, text):
        if not any(p.rule == rule and p.line == line for p in out):
            out.append(Problem(rule, line, text))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            else:
                modules = [] if node.level or not node.module else \
                    [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for name in modules:
                top = name.split(".")[0]
                if top in NO_IMPORT["R13"]:
                    add("R13", node.lineno, f"不能 import {top}：畫面是殼的事")
                if top in NO_IMPORT["R18"]:
                    add("R18", node.lineno, f"不能用 {top}：作業不自己開程式或網頁（網址寫在 DOCS）")
                if name.startswith(TK_BACKEND):
                    add("R14", node.lineno, "不能用 matplotlib 的 Tk 後端（畫面是殼的事）")
            if any(a.name in TK_NAMES or (a.asname or "") in TK_NAMES for a in node.names):
                add("R14", node.lineno, "不能用 matplotlib 的 Tk 後端（畫面是殼的事）")
        elif isinstance(node, ast.Name) and node.id in TK_NAMES or isinstance(node, ast.Attribute) and node.attr in TK_NAMES:
            add("R14", node.lineno, "不能用 matplotlib 的 Tk 後端（畫面是殼的事）")
        if isinstance(node, ast.Call):
            name = _qual(node.func, aliases) or ""
            if name == "matplotlib.use":
                add("R15", node.lineno, "不能換 matplotlib 的後端：殼會設")
            if name in {f"matplotlib.pyplot.{f}" for f in PYPLOT_OPEN}:
                add("R16", node.lineno, f"不能用 pyplot 的 {name.rsplit('.', 1)[1]}()：圖畫在 draw 收到的 fig 上（要子圖用 fig.add_subplot）")
            if name == "input":
                add("R17", node.lineno, "不能用 input()：作業不讀鍵盤，參數寫在 CASES")
            if name in RUN_CALLS or name.startswith(RUN_PREFIXES):
                add("R18", node.lineno, f"不能用 {name}：作業不自己開程式或網頁")
            if name == "os.chdir":
                add("R19", node.lineno, "不能 os.chdir：路徑從 DATA 或 Path(__file__) 出發")
            if name in EXIT_CALLS:
                add("R26", node.lineno, f"不能用 {name}()：一個 case 出錯時殼會接著跑下一個，作業不結束整個程式")
            if name == "open" and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                mode = node.args[1] if len(node.args) > 1 else next(
                    (k.value for k in node.keywords if k.arg == "mode"), None)
                if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and set(mode.value) & set("wax"):
                    add("R23", node.lineno, f"寫檔要寫在 DATA 底下：open(DATA / \"{node.args[0].value}\", …)")
        if isinstance(node, (ast.Name, ast.Attribute)) and _qual(node, aliases) == "sys.stdin":
            add("R17", node.lineno, "不能讀 sys.stdin：作業不讀鍵盤，參數寫在 CASES")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.match(ABSOLUTE_RE, node.value):
            add("R20", node.lineno, f"不能寫絕對路徑：{node.value}（從 DATA 或 Path(__file__) 出發）")
        if isinstance(node, ast.Name) and node.id in OLD_GLOBALS or isinstance(node, ast.arg) and node.arg in OLD_GLOBALS:
            add("R21", node.lineno, f"{getattr(node, 'id', None) or node.arg} 是舊格式的全域：路徑用 DATA，畫面是殼的事")
        if isinstance(node, ast.Global):  # nonlocal 不算（D140）：draw 裡的 update 用它記狀態
            add("R22", node.lineno, "不能用 global：case 之間不共用狀態，要傳的東西放在 run 裡")
    for key, value, line in _rc_sets(tree, aliases):
        if key == "backend":
            add("R15", line, "不能換 matplotlib 的後端：殼會設")
        if key in FONT_KEYS and (isinstance(value, ast.Constant)
                                 or isinstance(value, (ast.List, ast.Tuple)) and len(value.elts) == 1):
            add("R24", line, f"rcParams[\"{key}\"] 只指定一個字型：別的電腦沒有它就變方塊；給一串備選，或不設（殼會設）")
    for node in tree.body:
        names = [node.name] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else \
            [t.id for t in getattr(node, "targets", [getattr(node, "target", None)]) if isinstance(t, ast.Name)]
        for name in names:
            if name in IPLOT_NAMES:
                add("R25", node.lineno, f"不要定義 {name}：作業檔不是 iPLoT 的模組，iPLoT 的格子是框架產生的")
    return out


def check(file: Path) -> list[Problem]:
    """docs/09 第 3 節的靜態檢查，照規則編號排；空的就是通過。只用 ast，不執行檔案。"""
    file = Path(file)
    try:
        source = file.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        return [Problem("R27", None, "這個檔不是 UTF-8：用編輯器另存成 UTF-8")]
    except OSError as exc:
        return [Problem("R27", None, f"讀不到這個檔：{exc.strerror or exc}")]
    try:
        tree = ast.parse(source, str(file))
    except (SyntaxError, ValueError) as exc:
        line = getattr(exc, "lineno", None)
        return [Problem("R27", line, f"語法錯誤：{getattr(exc, 'msg', exc)}")]
    lines = source.splitlines() or [""]
    problems, requires = _requires(tree, lines)
    if len(lines) < 2 or _code(lines[1]) != ENSURE_LINE:
        problems.append(Problem("R2", 2, f"第二行要是 {ENSURE_LINE}"))
    problems += _str_assign(tree, "NAME", "R3", 'NAME = "HK1 …"')
    problems += _docs(tree)
    problems += _str_assign(tree, "NOTE", "R5", 'NOTE = """…"""，沒有就寫 NOTE = ""')
    problems += _data(tree, file)
    problems += _cases(tree)
    problems += _function(tree, "compute", 1, "R8", False)
    problems += _function(tree, "draw", 2, "R9", True)
    problems += _function(tree, "stats", 1, "R10", True)
    problems += _tail(tree, lines)
    if requires is not None:
        problems += _forgotten_lines(tree, file, requires)
    problems += _forbidden(tree)
    try:
        ast.parse(source, str(file), feature_version=(3, 9))
    except SyntaxError as exc:
        problems.append(Problem("R28", _newer_line(tree, exc),
                                "這份作業用了 Python 3.10 以後才有的寫法，學生在舊版 Python 上會看不到版本提示"))
    order = list(RULES)
    return sorted(problems, key=lambda p: (order.index(p.rule), p.line or 0))


def cli(argv: list[str], version=sys.version_info) -> int:
    """python coursework.py --check <作業檔>：擋的印 ✗ R<n> 第 <行> 行：<句子>、只警告的印 ⚠ 開頭；
    有擋的回 1，沒有就印「通過」回 0；用錯回 2。Python 不到 3.10：跟 ensure 同一句、回 1（D139）。
    python coursework.py --show-text <標題> <文字>：開一個文字視窗（框架在作業開始跑之前就出錯時用，D142）。"""
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8")
    if tuple(version[:2]) < MIN_PYTHON:
        print(TOO_OLD.format(have=".".join(str(v) for v in version[:3])))
        return 1
    if len(argv) == 3 and argv[0] == "--show-text":
        _show_or_hand_over(argv[1], argv[2])
        return 0
    if len(argv) != 2 or argv[0] != "--check":
        print("用法：python coursework.py --check <作業檔>", file=sys.stderr)
        return 2
    problems = check(Path(argv[1]))
    for p in problems:
        mark = "✗" if p.block else "⚠"
        print(f"{mark} {p.rule} 第 {p.line} 行：{p.text}" if p.line else f"{mark} {p.rule}：{p.text}")
    blocked = any(p.block for p in problems)
    if not blocked:
        print("通過")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
