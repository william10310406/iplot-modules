# Changelog

「行事曆 2」這個模組的版本紀錄，格式跟 iPLoT 的 CHANGELOG.md 一樣（[Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)）。`tools/publish.py` 取最上面那一節的版本號當工作坊裡的版本，取那一節的第一段當清單頁上的「這一版」。

## [0.1.0] - 2026-11-08

第一版：從「行事曆」0.1.1 複製來的另一個模組，可以跟舊的分開開、互不干擾；在月、年、日檢視上多顯示 LINE bot 的資料（心情、行程、待辦、小記、做了什麼），預設只能看；按「複製進我的日記」（或在 ⚙ 打開「自動複製」）才會把它接在你自己的日記後面。⚙ 可以貼上、更換、清除 LINE 網址，有「立刻更新」與上次更新的時間。**日記資料夾跟舊的行事曆是同一個（預設 ~/Documents/行事曆）：新舊兩個不要同時開著寫同一天**（後存的會蓋掉先存的）。

### 新增
- **LINE 的資料**（依 LINE bot 的 `iPLoT-資料格式.md` version 1）：`line_url.py`（網址檢查與遮罩）、`line_net.py`（`urllib`、只 GET、逾時 15 秒、最多 2 MiB、不跟轉址、錯誤都是一句話且不含網址）、`line_data.py`（解析、型別嚴格、不認得的欄位忽略、台北時間、整天活動含最後一天）、`line_cache.py`（`line_cache.json`，按段存、保留每筆 id）、`line_view.py`（月、年、日的顯示與心情的優先順序）、`line_sync.py`（背景執行緒、429 照 `Retry-After` 等、翻頁才補抓）。
- **畫面**：月、年、日都有 LINE 的部分（淡綠色左邊線＋「LINE」標籤，唯讀）；待辦 ☐／☑；心情我選了表情就用我的，沒選才顯示 LINE 的（標「LINE」）；頂端的 LINE 記號（✓ 時間／⚠ 原因）；⚙ 的 LINE 區（遮過的網址、貼上／更換、清除、立刻更新、上次更新、自動複製）。
- **複製進日記**（`line_copy.py`）：預覽、你按確定才寫；接在原本的內容後面不覆蓋（心情只填還沒填的）；寫之前一定先存 `.history/` 快照（`diary.save_day(..., force_snapshot=True)`）；已複製的記在 `line_copied.json`，不重複；這天勾了「公開」時預覽有警告、私人項目略過。
- **自動複製**：⚙ 的開關，**預設關**；打開後每次打開行事曆（抓到最新資料之後）做一次，從「做到哪一天」的隔天到昨天，一次最多補 35 天；私人項目一律略過、「公開」的日子整天不自動複製、不碰頁面正在看的那一天、寫不進去就停下來下次再試。
- **設定檔**（`settings.py`）：讀出來、改一個鍵、寫回去，不認得的鍵原樣保留（之後要加寫入金鑰不用改格式）；權限 0600。
- 新的 `icon.png`（藍色月曆；純 Python 產生）、`ICON = "🗓"`；`LICENSE`（MIT，從「行事曆」原樣複製）、`.gitignore`、`ruff.toml`、`pytest.ini`。
- 文件在 `docs/`：`01_設計.md`、`02_實作計畫.md`、`03_手動驗證.md`。

### 修改（跟「行事曆」0.1.1 不一樣的地方）
- **只開一個的機制**：`.pid` 還是各自資料夾裡的（本來就分開）；環境變數 `IPLOT_CALENDAR` → `IPLOT_CALENDAR_LINE`；`running_pid` 找自己的程序改成「指令的**結尾**是這個資料夾」（舊的「含有」會把路徑是它前綴的程序誤認，「行事曆」是「行事曆 2」的前綴）；Dock 圖示、`ICON` 換新的。
- 視窗標題、`page.html` 的 `<title>`、「打開…／已經開著」的訊息都讀資料夾的名字（改資料夾名不用改程式）；沒有 `TITLE`（跟舊的一樣，按鈕字用資料夾名）。
- `diary.py` 三個函式：`save_root`（只改「資料夾」這一個鍵，不洗掉 `LINE` 區）、`snapshot`（多一個 `force`）、`save_day`（多一個 `force_snapshot`）。其他函式一個字沒改（`tests/test_untouched.py` 用複製當天的函式雜湊證明）；`pages.py`、`photos.py` 逐位元組相同。
- `Api` 多 7 個方法（`line_state`、`line_refresh`、`line_set_url`、`line_clear`、`line_set_auto`、`line_copy_preview`、`line_copy`），共 22 個；`month`、`year`、`day` 的回傳多一個 `line`；`_lock` 改成 `RLock`。

