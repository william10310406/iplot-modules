# Changelog

「行事曆」這個模組的版本紀錄，格式跟 iPLoT 的 CHANGELOG.md 一樣（[Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)）。`tools/publish.py` 取最上面那一節的版本號當工作坊裡的版本，取那一節的第一段當清單頁上的「這一版」。

## [0.1.1] - 2026-10-15

修正「發佈」：取消最後一個公開的日子之後再按「發佈」，上一次產生的 發佈/ 會整個拿掉，狀態列說「沒有公開的日子了，已經拿掉 發佈/」；之前只說「還沒有打開「公開」的日子」，發佈/ 裡還留著剛取消公開的那幾天，照著再上傳就會把它們留在網路上。

### 修正
- 公開的日子是 0 天、而 `發佈/` 存在時，「發佈」把 `發佈/` 整個拿掉（`pages.unpublish`）；`發佈/` 本來就不在時跟以前一樣，只說「還沒有打開「公開」的日子」、不產生任何東西（`tests/test_calendar.py::test_publish_after_the_last_public_day_is_unpublished_removes_the_publish_folder`、`::test_publish_with_no_public_day_and_no_publish_folder_creates_nothing`）。

## [0.1.0] - 2026-10-14

第一版：打開就是這個月的月曆，每天寫行程、心情、看到了什麼、做了什麼，放照片；全部存成一天一個資料夾（預設 ~/Documents/行事曆），並產生成網頁（綜合、年、月、日）；打開「公開」的日子，按「發佈」另外產生一份可以放上網路的 發佈/（照片縮小、拿掉拍攝地點，不會幫忙上傳）。上方的模組列叫得到任何模組，任何模組寫 app.run("行事曆") 就叫得到它。需要「互通」；只在 macOS 驗過。

### 新增
- 月、年、日三個檢視；四個欄位離開輸入框或打字停 1 秒就存；五個表情；「加圖片」與拖放，HEIC 另外轉一張 JPG（macOS）；畫面上的縮圖用 `sips -Z 320` 做到那一天的 `.縮圖/`。
- 資料（`diary.py`，D90）：一天一個資料夾、純文字加圖片、`公開` 標記；覆寫之前舊的存進 `.history/`（同一個欄位 10 分鐘內只存一份）；先寫暫存檔再換上去；不是 UTF-8 的檔不覆寫。
- 網頁（`pages.py`，D91；設計原文叫 `site.py`，跟 Python 標準庫的 `site` 同名，改名）：日、月、年、綜合；存一天連前後有內容的日子與相鄰的月一起重產；公開版只放公開的日子、每頁 noindex、照片的中繼資料用白名單拿掉（到影像結尾為止）。
- 程序（`iplot.py`，D89）：頁面只在自己另開的程序裡開（經「互通」的 `run.py`），已經開著就叫到最前面；模組列在頁面載入與視窗拿到焦點時重掃；Dock 圖示換成 `icon.png`（macOS）。
- 量出來的數字：`tests/test_calendar.py` 102 個測試；有效行 `diary.py` 198、`photos.py` 163、`pages.py` 261、`iplot.py` 313（含「互通」那一小段 22 行），`page.html` 395 行。

### 這一版沒有做
- 上傳到網頁空間（只留 `pages.publish(root)` 這個接口，D92）；匯入 DavidSPACE 的舊資料；筆記裡寫到的模組名稱變成按鈕；週檢視；提醒與通知；搜尋；重複的行程；iPLoT 啟動時自動打開行事曆；多台電腦同步。
- Windows、Linux：HEIC 轉檔、照片縮小、叫到最前面、Dock 圖示只在 macOS 做；Windows 未經實機驗證。
