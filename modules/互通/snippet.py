"""那一小段：直接執行模組的 iplot.py（python3 iplot.py）時交給 iPLoT 跑（python3 main.py --run，D84、D163）。

1.0 起加的是 iPLoT 自己的那一段（跟隨附模組的一字不差，全文在 docs/api.md，tests/test_interop.py 核對）；
互通 0.x 加過的舊的那一段（找互通的 run.py）照樣認得、照樣能用（run.py 轉給 main.py --run）。
核心 ＋ 的範本不帶它（D84 修訂）；要直接執行的模組，在「互通」的狀態頁按「加上」時加（iplot.py 的 patch，D87）。
這裡只管文字、找插入的位置、加上去、認得出來。改檔之前存一份快照（跟核心存的一樣，面板的「回到上一版」看得到）。"""

import ast
import hashlib
import io
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

NAME = re.compile(r"\d{4}-\d{2}-\d{2}_\d{6}(_\d+)?")  # 快照的檔名，跟核心的 core/history.py 一樣

MARK = "# ── 互通 ──"  # 互通 0.x 加的那一段（找互通的 run.py）：還認得，不再加
IPLOT_MARK = "# ── iPLoT ──"  # iPLoT 1.0 的那一段（找 main.py --run，D163）：1.0 起「加上」加的是這一段
TEXT = '''# ── iPLoT ── 直接執行這個檔（python3 iplot.py）時交給 iPLoT 跑（python3 main.py --run）；從 iPLoT 裡執行時這段不做事。不要可以整段刪掉
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
'''
BOM = b"\xef\xbb\xbf"


def _order(p: Path) -> tuple[str, int]:
    tail = p.stem[18:]  # 「2026-10-02_140905」之後的序號
    return p.stem[:17], int(tail) if tail.isdigit() else 0


def versions(file: Path) -> list[Path]:
    """file 的所有快照，新到舊。抄自核心的 core/history.py（規則 7：模組不 import 核心）。"""
    found = (p for p in (file.parent / ".history").glob("*.py") if NAME.fullmatch(p.stem))
    return sorted(found, key=_order, reverse=True)


def snapshot(file: Path, keep: int) -> Path | None:
    """存一份 file 的快照到旁邊的 .history/，跟最新一份一樣就不存；只留最新 keep 份。抄自核心的 core/history.py。"""
    data, old = file.read_bytes(), versions(file)
    if old and hashlib.sha256(old[0].read_bytes()).digest() == hashlib.sha256(data).digest():
        return None
    folder = file.parent / ".history"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    new, n = folder / f"{stamp}.py", 0
    while new.exists():
        n += 1
        new = folder / f"{stamp}_{n}.py"
    new.write_bytes(data)
    for extra in versions(file)[keep:]:
        extra.unlink()
    return new


def has(source: str) -> bool:
    """有沒有那一小段：有一行以記號開頭；互通 0.x 的舊的那一段與 iPLoT 1.0 的都算。"""
    return re.search(f"^(?:{re.escape(MARK)}|{re.escape(IPLOT_MARK)})", source, re.M) is not None


def where(source: str) -> int:
    """那一小段要插在第幾行（0 起算）：模組的 docstring、from __future__、以及開頭連續的 import 之後，其他程式之前。
    放在最外層程式之前，沒有 run 的模組（D47）直接執行時才不會先跑一次；放在開頭的 import 之後，
    那些 import 才不會變成「程式碼之後的 import」（ruff E402）。語法錯誤丟 SyntaxError。"""
    body, end = ast.parse(source).body, 0
    for i, node in enumerate(body):
        doc = (i == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
               and isinstance(node.value.value, str))
        if not (doc or isinstance(node, (ast.Import, ast.ImportFrom))):
            break
        end = node.end_lineno or node.lineno
    return end


def add(path: Path, keep: int) -> bool:
    """在 path（模組的 iplot.py）加上那一小段；已經有就回 False。改之前先存快照；
    保留原本的 BOM 與換行方式（runner 用 utf-8-sig 讀）。語法錯誤丟 SyntaxError，檔案不動。"""
    data = path.read_bytes()
    bom = data.startswith(BOM)
    text = data[len(BOM):].decode("utf-8") if bom else data.decode("utf-8")
    if has(text):
        return False
    at = where(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = io.StringIO(text, newline="").readlines()  # 跟 Python 一樣只認 \n、\r\n、\r（splitlines 還認換頁字元等）
    if at and not lines[at - 1].endswith(("\n", "\r")):
        lines[at - 1] += newline
    after_import = any(isinstance(n, (ast.Import, ast.ImportFrom)) and n.end_lineno == at for n in ast.parse(text).body)
    lines[at:at] = [(newline if after_import else "") + TEXT.replace("\n", newline)]  # 接在 import 後面空一行（ruff 的 I001）
    snapshot(path, keep)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")  # 先寫暫存再換上去：寫到一半失敗，原來的檔完好（體驗 7-05）
    try:
        tmp.write_bytes((BOM if bom else b"") + "".join(lines).encode("utf-8"))
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return True
