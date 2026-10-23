"""那一小段：直接執行模組的 iplot.py（python3 iplot.py）時交給「互通」用彈出式視窗跑（D84）。

文字是「互通」自己的，到 1.0.0 一字不改（tests/test_interop.py 用 sha256 擋）：已經加過的模組才認得出來。
核心 ＋ 的範本不帶它（D84 修訂）；要直接執行的模組，在「互通」的狀態頁按「加上」時加（iplot.py 的 patch，D87）。
這裡只管文字、找插入的位置、加上去、認得出來。"""

import ast
import io
import re
from pathlib import Path

from core.history import snapshot

MARK = "# ── 互通 ──"
TEXT = '''# ── 互通 ── 直接執行這個檔（python3 iplot.py）時交給 iPLoT 用彈出式視窗跑；從 iPLoT 裡執行時這段不做事。不要可以整段刪掉
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
'''
BOM = b"\xef\xbb\xbf"


def has(source: str) -> bool:
    """有沒有那一小段：有一行以記號開頭。"""
    return re.search("^" + re.escape(MARK), source, re.M) is not None


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
    path.write_bytes((BOM if bom else b"") + "".join(lines).encode("utf-8"))
    return True
