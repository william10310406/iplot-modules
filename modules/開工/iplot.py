"""每日入口：一鍵打開 iPLoT 資料夾、docs/、設計文件和終端機，然後開工。"""
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
ICON = "🧭"


def run(app):
    docs = app.home / "docs"
    design = docs / "02_重構設計.md"
    app.open(app.home)
    app.open(docs)
    app.edit(design)
    app.terminal(app.home)
    gone = [p.name for p in (docs, design) if not p.exists()]  # 沒有的那幾個，作業系統模組已經各說了一句；這一行不能說「都開了」
    app.log("開工：iPLoT 資料夾、docs、設計文件、終端機都開了" if not gone else f"開工：{'、'.join(gone)} 找不到，其餘都開了")
