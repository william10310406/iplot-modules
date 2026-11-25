"""模組依賴規則的檢查（D160，規則全文在 AGENTS.md）：只用 ast 讀，不執行任何模組。

    python3 tools/check_deps.py            # 列出現在的違規，標出哪些不在白名單上（新的）
    python3 tools/check_deps.py --write    # 把現在的違規整份寫成白名單（只在第一次上線、或確定要接受時用）

查的規則：
- R1 用名字碰別的模組：程式碼裡（不含 docstring）有一個字串剛好是另一個模組的名字（用檔案路徑載入、Popen 它的檔、
  靠名字找它都會這樣）。要用別的模組的功能，0.8 起用角色（app.call、app.providers）。
- R2 模組 import 核心的內部（core.*）。
- R3 用 sys.modules 的名字或固定路徑猜環境（"core.runner"、"ui.web"、"ui.tk"）。
- R4 第三方套件：不是標準庫、不是自己資料夾裡的檔、不是 core／ui，又不在 try/except ImportError 裡、模組也沒宣告 REQUIRES；
  另外，不管有沒有包在 try 裡，都不准 import 套件的內部（_ 開頭，或 platforms、internal、vendor、backends 這類子模組，
  例如 webview.platforms.cocoa）。
- 三個以上模組名字的名單（tuple、list、set 的字面值，例如「隨附的有哪些」）只是列名字，R1、R5 都不算。
- 模組自己裡面也有一個資料夾叫這個名字（例如課程作業的範例課程「科學計算」）：說的是自己的檔，R1、R5 都不算。
- R5 依賴要寫明：用到別的模組的名字（R1 那種字串），或用 app.call／each／providers 叫一個角色，那個名字或角色都要列在
  iplot.py 頂層的 NEEDS = ("角色或模組名", ...) 裡。
- R11 另開程序把錯誤輸出丟掉：任何呼叫帶 stderr=subprocess.DEVNULL（D160 第 3 條）。另開的程序失敗了要有人知道：
  接到 logs/separate.log，並確認它起來了（行事曆、主控面板的 _spawn，互通的 separate.here）。
- R6 核心與面板（modules/核心/ 的 core/、ui/）出現模組的名字。這兩個資料夾是核心本身，不當成模組的程式碼查；
  「核心」模組自己的 iplot.py 照一般模組查。iPLoT 資料夾的 main.py 是凍結的開機程式（D167），它本來就要知道核心在哪。
iplot-modules 收件時跑同一份（tools/check_deps.py 與 tools/deps_allow.json 逐字抄過去）：維護者的模組有新的違規就退回，
別人的只警告（AGENTS.md 第一節）。
白名單在 tools/deps_allow.json：每一筆是現在已經有的違規，寫著預定哪一版拿掉。tests/test_module_deps.py 擋兩件事：
不在白名單上的新違規，與白名單上已經不存在的舊項目（拿掉了就要從白名單刪掉）。"""

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW = ROOT / "tools" / "deps_allow.json"
ENVIRONMENT = {"core.runner", "ui.web", "ui.tk"}
STDLIB = set(sys.stdlib_module_names) | {"__future__"}
KERNEL = ROOT / "modules" / "核心"  # 核心本身（D167）


def kernel_files() -> list[Path]:
    """核心本身的程式：R6 查這些，R1～R5 不查（它們就是核心）。"""
    return sorted([*(KERNEL / "core").glob("*.py"), *(KERNEL / "ui").glob("*.py")])


def module_names() -> set[str]:
    return {p.name for p in (ROOT / "modules").iterdir() if p.is_dir() and not p.name.startswith((".", "_"))}


def _docstrings(tree: ast.AST) -> set[int]:
    return {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}


def _guarded(tree: ast.AST) -> set[int]:
    """在 try/except ImportError（或 Exception、裸的 except）裡的 import。"""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            names = {ast.unparse(h.type) if h.type else "" for h in node.handlers}
            if names & {"", "ImportError", "ModuleNotFoundError", "Exception", "(ImportError, OSError)"} or any(
                    "ImportError" in n for n in names):
                found |= {id(n) for stmt in node.body for n in ast.walk(stmt)}
    return found


def _catalogs(tree: ast.AST, names: set[str]) -> set[int]:
    """名單：三個以上模組名字的 tuple／list／set 字面值（例如「隨附的有哪些」）。列名字不是用到它們，R1、R5 不算。"""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            hits = [e for e in node.elts if isinstance(e, ast.Constant) and e.value in names]
            if len(hits) >= 3:
                found |= {id(e) for e in hits}
    return found


INTERNAL = {"platforms", "internal", "vendor", "backends"}  # 套件裡常見的內部子模組名；另外，_ 開頭的也算


def _internal(mod: str) -> bool:
    return any(part.startswith("_") or part in INTERNAL for part in mod.split(".")[1:])


def _local(name: str, top: Path) -> bool:
    """name 是不是這個模組自己資料夾（含子資料夾）裡的 .py 或套件。"""
    return any(top.rglob(f"{name}.py")) or any(p.is_dir() for p in top.rglob(name))