### 注意
- **網址等於密碼。** 只存在這個資料夾的 `設定.json`（0600）；畫面、訊息區、錯誤訊息、log 只出現遮過的（`https://<網域>/j/AbCd…wXyZ.json`）；不寫進任何 `.py`（`.py` 會被存進 `.history/`）。只接受 `https://` 開頭、路徑是 `/j/<token>.json` 的網址，其他一律拒絕並說要私訊 bot「連上iPLoT」拿網址。
- **上傳或發佈這個模組之前，先把 `設定.json`、`line_cache.json`、`line_copied.json`、`.pid` 搬走。** 工作坊與 `tools/publish.py` 打包時只略過 `.history`、`.origin`、`.unconfirmed`、`__pycache__`、`.ds_store`，不會略過它們。`tests/` 與 `docs/` 也會進包，裡面只有明顯是假的 token。
- 「發佈」與 `pages.py` 產生的網頁**沒有任何 LINE 的內容**；只有你按了「複製進日記」（或打開自動複製）之後，那些字才成為你日記的一部分，網頁照常會有。勾了「公開」的日子，複製進去的字會跟著「發佈」放上網路（手動複製時預覽有警告、私人項目略過；自動複製不碰公開的日子）。
- 複製之後，待辦才完成的、LINE 上才改的，不會再複製一次（已複製的記的是 id 與日期）。
- 小視窗（「互通」）跑完別的模組之後的「回去」鈕，只認名字剛好是「行事曆」的模組：從「行事曆 2」的模組列開別的模組，那顆鈕會回到舊的行事曆。這在「互通」那邊，這個模組改不了。
- 「互通」每次跑完模組都會同步捷徑（寫它自己的 `捷徑/`、`.lock`、`.sync-error`、`.python`）；這是它自己的行為。
- 量出來的數字：`tests/` 797 個測試、16 個測試檔、有效行 3016；有效行 `iplot.py` 401（舊 314，含「互通」那一小段 22 行）、`diary.py` 199（舊 198）、`pages.py` 271、`photos.py` 163、`settings.py` 35、`line_url.py` 39、`line_data.py` 168、`line_net.py` 156、`line_cache.py` 131、`line_view.py` 111、`line_sync.py` 219、`line_copy.py` 210，`page.html` 684 行；`ruff` 0 個警告（舊檔在這份規則下有 2 個 `S603`、`S607`，都是 `_ps()` 用清單叫 `ps`，D50 允許，已關掉）。只在 macOS 驗過；用瀏覽器接真的 `Api` 與 `page.html` 驗過畫面，在真正的面板裡雙擊開它還沒驗（步驟在 `docs/03_手動驗證.md`）。

### 這一版沒有做
- 從 iPLoT 寫回 LINE bot（設計文件最後一節寫了之後要改哪裡）；圖片（LINE 那邊這一版也不提供）。
- 沒有截止日的待辦的顯示（只存進快取，L12）。
- 固定時間的自動複製（只有「每次打開一次」；iPLoT 沒有常駐程式，行事曆沒開就不會跑，下次打開時補）。
- 偵測並阻擋新舊行事曆同時寫同一天（只在說明裡警告）；改舊行事曆或「互通」。
- Windows、Linux 的 HEIC 轉檔、照片縮小、叫到最前面、Dock 圖示（跟舊的一樣只在 macOS）；Windows 未經實機驗證。
