REQUIRES = ["numpy", "matplotlib"]                       # 用了別的套件就加在這；自己跑一次會自動補
import coursework; coursework.ensure(REQUIRES, __file__)  # 缺的在這一行裝好，裝完才往下 import
import numpy as np
from pathlib import Path
from matplotlib.animation import FuncAnimation

# ── 從這裡開始是作業 ──
NAME = "HK1 範例：一顆球繞圓"                            # 頁面標題
DOCS = [("Uniform circular motion", "https://en.wikipedia.org/wiki/Circular_motion")]
NOTE = """筆記寫這裡。純文字。"""
DATA = Path(__file__).resolve().parent / "HK1Space"      # 資料檔放這個資料夾；沒有資料檔就刪掉這行
CASES = {
    "case-1": dict(r=1.0, w=1.0, label="半徑 1、角速度 1"),
    "case-2": dict(r=2.0, w=0.5, label="半徑 2、角速度 0.5"),
}

def compute(case):
    """算。純計算、不畫圖、不開視窗；回一個 dict，畫圖和數字都從它拿。"""
    p = CASES[case]
    t = np.linspace(0, 2 * np.pi / p["w"], 200)
    return {"t": t, "x": p["r"] * np.cos(p["w"] * t), "y": p["r"] * np.sin(p["w"] * t)}

def draw(fig, run):
    """畫。在給你的 fig 上畫；要動畫就回傳 FuncAnimation，靜態圖回 None；不要畫圖的話，整個函式換成一行 draw = None。"""
    ax = fig.add_subplot(111)
    ax.set_aspect("equal"); ax.set_xlim(-2.2, 2.2); ax.set_ylim(-2.2, 2.2)
    ax.plot(run["x"], run["y"], lw=0.8, alpha=0.4)
    dot, = ax.plot([], [], "o")
    def update(i):
        dot.set_data([run["x"][i]], [run["y"][i]])
        return (dot,)
    return FuncAnimation(fig, update, frames=len(run["t"]), interval=30, blit=False)

def stats(run):
    """幾個數字，頁面照順序列；不要的話整個函式換成一行 stats = None。"""
    return [("週期 T", f"{run['t'][-1]:.3f}"), ("點數", str(len(run["t"])))]

# ── 以下不用改 ──
HOMEWORK = dict(name=NAME, docs=DOCS, note=NOTE, cases=CASES, compute=compute, draw=draw, stats=stats, file=__file__)
if __name__ == "__main__":
    raise SystemExit(coursework.main(HOMEWORK))
