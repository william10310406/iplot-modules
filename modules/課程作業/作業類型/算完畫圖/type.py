"""作業類型「算完畫圖」：一個 <代號>.py，CASES 裡每個 case 算一次、印數字、畫一張圖（docs/09 規範 v2）。
框架用 course.load_type 載入這個檔、照設計第 2.2 節的介面叫這幾個函式。只 import 標準庫；
判斷一律用 ast，從不執行作業檔。"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

NAME = "算完畫圖"
ACCEPTS = (".py",)  # 收作業時哪些副檔名算作業檔
SHELL = "coursework"  # 殼：跟作業檔放在一起，不是 pip 套件
SHELL_REQUIRES = ("matplotlib",)  # 殼在 iPLoT 裡開視窗要的：課的 .venv 一律裝，不管 REQUIRES 有沒有寫（D145）


def _tree(file: Path) -> ast.Module | None:
    """讀懂就回 ast；不是 UTF-8、語法錯、含 NUL 都回 None。"""
    try:
        return ast.parse(Path(file).read_text(encoding="utf-8-sig"), str(file))
    except (SyntaxError, ValueError):
        return None


def _assigned(tree: ast.Module, name: str) -> ast.expr | None:
    """頂層 name = … 最後一次的值。"""
    found = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name:
            found = node.value
    return found


def _top_imports(tree: ast.Module) -> set[str]:
    return {a.name for node in tree.body if isinstance(node, ast.Import) for a in node.names}


def classify(file: Path) -> tuple[str, str | None]:
    """("mine", None)：頂層有 HOMEWORK = dict(…) 與 import coursework；("broken", None)：語法錯；
    ("not-utf8", None)：不是 UTF-8；("none", None)：其他，包括 import hk_page 的規範 v0 檔（不收）。"""
    try:
        text = Path(file).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return ("not-utf8", None)
    try:
        tree = ast.parse(text, str(file))
    except (SyntaxError, ValueError):
        return ("broken", None)
    imports = _top_imports(tree)
    homework = _assigned(tree, "HOMEWORK")
    is_dict = isinstance(homework, ast.Call) and isinstance(homework.func, ast.Name) and homework.func.id == "dict"
    if "hk_page" in imports or not (is_dict and SHELL in imports):
        return ("none", None)
    return ("mine", None)


def _label(value: ast.expr) -> str:
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "dict":
        node = next((k.value for k in value.keywords if k.arg == "label"), None)
    elif isinstance(value, ast.Dict):
        node = next((v for k, v in zip(value.keys, value.values, strict=True)
                     if isinstance(k, ast.Constant) and k.value == "label"), None)
    else:
        node = None
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else ""


def cases(file: Path) -> list[tuple[str, str]] | None:
    """頂層 CASES = {…} 的（名字, label），照檔裡的順序；label 不是字串常數或沒寫就是 ""。
    CASES 不是 dict 字面值、有一個鍵不是字串常數、檔讀不懂 → None。不執行。"""
    tree = _tree(file)
    value = _assigned(tree, "CASES") if tree else None
    if not isinstance(value, ast.Dict):
        return None
    if not all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in value.keys):
        return None  # 鍵是變數、數字，或 **展開（鍵是 None）
    return [(k.value, _label(v)) for k, v in zip(value.keys, value.values, strict=True)]  # type: ignore[union-attr]


def requires(file: Path) -> set[str]:
    """這份作業要的 pip 名：頂層 REQUIRES = [...] 的字面值（ast 讀，D137）裡的非空字串。
    import 了、REQUIRES 沒寫的不算在這裡：那是 --check 的 R12（只警告、打包時擋）。
    沒有 REQUIRES、不是字串 list 的字面值、檔讀不懂 → 空集合。"""
    tree = _tree(file)
    line = _assigned(tree, "REQUIRES") if tree else None
    try:
        written = ast.literal_eval(line) if line is not None else []
    except ValueError:
        return set()
    return {r for r in written if isinstance(r, str) and r} if isinstance(written, list) else set()


def shell():
    """從檔案載入旁邊的 coursework.py（換個名字，不動 sys.modules 裡的 coursework：那可能是別人的）。
    dataclass 要在 sys.modules 找得到自己的模組，所以載入期間放著、載完拿掉。"""
    name = "_coursework_for_check"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / f"{SHELL}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def check(file: Path) -> list:
    """docs/09 第 3 節的規則（R1–R28）：coursework.check 的 Problem(rule, line, text) 清單；空的就是通過。
    作業那一格只警告、檢查與打包時擋（D131），由框架決定。不執行作業檔。"""
    return shell().check(Path(file))


V0_HINT = "這是規範 v0 的檔：把 hk_page 換成 coursework、尾段換成 v2 的三行（docs/09 第 6 節）"


def hint(file: Path) -> str | None:
    """classify 不是 mine 時給人看的一句（只有規範 v0 的檔有）；讀不懂就 None。不執行。"""
    tree = _tree(file)
    return V0_HINT if tree is not None and "hk_page" in _top_imports(tree) else None


def argv(file: Path, python: Path, case: str | None) -> tuple[list[str], dict[str, str]]:
    """在 iPLoT 裡另開程序跑：課的 Python 跑作業檔，--case <名> 或 --all；殼靠 PYTHONPATH 找（不複製進作業資料夾）。"""
    run = [str(python), str(file), *(["--case", case] if case is not None else ["--all"])]
    return run, {"PYTHONPATH": str(Path(__file__).resolve().parent), "CW_FROM_IPLOT": "1",
                 "PYTHONIOENCODING": "utf-8"}  # stderr 用 UTF-8：框架讀回來給老師看（D142）


ERROR_TAIL = 40  # 開始跑之前就出錯時，給老師看 stderr 的最後幾行


def shown_mark() -> str:
    """殼自己開了錯誤視窗時印到 stderr 的那一行（框架看到就不再開）。"""
    return shell().SHOWN_MARK


def handed_over() -> tuple[str, str]:
    """殼開不了視窗時，交給框架放進訊息區的那一段前後的兩行（D145）。"""
    cw = shell()
    return cw.HANDED_OVER, cw.HANDED_OVER_END


def error_window(file: Path, python: Path, returncode: int, tail: list[str]) -> list[str]:
    """作業在殼的 main 開始之前就出錯（頂層的錯、import 錯）：用課的 Python 跑殼的 --show-text 開一個文字視窗，
    開頭一句白話，接 stderr 的最後幾行；stderr 是空的就說結束碼（D142）。"""
    code = Path(file).stem
    body = "".join(tail).rstrip("\n") or f"（Python 沒有留下錯誤訊息，結束碼 {returncode}）"
    text = f"{code} 在開始跑之前就出錯了，下面是 Python 的錯誤訊息：\n\n{body}"
    return [str(python), str(Path(__file__).resolve().parent / f"{SHELL}.py"), "--show-text", code, text]


def new(folder: Path, code: str) -> Path:
    """在 folder 放 <code>.py（範本，裡面的代號 HK1 換成 code）和空的 <code>Space/，回傳作業檔。
    換的是整個字（不是子字串）：HK12 裡的 HK1 不動，HK1Space 要換。已經有 <code>.py 就丟 FileExistsError。"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    text = re.sub(r"(?<![A-Za-z0-9_])HK1(?!\d)", lambda _: code,
                  (Path(__file__).resolve().parent / "範本.py").read_text(encoding="utf-8"))
    file = folder / f"{code}.py"
    with open(file, "x", encoding="utf-8", newline="\n") as out:  # x：已經有就不蓋
        out.write(text)
    (folder / f"{code}Space").mkdir(exist_ok=True)
    return file


