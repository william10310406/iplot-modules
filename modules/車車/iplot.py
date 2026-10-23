"""車車：按一下，一台顏文字的車車從畫面左邊開到右邊。測試工作坊上傳用的小模組。

網頁面板另開一個視窗看它開過去（按「再一台」再開一次）；安全模式與 tkinter 面板沒有頁面，就在訊息區畫出來；
直接在終端機打 python3 iplot.py，就在終端機裡開過去。"""
import shutil
import sys
import time

ICON = "🚗"

CAR = [
    "          ______",
    "    _____/(•ω•)|\\____",
    "ε=ε=|   _      _    |",
    "    '--(_)----(_)---'",
]

PAGE = """<!doctype html>
<meta charset="utf-8">
<style>
  body { margin: 0; height: 100vh; overflow: hidden; display: flex; flex-direction: column;
         justify-content: center; background: #1d2330; color: #f5f1e6; font-family: -apple-system, sans-serif; }
  .road { position: relative; height: 150px; border-bottom: 6px dashed #f2c94c; }
  .car { position: absolute; bottom: 4px; left: 0; margin: 0; font: 20px/1.15 Menlo, monospace;
         white-space: pre; transform: translateX(-110%); }
  .car.go { animation: drive 4s linear forwards, bump .3s ease-in-out infinite alternate; }
  @keyframes drive { to { left: 100%; transform: translateX(10%); } }
  @keyframes bump { to { bottom: 7px; } }
  .bar { display: flex; gap: 12px; align-items: center; justify-content: center; margin-top: 28px; }
  button { font-size: 15px; padding: 6px 16px; border-radius: 8px; border: 0; background: #f2c94c; cursor: pointer; }
  #honk { min-width: 4em; }
</style>
<div class="road"><pre class="car" id="car"></pre></div>
<div class="bar"><button id="again" type="button">再一台</button><span id="honk"></span></div>
<script>
const car = document.getElementById("car");
const honk = document.getElementById("honk");
car.textContent = CAR_TEXT;
function go() {
  car.classList.remove("go");
  void car.offsetWidth;  // 重新觸發動畫
  car.classList.add("go");
  honk.textContent = "叭叭！";
  setTimeout(() => { honk.textContent = ""; }, 1200);
}
document.getElementById("again").addEventListener("click", go);
go();
</script>"""


def run(app):
    """按下時：網頁面板開一個視窗看車車開過去，關掉之後在訊息區留一台。"""
    import json

    app.page("車車", PAGE.replace("CAR_TEXT", json.dumps("\n".join(CAR))))
    for line in CAR:
        app.log(line)
    app.log("叭叭！車車開過去了")


def drive(delay: float = 0.03) -> None:
    """在終端機裡從左開到右：每一格把四行重畫一次，再把游標移回四行前。"""
    width = shutil.get_terminal_size((80, 20)).columns - 1
    wide = max(len(line) for line in CAR)
    print("\n" * (len(CAR) - 1))
    try:
        for x in range(-wide, width + 1):
            rows = [(" " * x + line)[:width] if x >= 0 else line[-x:][:width] for line in CAR]
            sys.stdout.write(f"\x1b[{len(CAR)}F" + "".join(f"\x1b[2K{row}\n" for row in rows))
            sys.stdout.flush()
            time.sleep(delay)
    except KeyboardInterrupt:
        pass
    print("叭叭！車車開過去了")


if __name__ == "__main__" and "core.runner" not in sys.modules:  # 在 iPLoT 裡執行時 __name__ 也是 "__main__"
    drive()
