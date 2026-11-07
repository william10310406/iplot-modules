"""課程作業的框架：跟科目、跟作業長什麼樣都無關的部分（讀 課程.py、課的 .venv、面板上的格子、打包）。
只 import 標準庫；從不執行老師或學生的檔，判斷一律用 ast，真的跑一律是子程序。"""

from __future__ import annotations

import ast
import collections
import contextlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import ModuleType

MARK = "課程.py"  # 一門課就是一個有這個檔的資料夾
NO_INSTALL = "CW_NO_INSTALL"  # 設了就不建 venv、不跑 pip，缺了只報
FROM_IPLOT = "CW_FROM_IPLOT"  # iPLoT 另開的子程序：不問、不改檔、文字開視窗
VERSIONS = ".版本"  # 作業資料夾裡框架留的版本（D135）
SENT = "發出去的"  # 一門課裡放學生包 zip 的資料夾
KEEP_PY = 20  # .版本/ 裡作業檔的 .py 最多留幾份

HERE = Path(__file__).resolve().parent  # 框架/；它的上一層是模組資料夾（作業類型/、範例課程/ 在那裡）
FRAMEWORK = Path("框架") / "course.py"  # 往上找框架時認的檔
TYPES_DIR = "作業類型"  # 框架所在的資料夾底下：每種作業一個資料夾，裡面是 type.py
PIP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# 子程序裡列出這個 Python 裝了哪些套件（不 import 它們）；它認為自己不在 venv 裡（.venv 少了 pyvenv.cfg）就結束碼 3，
# 不然列出來的是電腦本身的 Python 的套件，pip 也會裝進那裡（D146 修訂）
LIST_INSTALLED = ("import importlib.metadata, json, sys; "
                  "sys.exit(3) if sys.prefix == sys.base_prefix else "
                  "print(json.dumps([d.metadata['Name'] for d in importlib.metadata.distributions()]))")
FOLDER_SLOT = re.compile(r"\{n(?::0([1-4])d)?\}")  # {n} 或 {n:01d}…{n:04d}；不用 str.format 驗使用者給的字串


class CourseError(ValueError):
    """課程.py 讀不了或寫得不對：訊息是一句中文，有行號時含「第 n 行」。"""


class BrokenVenv(RuntimeError):
    """課的 .venv 建過、但它的 Python 叫不起來或一跑就失敗（建它的 Python 被移掉或升版，D146）。"""


@dataclass(frozen=True)
class Course:
    folder: Path
    name: str
    code: str
    folder_format: str
    types: tuple[str, ...]
    packages: tuple[tuple[tuple[str, ...], str, str], ...]
    only_on: dict[str, str]


def _fail(name: str, line: int, what: str) -> CourseError:
    return CourseError(f"第 {line} 行：{name} {what}")


def _is_text_list(value: object) -> bool:
    return isinstance(value, (list, tuple)) and all(isinstance(v, str) and v for v in value)