def _requires(top: Path) -> bool:
    """模組有沒有哪個檔在頂層宣告 REQUIRES（自己負責裝第三方套件）。"""
    for path in top.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError, ValueError):
            continue
        if any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "REQUIRES" for t in n.targets)
               for n in tree.body):
            return True
    return False


ROLE_CALLS = {"call", "each", "providers", "run_role"}


def needs(top: Path) -> set[str]:
    """iplot.py 頂層 NEEDS 的字串（tuple、list、set 的字面值；別的寫法當作沒寫）。"""
    try:
        tree = ast.parse((top / "iplot.py").read_text(encoding="utf-8-sig"))
    except (OSError, SyntaxError, ValueError):
        return set()
    for node in tree.body:
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "NEEDS" for t in node.targets)
                and isinstance(node.value, (ast.Tuple, ast.List, ast.Set))):
            return {e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def _role(node: ast.AST) -> str | None:
    """x.call("角色", …) 這類呼叫的角色字串。"""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ROLE_CALLS
            and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
        return node.args[0].value
    return None


def scan_module(top: Path, names: set[str]) -> list[tuple[str, str, str]]:
    """一個模組（modules/ 底下最上層的資料夾）的違規：（規則, 相對路徑, 是什麼）。"""
    found, requires, declared = [], None, needs(top)
    kernel = set(kernel_files()) if top == KERNEL else set()
    own = {p.name for p in top.rglob("*") if p.is_dir()}  # 自己裡面的資料夾：同名的字串說的是自己的檔
    others = names - {top.name} - own
    for path in sorted(top.rglob("*.py")):
        if "__pycache__" in path.parts or path in kernel or ".local" in path.relative_to(top).parts:
            continue
        rel = f"modules/{path.relative_to(top.parent).as_posix()}"  # 收件時模組在別處，一樣寫成 modules/<名字>/…
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (SyntaxError, ValueError):
            continue
        docs, guarded, catalogs = _docstrings(tree), _guarded(tree), _catalogs(tree, names)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                if node.value in others and id(node) not in catalogs:
                    found.append(("R1", rel, node.value))
                    if node.value not in declared:
                        found.append(("R5", rel, node.value))
                if node.value in ENVIRONMENT:
                    found.append(("R3", rel, node.value))
            if isinstance(node, ast.Call) and any(k.arg == "stderr" and ast.unparse(k.value).endswith("DEVNULL")
                                                  for k in node.keywords):
                found.append(("R11", rel, f"{ast.unparse(node.func)}(stderr=DEVNULL)"))
            if (role := _role(node)) is not None and role not in declared:
                found.append(("R5", rel, role))
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module] if node.module != "core" else [f"core.{a.name}" for a in node.names]
            for mod in mods:
                head = mod.split(".")[0]
                if head in ("core", "ui"):
                    found.append(("R2", rel, mod))
                elif head in STDLIB or _local(head, top):
                    continue
                elif _internal(mod):
                    found.append(("R4", rel, mod))
                elif id(node) not in guarded:
                    requires = _requires(top) if requires is None else requires
                    if not requires:
                        found.append(("R4", rel, mod))
    return found


def scan_seed(names: set[str]) -> list[tuple[str, str, str]]:
    """R6：核心本身（kernel_files）裡剛好是模組名字、或含 modules/<名字> 的字串（docstring 不算）。"""
    found = []
    for path in kernel_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = _docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                found += [("R6", path.relative_to(ROOT).as_posix(), n) for n in sorted(names)
                          if node.value == n or f"modules/{n}" in node.value]
    return found


def new_in(folder: Path, names: set[str]) -> list[tuple[str, str, str]]:
    """別處的一個模組（工作坊收件時用，iplot-modules 的 tools/receive.py）：不在白名單上的違規。"""
    ok = allowed()
    return [v for v in scan_module(folder, names | {folder.name}) if v not in ok]


def violations() -> list[tuple[str, str, str]]:
    names = module_names()
    found = [v for n in sorted(names) for v in scan_module(ROOT / "modules" / n, names)] + scan_seed(names)
    return sorted(set(found))


def allowed() -> dict[tuple[str, str, str], str]:
    data = json.loads(ALLOW.read_text(encoding="utf-8")) if ALLOW.is_file() else []
    return {(e["rule"], e["file"], e["what"]): e for e in data}


def main() -> int:
    found = violations()
    if "--write" in sys.argv[1:]:
        old = allowed()
        blank = {"until": "待定", "why": ""}
        rows = [{"rule": r, "file": f, "what": w, **{k: old.get((r, f, w), blank)[k] for k in blank}} for r, f, w in found]
        ALLOW.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"寫了 {ALLOW}（{len(rows)} 筆）")
        return 0
    ok = allowed()
    new = [v for v in found if v not in ok]
    for rule, file, what in found:
        print(f"{'新 ' if (rule, file, what) in new else '   '}{rule} {file}: {what}")
    gone = [k for k in ok if k not in set(found)]
    for rule, file, what in gone:
        print(f"已經沒有了，請從白名單刪掉：{rule} {file}: {what}")
    return 1 if new or gone else 0


if __name__ == "__main__":
    sys.exit(main())
