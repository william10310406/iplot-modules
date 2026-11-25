"""重新啟動 iPLoT：改了 core/ 或 config.py 之後按這顆，整個程式從頭再來（安全模式開的，重新啟動後還是安全模式）。"""

import os

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

ICON = "🔄"


NOT_HERE = "這裡沒有面板可以重新啟動：從 iPLoT 的面板按「重新啟動」。"


def run(app):
    if hasattr(app, "restart"):  # iPLoT 1.0 起：模組在自己的程序裡跑（D161），要請面板重新啟動，--safe 照舊（D166）
        try:
            return app.restart()
        except AttributeError:  # 不是面板開的（python3 main.py --run）
            return app.log(NOT_HERE)
    os.chdir(app.home)  # 執行期間的工作目錄是這個模組的資料夾；新的 iPLoT 要從自己的資料夾起來
    try:
        os.execv(sys.executable, [sys.executable, str(app.home / "main.py")])
    except OSError:  # 換不了程序（例如 Python 被搬走了）：舊的面板還在，照常用
        app.log("沒有重新啟動。請關掉 iPLoT（視窗和終端機都關），再開一次。")