def _space(folder: Path, code: str) -> tuple[list[tuple[Path, str]], list[Path]]:
    """<code>Space/ 底下要放進學生包的（檔或資料夾, zip 裡相對於 <code>/ 的路徑；資料夾結尾是 /）與跳過的。
    跳過 . 開頭的、__pycache__、符號連結（可能指到 Space 外面）；跳過的資料夾整個不看。
    <code>Space/ 本身一定在（沒有或是連結就是一個空的資料夾），學生包永遠同一個樣子、跟 README 對得上。"""
    space = Path(folder) / f"{code}Space"
    kept: list[tuple[Path, str]] = [(space, f"{code}Space/")]
    if space.is_symlink():
        return kept, [space]
    if not space.is_dir():
        return kept, []
    skipped: list[Path] = []
    pending = [space]
    while pending:
        here = pending.pop()
        for p in sorted(here.iterdir()):
            if p.name.startswith(".") or p.name == "__pycache__" or p.is_symlink():
                skipped.append(p)
            elif p.is_dir():
                kept.append((p, p.relative_to(Path(folder)).as_posix() + "/"))
                pending.append(p)
            elif p.is_file():
                kept.append((p, p.relative_to(Path(folder)).as_posix()))
    return kept, skipped


def pack(folder: Path, code: str) -> list[tuple[Path, str]]:
    """學生包裡的東西（檔或資料夾, zip 裡相對於 <code>/ 的路徑）：<code>.py、殼、<code>Space/ 底下的。
    README.txt 由框架用 readme_values 的值另外寫進去。"""
    folder = Path(folder)
    shell_file = Path(__file__).resolve().parent / f"{SHELL}.py"
    return [(folder / f"{code}.py", f"{code}.py"), (shell_file, f"{SHELL}.py"), *_space(folder, code)[0]]


def left_out(folder: Path, code: str) -> list[Path]:
    """<code>Space/ 底下沒放進學生包的（. 開頭、__pycache__、連結），給框架說一句。"""
    return _space(folder, code)[1]


def readme_values(code: str) -> dict[str, str]:
    """框架/學生README.txt 的佔位：指令都從殼的常數來，殼的錯誤句子與 README 是同一份。"""
    cw, file = shell(), f"{code}.py"
    return {"code": code, "file": file, "version_check": cw.VERSION, "make_venv": cw.MAKE_VENV,
            "run": cw.RUN.format(file=file), "win_version_check": cw.WIN_VERSION,
            "remake_venv": cw.REMAKE_VENV, "win_remake_venv": cw.WIN_REMAKE_VENV,
            "win_make_venv": cw.WIN_MAKE_VENV, "win_run": cw.WIN_RUN.format(file=file)}
