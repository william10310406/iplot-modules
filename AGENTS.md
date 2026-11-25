# 寫 iPLoT 模組的規則（給寫程式的 AI 助手，也給人）

這個 repo 是 iPLoT 的工作坊：大家上傳的模組都在 `modules/`。Claude、ChatGPT、Gemini、Copilot、Cursor 等助手：
幫人寫要上傳到這裡的模組之前，先照這份做。`CLAUDE.md`、`GEMINI.md` 只是指到這裡。

下面「寫模組」這一節是從 iPLoT 的 AGENTS.md 逐字抄來的（`tests/test_agents_md.py` 拿隔壁的 iPLoT 核對）；
iPLoT 本身的規則（核心、面板怎麼改）在 iPLoT 的 repo。名詞：**模組**是一個有 `iplot.py` 的資料夾，`app` 是 iPLoT 交給模組的那個物件。

收件機器人（`tools/receive.py`）跑的是 iPLoT 的同一支檢查（`tools/check_deps.py`，也是逐字抄的）。

## 一、寫模組（每個人都要守）

上傳到工作坊（iplot-modules）的模組，收件時會跑同一套檢查：iPLoT 維護者的模組違規就退回；別人上傳的只警告、寫在清單上，遵不遵守由你決定，但不守的模組很可能在下一版 iPLoT 壞掉。

**1. 只透過 `app` 碰 iPLoT。不准 import `core`、`ui` 的任何東西。**（R2，`tests/test_module_deps.py::test_no_new_violations`）

```python
# 可以
def run(app):
    app.log("完成")
    folder = app.module.folder

# 不可以
from core import scan          # 核心的內部，下一版就可能改名
from core.types import ModuleInfo
```

**2. 不准用名字或檔案路徑碰別的模組。要用別的模組的功能，用角色：`app.call`、`app.each`、`app.providers`。**（R1）

```python
# 可以：問「誰提供 page.top」，核心不知道、也不在乎是哪個模組
bar = app.call("page.top", app.module)

# 不可以：寫死別的模組的名字或路徑
path = app.home / "modules" / "互通" / "separate.py"
subprocess.Popen([sys.executable, str(app.home / "modules" / "行事曆" / "iplot.py")])
```

要提供功能給別人用，在 `iplot.py` 頂層宣告 `PROVIDES = {"角色": "函式名"}`（字面值，核心只用 ast 讀，不執行）：

```python
PROVIDES = {"menu.module": "items"}   # 右鍵選單多幾項

def items(app, info):
    return [("改名…", "rename")]
```

從工作坊裝來的模組宣告角色，第一次會先問使用者允不允許（D159）。

**3. 用到的角色或模組，都要寫在 `iplot.py` 頂層的 `NEEDS`。可有可無的也要寫。**（R5）

```python
# 可以
NEEDS = ("page.top", "互通")

# 不可以：程式裡用了 app.call("page.top")，NEEDS 沒寫
```

列一份名單（三個以上模組名字的 tuple／list／set，例如「隨附的有哪些」）只是列名字，不算用到。

**4. 不准猜自己在哪個環境：不看 `sys.modules` 裡有沒有 `"ui.web"`、`"ui.tk"`，不猜固定路徑。**（R3）
唯一的例外是模組檔頭的「那一小段」（`"core.runner" in sys.modules`）：iPLoT 永久保留 `core.runner` 這個名字給它用。

**5. 第三方套件只能這三種用法；不管哪一種，都不准 import 套件的內部（`_` 開頭，或 `platforms`、`internal`、`vendor`、`backends` 這類子模組）。**（R4）

```python
# 可以 (一)：包在 try 裡，而且沒有它也能跑
try:
    import numpy
except ImportError:
    numpy = None

# 可以 (二)：頂層宣告 REQUIRES，自己負責裝（課程作業的做法）
REQUIRES = ["numpy", "matplotlib"]

# 不可以
import webview.platforms.cocoa   # 套件的內部，套件一升版就壞
import requests                  # 沒有退路、也沒宣告
```

**6. 另開程序要確認它真的起來了；不准把它的錯誤輸出丟掉（`stderr=subprocess.DEVNULL`）。**（R11）
丟出去就回「成功」，對方失敗時沒有任何人知道。做法：錯誤輸出接到 `logs/separate.log`，等一下看它有沒有馬上出錯結束（抄 `modules/行事曆/iplot.py` 的 `_spawn`）；等不到就跟使用者說一句，自己在這裡做。

**7. 要別的模組的小工具，寧可抄一份也不要依賴它；抄的時候註明出處。**（人工；在 iPLoT 的 repo 裡由 `tests/test_copies.py` 擋：沒登記的抄本會紅）

**8. 用到 `app` 在 `api_version` 4 以後才有的東西（`app.call`、`app.each`、`app.providers` 是 5，`app.start` 是 6），要嘛先 `hasattr(app, "call")` 判斷，要嘛頂層宣告 `MIN_API = 5`（iPLoT 1.0 起不夠新就不跑、會請使用者更新）。**（人工）
使用者的 iPLoT 不一定是最新版。

**9. 每台電腦自己的東西（設定、快取、`.pid`、登入資訊）不准放進上傳的包。**（工作坊收件時退回）
現在的做法：寫在模組資料夾的點檔或 `設定.json`，並在 `.gitignore` 加一行。1.0 起統一放 `.local/`。

**10. 畫面上的文字寫給一般人看：中文、完整句子、說出下一步怎麼辦。錯誤要說清楚發生什麼、使用者可以做什麼。**（人工）

**11. 改了模組，就在它的 `CHANGELOG.md` 最上面加一節、升版本號。**（隨附模組：`tools/bundled_hashes.py --check` 與 `tests/test_bundled_update.py`）

## 這個 repo 自己

- 機器人與網站的程式在 `tools/`，改之前先跑 `python3 -m pytest -q`。
- 從 iPLoT 抄來的檔（`tools/iplot_rules.py`、`tools/check_deps.py`、`tools/deps_allow.json`、這份的「寫模組」一節）不准只改這邊：先改 iPLoT，再抄過來。
- 不准自己合併、發佈、刪模組或回覆別人的 issue：這些都要 William 先說好。