def _name(value: object, line: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail("NAME", line, "要是不空的字串")
    return value


def _code(value: object, line: int) -> str:
    if not isinstance(value, str) or value.count("{n}") != 1:
        raise _fail("CODE", line, "要是字串，而且剛好有一個 {n}（例如 \"HK{n}\"）")
    rest = value.replace("{n}", "")
    if not all(c.isalnum() or c in "_-" for c in rest):
        raise _fail("CODE", line, "除了 {n}，只能有字母、數字、_、-")
    return value


def _folder(value: object, line: int) -> str:
    if not isinstance(value, str) or len(FOLDER_SLOT.findall(value)) != 1 \
            or re.search(r"[{}]", FOLDER_SLOT.sub("", value)):
        raise _fail("FOLDER", line, "要是字串，而且剛好有一個 {n} 或 {n:0kd}（k 是 1–4，例如 \"HK{n:02d}\"）")
    if re.search(r"[/\\]", value) or value.startswith("."):  # D136：作業資料夾一定在課裡、面板掃得到
        raise _fail("FOLDER", line, "是作業資料夾的名字，作業資料夾要放在這門課的資料夾裡：不能有 / 或 \\，"
                                    "也不能用 . 開頭（. 開頭的資料夾面板看不到）")
    return value


def _types(value: object, line: int) -> tuple[str, ...]:
    if not _is_text_list(value):
        raise _fail("TYPES", line, "要是字串的 list（例如 [\"算完畫圖\"]）")
    return tuple(value)  # type: ignore[arg-type]


def _packages(value: object, line: int) -> tuple[tuple[tuple[str, ...], str, str], ...]:
    what = "要是 [(套件的 list, 說明, 大小), …]，套件名只能有字母、數字、. _ -"
    if not isinstance(value, (list, tuple)):
        raise _fail("PACKAGES", line, what)
    batches = []
    for item in value:
        if not (isinstance(item, (list, tuple)) and len(item) == 3 and _is_text_list(item[0]) and item[0]
                and all(PIP_NAME.fullmatch(p) for p in item[0])
                and isinstance(item[1], str) and isinstance(item[2], str)):
            raise _fail("PACKAGES", line, what)
        batches.append((tuple(item[0]), item[1], item[2]))
    return tuple(batches)


def _only_on(value: object, line: int) -> dict[str, str]:
    if not (isinstance(value, dict)
            and all(isinstance(k, str) and PIP_NAME.fullmatch(k) and v == "apple-silicon"
                    for k, v in value.items())):
        raise _fail("ONLY_ON", line, "要是 {套件名: \"apple-silicon\"}（只認這一種機器）")
    return dict(value)


CHECKS = {"NAME": _name, "CODE": _code, "FOLDER": _folder, "TYPES": _types, "PACKAGES": _packages,
          "ONLY_ON": _only_on}


def read_course(folder: Path) -> Course:
    """讀 folder/課程.py：只用 ast，不執行、不 import。頂層只接認得的名字的 = 字面值，以及字串常數
    的說明；其他一律 CourseError（說第幾行）。沒寫的名字用預設值。"""
    folder = Path(folder)
    file = folder / MARK
    try:
        tree = ast.parse(file.read_text(encoding="utf-8-sig"), str(file))
    except SyntaxError as exc:
        where = f"第 {exc.lineno} 行" if exc.lineno else "某一行"
        raise CourseError(f"{MARK} 的{where}語法不對：{exc.msg}") from exc
    except (OSError, ValueError) as exc:  # 讀不到、不是 UTF-8、含 NUL 位元組
        raise CourseError(f"讀不了 {folder.name}/{MARK}：{exc}") from exc
    values: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            continue  # 說明文字
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            raise CourseError(f"第 {node.lineno} 行：{MARK} 裡只能放「名字 = 值」的設定，這一行不行")
        name = node.targets[0].id
        if name not in CHECKS:
            raise CourseError(f"第 {node.lineno} 行：不認得的名字 {name}（認得：{'、'.join(CHECKS)}）")
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as exc:
            raise _fail(name, node.lineno, "只能寫字面值（字串、數字、list、dict、tuple）") from exc
        values[name] = CHECKS[name](value, node.lineno)
    course = Course(
        folder=folder,
        name=values.get("NAME", folder.name),  # type: ignore[arg-type]
        code=values.get("CODE", "HK{n}"),  # type: ignore[arg-type]
        folder_format=values.get("FOLDER", "HK{n:02d}"),  # type: ignore[arg-type]
        types=values.get("TYPES", ("算完畫圖",)),  # type: ignore[arg-type]
        packages=values.get("PACKAGES", ()),  # type: ignore[arg-type]
        only_on=values.get("ONLY_ON", {}),  # type: ignore[arg-type]
    )
    # D136：用 FOLDER 組出來的作業資料夾，解析後（連結、..）一定在課的資料夾之內
    first = (folder / folder_of(course, 1)).resolve()
    if first.parent != folder.resolve():
        line = next((n.lineno for n in tree.body if isinstance(n, ast.Assign)
                     and getattr(n.targets[0], "id", "") == "FOLDER"), None)
        where = f"第 {line} 行：" if line else ""
        raise CourseError(f"{where}FOLDER 組出來的作業資料夾 {folder_of(course, 1)} 實際上指到這門課的資料夾外面"
                          "（可能是連結），作業資料夾要放在這門課的資料夾裡")
    return course


def code_of(course: Course, n: int) -> str:
    return course.code.replace("{n}", str(n))


def folder_of(course: Course, n: int) -> str:
    return FOLDER_SLOT.sub(lambda m: f"{n:0{m.group(1)}d}" if m.group(1) else str(n), course.folder_format)


def code_number(course: Course, name: str) -> int | None:
    """名字（檔名去副檔名、zip 名、資料夾名都行）裡認作業代號，回數字；認不出回 None。不分大小寫、
    數字可以補零（HK05 就是 HK5）；代號前後緊鄰英文字母不算（CHK1 不是 HK1、HK1A 也不是）。"""
    before, after = course.code.split("{n}")
    pattern = rf"(?<![A-Za-z]){re.escape(before)}0*(\d+)(?!\d){re.escape(after)}(?![A-Za-z])"
    found = re.search(pattern, name, re.IGNORECASE)
    return int(found.group(1)) if found else None


def _up(start: Path, wanted: Path) -> Path | None:
    here = Path(os.path.abspath(start))
    for folder in (here, *here.parents):
        if (folder / wanted).is_file():
            return folder
    return None


def course_root(start: Path) -> Path | None:
    """從 start 自己往上，第一個有 課程.py 的資料夾。"""
    return _up(start, Path(MARK))


def framework_root(start: Path) -> Path | None:
    """從 start 自己往上，第一個有 框架/course.py 的資料夾。"""
    return _up(start, FRAMEWORK)


def load_type(name: str, framework: Path) -> ModuleType:
    """載入作業類型 framework/作業類型/<name>/type.py（框架自己帶的程式，不是老師或學生的）。
    name 不是 作業類型/ 底下的一個資料夾、或那裡沒有 type.py → CourseError。"""
    base = Path(framework) / TYPES_DIR
    file = base / name / "type.py"
    if not name or re.search(r"[/\\]", name) or name.startswith(".") or not file.is_file() \
            or file.resolve().parent.parent != base.resolve():
        try:
            have = sorted(p.name for p in base.iterdir() if (p / "type.py").is_file())
        except OSError:
            have = []
        raise CourseError(f"沒有「{name}」這種作業：{TYPES_DIR}/ 底下有的是 {'、'.join(have) or '（沒有）'}")
    spec = importlib.util.spec_from_file_location(f"cw_type_{name}", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ── 課的 .venv：建、列已裝、缺的問一次、一個一個裝（從科學計算的 hk_tk 複製來改，不 import 它）──

def python_in(venv_dir: Path) -> Path:
    """venv 裡 Python 的位置（不查在不在）。"""
    return Path(venv_dir) / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def venv_python(course: Path | None) -> Path | None:
    """課 .venv 的 Python；還沒建（或 course 是 None）回 None。斷掉的連結也算建過（壞了，D146），回它。"""
    if course is None:
        return None
    python = python_in(Path(course) / ".venv")
    return python if python.is_file() or python.is_symlink() else None


def _normal(dist: str) -> str:
    return re.sub(r"[-_.]+", "-", dist).lower()


def ensure_venv(venv_dir: Path, say, popen=subprocess.Popen, python: str = sys.executable, clear: bool = False) -> Path:
    """venv_dir 的 Python；還沒有就用 python -m venv 建（不帶 --system-site-packages）。
    clear：壞掉的 .venv 用 --clear 清空重建，不蓋在壞的上面（D146）。"""
    venv_dir = Path(venv_dir)
    exe = python_in(venv_dir)
    if exe.is_file() and not clear:
        return exe
    if os.environ.get(NO_INSTALL):
        raise RuntimeError(f"{NO_INSTALL}：不建 .venv")
    say(f"在{'重建' if clear else '建'} {venv_dir.parent.name}/{venv_dir.name} …")
    code = popen([str(python), "-m", "venv", *(["--clear"] if clear else []), str(venv_dir)]).wait()
    if code != 0:
        raise RuntimeError(f"建不了 {venv_dir}：代碼 {code}")
    return exe


def installed(python: Path, popen=subprocess.Popen) -> set[str]:
    """python 那個環境裝了哪些套件（名字正規化成小寫、- 連接）；回答讀不懂回空集合。
    python 叫不起來（OSError）或結束碼不是 0 → BrokenVenv（D146）。"""
    try:
        proc = popen([str(python), "-c", LIST_INSTALLED], stdout=subprocess.PIPE, text=True)
        out, _ = proc.communicate()
    except OSError as exc:
        raise BrokenVenv(str(exc)) from exc
    if proc.returncode:
        raise BrokenVenv(f"結束碼 {proc.returncode}")
    try:
        return {_normal(n) for n in json.loads(out)}
    except (ValueError, TypeError):
        return set()


def missing(python: Path, pkgs, popen=subprocess.Popen) -> list[str]:
    """pkgs 裡 python 那個環境還沒有的，照原順序、不重複。"""
    have, out = installed(python, popen=popen), []
    for pkg in pkgs:
        if _normal(pkg) not in have and _normal(pkg) not in map(_normal, out):
            out.append(pkg)
    return out


def install(python: Path, pkgs: list[str], say, popen=subprocess.Popen, clock=time.monotonic):
    """一個一個 pip install 進 python 那個環境；一個裝不了，其他照裝。
    pip 的輸出一行一行讀，每 5 秒 say 一次最後一行。回（裝好的, [(裝不了的, 原因)]）。"""
    ok, failed = [], []
    for pkg in pkgs:
        if not PIP_NAME.fullmatch(pkg):  # fullmatch：$ 會放過結尾的換行
            failed.append((pkg, "名字不合法"))
        elif os.environ.get(NO_INSTALL):
            failed.append((pkg, NO_INSTALL))
        else:
            proc = popen([str(python), "-m", "pip", "install", "--no-input", "--disable-pip-version-check", pkg],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            tail, last = collections.deque(maxlen=5), clock()
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                tail.append(line)
                now = clock()
                if now - last >= 5:
                    say(f"{pkg}：{line}")
                    last = now
            if proc.wait() == 0:
                ok.append(pkg)
            else:
                errors = [t.strip() for t in tail if t.strip().startswith("ERROR")]
                failed.append((pkg, " / ".join(errors or [t.strip() for t in tail])))
    return ok, failed


def summary_of_install(ok, failed) -> str:
    """「已裝 a、b；裝不了 c（原因）」；兩個都空回空字串。"""
    parts = []
    if ok:
        parts.append("已裝 " + "、".join(ok))
    if failed:
        parts.append("裝不了 " + "、".join(f"{p}（{why}）" for p, why in failed))
    return "；".join(parts)


BROKEN_SAYS = "壞了（建它的 Python 已經不在、或換了版本）"  # D146


def _pending(python: Path | None, need, popen) -> tuple[list[str], bool]:
    """（need 裡課的 .venv 還沒有的, .venv 壞了沒）：還沒建或壞了就是全部。"""
    if python is None:
        return list(need), False
    try:
        return (missing(python, need, popen) if need else []), False
    except BrokenVenv:
        return list(need), True


# ── 課那一格 ──

def _apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def homeworks(course: Course) -> list[tuple[str, Path]]:
    """這門課的作業（代號, 作業檔），照數字排：課裡每個資料夾（. 開頭的不算）底下名字剛好是 <代號>.py 的檔，
    而且是 TYPES 裡某一種認得的作業（classify 說 mine）。只看檔名與 ast，不執行。"""
    found: list[tuple[int, str, Path]] = []
    try:
        folders = sorted(p for p in course.folder.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []
    for sub in folders:
        for file in sorted(sub.glob("*.py")):
            n = code_number(course, file.stem)
            if n is not None and file.stem == code_of(course, n):
                found.append((n, file.stem, file))
    return [(code, file) for _, code, file in sorted(found)]


def _unreadable(file: Path, exc: OSError) -> str:
    return f"讀不了 {file.name}（{exc.strerror or exc}）"


def _os_problem(exc: OSError, file: Path | None, course_folder: Path) -> str:
    """OSError 說成一句，指到真正出錯的路徑（exc.filename，從課的資料夾名字寫起）；沒有路徑、或就是作業檔，
    才說「讀不了 <作業檔>」（D147）。"""
    where = Path(os.path.abspath(exc.filename)) if exc.filename else None
    if where is None or (file is not None and where == Path(os.path.abspath(file))):
        return _unreadable(file, exc) if file is not None else f"出了問題（{exc.strerror or exc}）"
    base = Path(os.path.abspath(course_folder)).parent
    try:
        shown = where.relative_to(base).as_posix()
    except ValueError:
        shown = str(where)
    return f"{shown} 有問題（{exc.strerror or exc}）"


def _kind_of(file: Path, kinds: list[ModuleType]) -> ModuleType | None:
    """TYPES 裡第一種說這個檔是 mine 的作業類型；都不是回 None。讀不到檔（OSError）照丟，由叫的人說成一句話。"""
    return next((k for k in kinds if k.classify(file)[0] == "mine"), None)


def _with_shell(need, kinds) -> list[str]:
    """need 再加上作業類型的殼自己要的（SHELL_REQUIRES，例如開視窗的 matplotlib，D145），不重複、照字母排。"""
    out = {_normal(p): p for p in need}
    for kind in kinds:
        for pkg in getattr(kind, "SHELL_REQUIRES", ()):
            out.setdefault(_normal(pkg), pkg)
    return sorted(out.values(), key=str.lower)


def _requires(course: Course, kinds: list[ModuleType], say) -> dict[str, set[str]]:
    """代號 → 這份作業要的 pip 名；不是任何一種 TYPES 認得的作業就不算，讀不到的檔 say 一句、不算。"""
    out: dict[str, set[str]] = {}
    for code, file in homeworks(course):
        try:
            kind = _kind_of(file, kinds)
            if kind is not None:
                out[code] = kind.requires(file)
        except OSError as exc:
            say(f"{_unreadable(file, exc)}，{code} 要的套件沒算進來")
    return out


def course_button(app, folder: Path, popen=subprocess.Popen, apple_silicon: bool | None = None) -> None:
    """課那一格：把這門課要的套件裝進課的 .venv。PACKAGES 有就一批一批問（一次只問一批），沒有就裝每份作業
    REQUIRES 的聯集；ONLY_ON 的套件在不對的機器上不裝，句子說哪幾份作業在這裡看不了。先問、確定了才建 .venv。
    中途的 OSError 說一句、指到出錯的路徑（D147），不出 traceback。"""
    folder = Path(folder)
    try:
        _course_button(app, folder, popen, apple_silicon)
    except OSError as exc:
        app.log(f"{folder.name}：{_os_problem(exc, None, folder)}，沒裝")


def _course_button(app, folder: Path, popen, apple_silicon: bool | None) -> None:
    apple = _apple_silicon() if apple_silicon is None else apple_silicon
    try:
        course = read_course(folder)
        kinds = [load_type(name, HERE.parent) for name in course.types]
        needs = _requires(course, kinds, app.log)
    except CourseError as exc:
        app.log(f"{folder.name}：{exc}")
        return
    if course.packages:
        batches = [(f"{why}：", list(pkgs), size) for pkgs, why, size in course.packages]
    else:
        batches = [("", _with_shell(set().union(*needs.values()), kinds), "")]
    off = {_normal(p) for p in course.only_on} if not apple else set()
    skipped = [p for _, pkgs, _ in batches for p in pkgs if _normal(p) in off]
    batches = [(label, [p for p in pkgs if _normal(p) not in off], size) for label, pkgs, size in batches]
    note = ""
    if skipped:
        users = [code for code, req in needs.items() if {_normal(r) for r in req} & {_normal(p) for p in skipped}]
        note = f"這台機器裝不了 {'、'.join(skipped)}（只有 Apple Silicon 的 Mac 裝得了）"
        if users:
            note += f"，用到它的作業 {'、'.join(users)} 在這裡看不了"
    python = venv_python(folder)
    broken = python is not None and _pending(python, ["pip"], popen)[1]
    pending = [(label, pkgs if python is None or broken else missing(python, pkgs, popen), size)
               for label, pkgs, size in batches if pkgs]
    pending = [item for item in pending if item[1]]
    if not pending:
        said = "課程套件都在" if any(pkgs for _, pkgs, _ in batches) else "這門課還沒有需要裝的套件（沒有作業，或作業的 REQUIRES 都是空的）"
        app.log(f"{said}；{note}" if note else said)
        return
    label, need, size = pending[0]
    if os.environ.get(NO_INSTALL):
        app.log(f"{NO_INSTALL}：不建 .venv、不裝套件（還缺 {'、'.join(need)}）")
        return
    ask = f"要裝{course.name}的課程套件嗎？{label}{'、'.join(need)}。{size + '，' if size else ''}裝進 {folder.name}/.venv" \
          + ("（還沒建，會先建）" if python is None else "（這個 .venv 壞了：建它的 Python 已經不在、或換了版本，會先清掉重建）" if broken else "") \
          + "；網路慢的話要很久，裝的時候別的按鈕要等它裝完"
    if not app.confirm(f"{ask}。{note}" if note else ask):
        app.log("沒裝")
        return
    try:
        python = ensure_venv(folder / ".venv", say=app.log, popen=popen, clear=broken)
    except RuntimeError as exc:
        app.log(str(exc))
        return
    ok, failed = install(python, need, say=app.log, popen=popen)
    said = summary_of_install(ok, failed)
    if len(pending) > 1:
        later = pending[1]
        said += f"；{later[0].rstrip('：')}{'（' + later[2] + '）' if later[2] else ''}再按一次「{course.name}」"
    app.log(f"{said}；{note}" if note else said)


# ── 作業那一格：留版本 → 檢查（只提醒）→ 裝套件 → 選 case → 用課的 .venv 另開程序；面板程序從不執行作業檔 ──

def _versions(file: Path) -> list[Path]:
    """file 在 .版本/ 裡的 .py 版本，舊到新。只認 <代號>_<YYYY-MM-DD_HHMMSS>[_n].py（照 core/history.py）；別的檔不算。"""
    own = re.compile(rf"{re.escape(file.stem)}_(\d{{4}}-\d{{2}}-\d{{2}}_\d{{6}})(?:_(\d+))?")
    found = []
    for p in (file.parent / VERSIONS).glob("*.py"):
        m = own.fullmatch(p.stem)
        if m:
            found.append(((m.group(1), int(m.group(2) or 0)), p))
    return [p for _, p in sorted(found)]


def snapshot_homework(file: Path, keep: int = KEEP_PY, now=datetime.now) -> Path | None:
    """作業檔跟 .版本/ 裡最新的 .py 不一樣就存一份（D135），回那個檔；一樣就不存、回 None。
    超過 keep 份刪最舊的，只刪自己這種命名的 .py：學生包 zip 與 .版本/ 裡別的檔都不碰。"""
    file = Path(file)
    data, old = file.read_bytes(), _versions(file)
    if old and old[-1].read_bytes() == data:
        return None
    folder = file.parent / VERSIONS
    folder.mkdir(exist_ok=True)
    stamp = now().strftime("%Y-%m-%d_%H%M%S")
    new, n = folder / f"{file.stem}_{stamp}.py", 0
    while new.exists():
        n += 1
        new = folder / f"{file.stem}_{stamp}_{n}.py"
    new.write_bytes(data)
    for extra in _versions(file)[:-keep]:
        extra.unlink()
    return new


def _homework_in(course: Course, folder: Path) -> tuple[str, Path] | None:
    """作業資料夾裡名字剛好是 <代號>.py 的那一個檔（跟 homeworks 同一個認法）。"""
    for file in sorted(Path(folder).glob("*.py")):
        n = code_number(course, file.stem)
        if n is not None and file.stem == code_of(course, n):
            return file.stem, file
    return None


def problem_lines(problems) -> list[str]:
    """--check 的問題，跟 coursework 的 cli 同一個樣子：擋的 ✗、只警告的 ⚠（D141）。"""
    return [f"{'✗' if getattr(p, 'block', True) else '⚠'} {p.rule}" + (f" 第 {p.line} 行：{p.text}" if p.line else f"：{p.text}")
            for p in problems]


def case_prompt(code: str, cases: list[tuple[str, str]]) -> str:
    """選 case 的對話框。面板的對話框一開就捲到最底（Task 0 探針），所以最後一行說要打什麼。"""
    lines = [f"{code} 要跑哪一個？"]
    lines += [f"{n}) {name}  {label}".rstrip() for n, (name, label) in enumerate(cases, 1)]
    lines.append("0) 全部")
    which = "1 跑這個 case" if len(cases) == 1 else f"1–{len(cases)} 跑一個 case"
    lines.append(f"打 {which}，打 0 全部跑：")
    return "\n".join(lines)


def _in_background(job) -> None:
    threading.Thread(target=job, daemon=True).start()


def homework_button(app, folder: Path, popen=subprocess.Popen, now=datetime.now,
                    apple_silicon: bool | None = None, background=_in_background) -> None:
    """作業那一格（D128）：留一份作業檔的版本 → --check 有問題就列出來、照跑（D131）→ 課的 .venv 不在或缺
    REQUIRES 就問一次、裝 → app.ask 選 case（0 全部；沒有 case 就不問）→ 用課的 .venv 另開程序跑，不等它：
    背景讀它的 stderr，開始跑之前就出錯時另開一個文字視窗（D142）。只用 ast 讀作業檔，從不執行它；讀不到檔說一句話。"""
    folder = Path(folder)
    course_folder = course_root(folder)
    if course_folder is None:
        app.log(f"{folder.name}：上面找不到 {MARK}，不知道是哪一門課")
        return
    try:
        course = read_course(course_folder)
        kinds = [load_type(name, HERE.parent) for name in course.types]
    except CourseError as exc:
        app.log(f"{course_folder.name}：{exc}")
        return
    found = _homework_in(course, folder)
    if found is None:
        app.log(f"{folder.name}：這個資料夾裡沒有作業檔（{code_of(course, 1)}.py 這種名字的）")
        return
    code, file = found
    try:
        _press(app, course, kinds, code, file, popen, now, _apple_silicon() if apple_silicon is None else apple_silicon,
               background)
    except OSError as exc:
        app.log(f"{code}：{_os_problem(exc, file, course_folder)}，沒跑")


def _press(app, course: Course, kinds, code: str, file: Path, popen, now, apple: bool, background) -> None:
    kind = _kind_of(file, kinds)
    snapshot_homework(file, now=now)
    if kind is None:  # 不是 v2 的作業（語法錯、不是 UTF-8、規範 v0、不是作業）：列問題、說一句、不跑
        if kinds:
            for line in problem_lines(kinds[0].check(file)):
                app.log(line)
        hint = next((h for h in (getattr(k, "hint", lambda f: None)(file) for k in kinds) if h), None)
        app.log(f"沒跑：{file.name} 不是規範 v2 的作業檔" + (f"。{hint}" if hint else ""))
        return
    lines = problem_lines(kind.check(file))
    for line in lines:
        app.log(line)
    if lines:
        app.log("以上在 iPLoT 裡只提醒、照跑；✗ 的在「檢查與打包」時會擋" if any(line.startswith("✗") for line in lines)
                else "以上只提醒，照跑；打包也不擋")
    own = kind.requires(file)
    shell_only = [p for p in _with_shell((), [kind]) if _normal(p) not in {_normal(r) for r in own}]
    if not _ready(app, course, code, _with_shell(own, [kind]), popen, apple, shell_only):
        return
    python = venv_python(course.folder)
    cases = kind.cases(file)
    if cases is None:
        app.log("R7：CASES 讀不出來（鍵要是字串常數、值是 dict(…) 或 {…}），不知道有哪幾個 case，沒跑")
        return
    case = None
    if cases:
        answer = app.ask(case_prompt(code, cases), "1")
        if answer is None:
            app.log("沒跑")
            return
        answer = answer.strip()
        if not (answer.isascii() and answer.isdecimal() and int(answer) <= len(cases)):
            app.log(f"要打 0 到 {len(cases)} 之間的數字，沒跑")
            return
        case = cases[int(answer) - 1][0] if int(answer) else None
    argv, env = kind.argv(file, python, case)
    proc = popen(argv, cwd=str(file.parent), env={**os.environ, **env},
                 stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    app.log(f"{code}：{case or '全部'} 的視窗開了（在 Dock 上找 Python）")
    background(lambda: _watch(proc, kind, file, python, popen, app.log))


def _read(stream, kind, log, tail=None) -> tuple[bool, bool]:
    """讀完一個子程序的 stderr：殼開不了視窗交過來的段落（handed_over 的兩行之間）一行一行 log（D145）；
    其他的行放進 tail。回（看到 shown_mark 了沒, 交過段落了沒）。"""
    mark = kind.shown_mark()
    start, end = getattr(kind, "handed_over", lambda: (None, None))()
    shown = handed = False
    block = None
    for raw in stream or ():
        line = raw.rstrip("\r\n")
        if line == mark:
            shown = True
        elif start is not None and line == start:
            block = []
        elif block is not None and line == end:
            for said in block:
                log(said)
            block, handed = None, True
        elif block is not None:
            block.append(line)
        elif tail is not None:
            tail.append(raw)
    return shown, handed


def _watch(proc, kind, file: Path, python: Path, popen, log) -> None:
    """讀完子程序的 stderr、等它結束：殼開不了視窗交過來的段落放進訊息區（D145）；結束碼不是 0、而且殼沒說它已經
    給人看過錯誤（作業在 main 開始之前就出錯），就用作業類型給的指令另開一個文字視窗放 stderr 的最後幾行（D142），
    那個視窗也開不了就放進訊息區。在背景跑，面板不等；log 是 app.log，面板關了也不往外丟。"""
    def say(line: str) -> None:
        with contextlib.suppress(Exception):
            log(line)

    tail: collections.deque[str] = collections.deque(maxlen=kind.ERROR_TAIL)
    shown, _ = _read(proc.stderr, kind, say, tail)
    returncode = proc.wait()
    if returncode == 0 or shown:
        return
    lines = [line.rstrip("\r\n") for line in tail] or [f"（Python 沒有留下錯誤訊息，結束碼 {returncode}）"]
    try:
        window = popen(kind.error_window(file, python, returncode, list(tail)), cwd=str(file.parent),
                       stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        _, handed = _read(window.stderr, kind, say)
        if window.wait() == 0 or handed:
            return
    except OSError:  # 連課的 Python 都叫不起來
        pass
    say(f"{file.stem}：錯誤視窗開不了，Python 的錯誤訊息：")
    for line in lines:
        say(line)


def _ready(app, course: Course, code: str, need: list[str], popen, apple: bool, shell_only=()) -> bool:
    """課的 .venv 在、need（這份作業的 REQUIRES 加上殼要的）都裝了就 True；不然問一次、建、裝，裝好了才 True。
    ONLY_ON 的套件在不對的機器上：不裝、不跑。.venv 不在而 need 是空的：也問一次、建空的 .venv。
    .venv 壞了（BrokenVenv）：問一次要不要清掉重建，確定了用 --clear 重建、重裝 need（D146）。
    shell_only 是 need 裡只有殼要的（REQUIRES 沒寫），問的句子說它是做什麼的（D145）。"""
    off = {_normal(p) for p in course.only_on} if not apple else set()
    blocked = [p for p in need if _normal(p) in off]
    if blocked:
        app.log(f"這台機器裝不了 {'、'.join(blocked)}（只有 Apple Silicon 的 Mac 裝得了），{code} 在這裡看不了，沒跑")
        return False
    venv = course.folder / ".venv"
    python = venv_python(course.folder)
    lack, broken = _pending(python, need, popen)
    if python is not None and not broken and not lack:
        return True
    where = f"{course.folder.name}/.venv"
    if os.environ.get(NO_INSTALL):
        what = f"{where} {BROKEN_SAYS}" if broken else f"還缺 {'、'.join(lack)}" if lack else f"{where} 還沒建"
        app.log(f"{NO_INSTALL}：不建 .venv、不裝套件（{what}），沒跑")
        return False
    if broken:
        ask = f"{where} {BROKEN_SAYS}：要清掉重建" + (f"，並裝 {'、'.join(lack)} 嗎？" if lack else " 嗎？")
    elif python is None:
        ask = f"這門課的 .venv 還沒建：要建在 {where}" + (f"，並裝 {'、'.join(lack)} 嗎？" if lack
                                                          else f" 嗎？{code} 沒有要裝的套件")
    else:
        ask = f"{code} 用到還沒裝的套件：{'、'.join(lack)}。現在裝進 {where} 嗎？"
    why = [p for p in lack if _normal(p) in {_normal(x) for x in shell_only}]
    if why:
        ask += f"（{'、'.join(why)} 是在 iPLoT 裡開視窗用的）"
    if not app.confirm(ask + ("（網路慢的話要很久，裝的時候別的按鈕要等它裝完）" if lack else "")):
        app.log("沒重建，沒跑" if broken else "沒裝，沒跑")
        return False
    try:
        python = ensure_venv(venv, say=app.log, popen=popen, clear=broken)
    except RuntimeError as exc:
        app.log(f"{exc}，沒跑")
        return False
    if lack:
        ok, failed = install(python, lack, say=app.log, popen=popen)
        app.log(summary_of_install(ok, failed))
        if failed:
            app.log(f"{code} 要的套件沒裝齊，沒跑")
            return False
    return True


# ── 檢查與打包：--check 擋 ✗（⚠ 照打包，D141）→ 發出去的/<代號>_學生包.zip → .版本/ 留一份同樣 bytes 的（D135）──

PACK_SUFFIX = "_學生包.zip"
README = HERE / "學生README.txt"


def keep_pack(zip_path: Path, homework_folder: Path, now: datetime) -> Path:
    """把打包好的 zip 原封不動複製成 <作業資料夾>/.版本/<代號>_<YYYY-MM-DD_HHMMSS>_學生包.zip；永遠不刪（D135）。
    同一秒打包兩次，第二份是 <代號>_<時間>_1_學生包.zip。"""
    code = Path(zip_path).name.removesuffix(PACK_SUFFIX)
    folder = Path(homework_folder) / VERSIONS
    folder.mkdir(exist_ok=True)
    stamp = now.strftime("%Y-%m-%d_%H%M%S")
    new, n = folder / f"{code}_{stamp}{PACK_SUFFIX}", 0
    while new.exists():
        n += 1
        new = folder / f"{code}_{stamp}_{n}{PACK_SUFFIX}"
    shutil.copyfile(zip_path, new)
    return new


def _write_zip(target: Path, code: str, members: list[tuple[Path, str]], readme: str, when: datetime) -> None:
    """學生包：第一層是 <代號>/；成員照路徑排、時間都是打包那一刻、UTF-8 檔名。先寫到暫存檔再換上去。"""
    stamp = when.timetuple()[:6]
    entries = [(f"{code}/{arc}", path) for path, arc in members] + [(f"{code}/README.txt", None)]
    tmp = target.with_name(target.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, path in sorted(entries, key=lambda e: e[0]):
            info = zipfile.ZipInfo(arc, date_time=stamp)
            info.flag_bits |= 0x800
            if arc.endswith("/"):
                info.external_attr = (0o40755 << 16) | 0x10
                z.writestr(info, b"")
            else:
                info.external_attr, info.compress_type = 0o644 << 16, zipfile.ZIP_DEFLATED
                z.writestr(info, readme.encode("utf-8") if path is None else path.read_bytes())
    os.replace(tmp, target)


def check_and_pack(app, course_folder: Path, now=datetime.now) -> None:
    """檢查與打包：問哪一份（預設號碼最大的）→ --check 有 ✗ 就列出來、不打包（⚠ 列出來、照打包）→
    寫 發出去的/<代號>_學生包.zip（作業檔、殼、<代號>Space/、README.txt）→ .版本/ 留一份 → 在 Finder 顯示。"""
    course_folder = Path(course_folder)
    try:
        course = read_course(course_folder)
        kinds = [load_type(name, HERE.parent) for name in course.types]
    except CourseError as exc:
        app.log(f"{course_folder.name}：{exc}")
        return
    found = homeworks(course)
    if not found:
        app.log(f"{course.name} 還沒有作業：先按「新增作業」")
        return
    by_number = {code_number(course, code): (code, file) for code, file in found}
    answer = app.ask("要打包哪一份？", found[-1][0])
    if answer is None:
        app.log("沒打包")
        return
    n = code_number(course, answer.strip())
    if n not in by_number:
        app.log(f"沒有「{answer}」這份作業（有的是 {'、'.join(code for code, _ in found)}），沒打包")
        return
    code, file = by_number[n]
    try:
        kind = _kind_of(file, kinds)
        lines = problem_lines((kind or kinds[0]).check(file)) if (kind or kinds) else []
        for line in lines:
            app.log(line)
        if kind is None:
            app.log(f"沒有打包：{file.name} 不是規範 v2 的作業檔")
            return
        if any(line.startswith("✗") for line in lines):
            app.log("沒有打包：先改好上面 ✗ 的這幾條")
            return
        readme = README.read_text(encoding="utf-8")
        for key, value in kind.readme_values(code).items():
            readme = readme.replace("{" + key + "}", value)
        when = now()
        out = course_folder / SENT
        out.mkdir(exist_ok=True)
        target = out / f"{code}{PACK_SUFFIX}"
        _write_zip(target, code, kind.pack(file.parent, code), readme, when)
        kept = keep_pack(target, file.parent, when)
    except OSError as exc:
        app.log(f"{code}：{_os_problem(exc, file, course_folder)}，沒有打包")
        return
    skipped = getattr(kind, "left_out", lambda folder, code: [])(file.parent, code)
    if skipped:
        app.log(f"{code}Space 裡這幾個沒放進學生包（. 開頭、__pycache__、連結）：{'、'.join(p.name for p in skipped)}")
    app.log(f"已打包 {code}：發給學生的是 {course_folder.name}/{SENT}/{target.name}；"
            f"同一份也存在 {file.parent.name}/{VERSIONS}/{kept.name}（不會自動刪）")
    app.reveal(target)


# ── 墊片：面板上每一格的 iplot.py ──
# 墊片只有幾行：往上找第一個有 框架/course.py 的資料夾，放進 sys.path、每次重讀 course、叫一個函式，
# 所以框架更新後墊片不用換（跟科學計算的墊片同一個做法）。作業資料夾裡的 iplot.py 也是墊片，面板程序從不執行作業檔。

STUB_MARK = "# 課程作業框架產生的墊片"  # 有這一行的 iplot.py 是框架產生的，可以換成這一版；沒有的是別人寫的，不碰
STUB = '''"""{doc}"""
{mark}（改了會被換掉；要自己寫格子，把這一行拿掉）
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
TITLE = {title}
FRAMEWORK = next(p for p in HERE.parents if (p / "框架" / "course.py").is_file()) / "框架"
sys.modules.pop("course", None)  # 每次都讀框架現在那一份
sys.path.insert(0, str(FRAMEWORK))
try:
    import course
finally:
    sys.path.remove(str(FRAMEWORK))


def run(app):
    course.{call}
'''
STUB_DOC = "課程作業框架產生的格子：按下去叫框架裡的函式。"

# 每一種格子的（要叫的函式, 面板上的說明）；函式裡的 HERE 是墊片所在的資料夾
COURSE_STUB = ("course_button(app, HERE)", "按下去：把這門課要的套件裝進課的 .venv。")
HOMEWORK_STUB = ("homework_button(app, HERE)", "按下去：選一個 case，用課的 Python 另開視窗跑這份作業。")
TOP_BUTTONS = {  # 模組資料夾底下、追蹤進 git 的兩顆
    "新增一門課": ("new_course(app, HERE.parent)", "問課的名字，建一門新的課。"),
    "加入範例課程": ("add_example(app, HERE.parent)", "把範例課程「科學計算」複製成一門課（不必裝）。"),
}
COURSE_BUTTONS = {  # 每門課底下的兩顆
    "新增作業": ("new_homework(app, HERE.parent)", "問作業代號，從範本建一份新的作業並打開編輯器。"),
    "檢查與打包": ("check_and_pack(app, HERE.parent)", "選一份作業：檢查、打成學生包 zip、在 Finder 顯示。"),
}
EXAMPLE = "科學計算"  # 範例課程/ 底下那一門


def render_stub(title: str, call: str, doc: str = STUB_DOC) -> str:
    """墊片的文字。title 用 repr 寫進去（引號、反斜線都安全）；doc 的引號跳脫，不會提早結束 docstring。"""
    safe = doc.replace("\\", "\\\\").replace('"', '\\"')
    return STUB.format(doc=safe, mark=STUB_MARK, title=repr(title), call=call)


def write_stub(folder: Path, title: str, call: str, doc: str = STUB_DOC) -> Path:
    """寫 folder/iplot.py 墊片。已經是這一版就不碰；是框架產生過的墊片（認記號行）就換成這一版；
    是別的檔（老師自己寫的）不碰。回傳那個檔。"""
    file = Path(folder) / "iplot.py"
    text = render_stub(title, call, doc)
    if file.exists():
        old = file.read_text(encoding="utf-8", errors="replace")
        if old == text or STUB_MARK not in old:
            return file
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8", newline="\n")
    return file


def _course_buttons(folder: Path, title: str) -> None:
    """課那一層的格子：課那一格、新增作業、檢查與打包。"""
    write_stub(folder, title, *COURSE_STUB)
    for name, (call, doc) in COURSE_BUTTONS.items():
        write_stub(folder / name, name, call, doc)


FORBIDDEN_CHARS = set('/\\:*?"<>|')  # 跟 core/create.py 同一套：課以後會被複製到別的電腦
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _bad_name(name: str) -> bool:
    return (name.startswith(".") or name != name.rstrip(". ")
            or any(c in FORBIDDEN_CHARS or ord(c) < 32 for c in name)
            or name.split(".")[0].upper() in RESERVED)


def new_course(app, root: Path) -> None:
    """新增一門課：問名字 → 在 root（模組資料夾）底下建 課程.py（只有 NAME）和四顆格子的墊片。不蓋已有的。"""
    root = Path(root)
    name = app.ask("課的名字：", "")
    if name is None or not name.strip():
        app.log("沒新增")
        return
    if _bad_name(name):
        app.log("名稱不能是空白、以 . 開頭、結尾是 . 或空白、含 / \\ : * ? \" < > |，"
                "也不能是 CON、NUL 這類 Windows 保留字（課要能複製到任何系統）")
        return
    folder = root / name
    if folder.exists() or folder.is_symlink():
        app.log(f"已經有叫「{name}」的資料夾了，沒有新增（不會蓋掉）")
        return
    template = (HERE / "範本" / MARK).read_text(encoding="utf-8")
    folder.mkdir()
    text = re.sub(r'^NAME = "[^"\n]*"', lambda _: f"NAME = {json.dumps(name, ensure_ascii=False)}", template,
                  count=1, flags=re.MULTILINE)
    (folder / MARK).write_text(text, encoding="utf-8", newline="\n")
    _course_buttons(folder, name)
    app.rescan()
    app.log(f"已新增「{name}」：按它旁邊的 ▸ 進去，「新增作業」建第一份作業")


def add_example(app, root: Path) -> None:
    """加入範例課程：把 root/範例課程/科學計算 整個複製成 root/科學計算，每份作業和課那一層補上墊片。不蓋已有的。"""
    root = Path(root)
    src, dest = root / "範例課程" / EXAMPLE, root / EXAMPLE
    if not (src / MARK).is_file():
        app.log(f"找不到範例課程：{root.name}/範例課程/{EXAMPLE}/{MARK} 不在")
        return
    if dest.exists() or dest.is_symlink():
        app.log(f"已經有「{EXAMPLE}」了，沒有再加（不會蓋掉）")
        return
    try:
        course = read_course(src)
    except CourseError as exc:
        app.log(f"範例課程 {EXAMPLE}：{exc}")
        return
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
    for code, file in homeworks(course):
        write_stub(dest / file.parent.relative_to(src), code, *HOMEWORK_STUB)
    _course_buttons(dest, course.name)
    app.rescan()
    app.log(f"已加入「{course.name}」：{len(homeworks(course))} 份作業，不用裝；按它旁邊的 ▸ 進去")


def new_homework(app, course_folder: Path) -> None:
    """新增作業：問代號（預設＝課裡最大的號碼＋1）→ 建作業資料夾、<代號>.py（範本）、<代號>Space/ 和墊片 → 打開編輯器。
    不蓋已有的：代號的號碼課裡已經有（資料夾叫什麼都算）或資料夾已經在，都只說一句。"""
    course_folder = Path(course_folder)
    try:
        course = read_course(course_folder)
        if not course.types:
            raise CourseError("TYPES 是空的，不知道要用哪一種作業的範本")
        kind = load_type(course.types[0], HERE.parent)
    except CourseError as exc:
        app.log(f"{course_folder.name}：{exc}")
        return
    have = {code_number(course, code): file.parent.name for code, file in homeworks(course)}
    default = code_of(course, max(have, default=0) + 1)
    answer = app.ask("作業代號：", default)
    if answer is None:
        app.log("沒新增")
        return
    n = code_number(course, answer.strip())
    if n is None:
        app.log(f"認不出作業代號「{answer}」：要像 {default}（{course.code} 的 {{n}} 換成數字）")
        return
    code, folder = code_of(course, n), course_folder / folder_of(course, n)
    if n in have or folder.exists() or folder.is_symlink():
        app.log(f"已經有 {code}（資料夾 {have.get(n, folder.name)}）了，沒有新增（不會蓋掉）")
        return
    file = kind.new(folder, code)
    write_stub(folder, code, *HOMEWORK_STUB)
    app.edit(file)
    app.rescan()
    app.log(f"已新增 {code}：{folder.name}/{file.name}，編輯器打開了")
