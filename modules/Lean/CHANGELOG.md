# Changelog

「Lean」這個模組的版本紀錄，格式跟 iPLoT 的 CHANGELOG.md 一樣（[Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)）。`tools/publish.py` 取最上面那一節的版本號當工作坊裡的版本，取那一節的第一段當清單頁上的「這一版」。

## [0.1.0] - 2026-11-10

第一版：按下去用瀏覽器打開「Lean 實數遊戲」——只用 Lean，從自然數一路蓋到實數，再證不等式與極限（遊戲內容是英文）。遊戲跑在 adam.math.hhu.de 的公開伺服器上，需要網路、不用安裝；進度存在瀏覽器裡。

### 新增
- 按下去先在訊息區說一兩句這是什麼、需要網路、不用安裝、進度存在瀏覽器裡，再試著連 adam.math.hhu.de（8 秒逾時）；連不上就說一句原因、不開任何東西，不丟錯誤。
- 連得上就用系統的瀏覽器打開遊戲。一律用瀏覽器，不在 iPLoT 的視窗裡玩：iPLoT 的頁面不載入外部內容（docs/07），而且 iPLoT 的頁面視窗不留網站資料，關掉視窗進度就不見。瀏覽器打不開時，把網址寫在訊息區給人複製。
- 模組不用 `app.page`，網頁面板、安全模式與後備的 tkinter 面板上行為一樣。
- 遊戲的原始碼在 https://github.com/william10310406/reals-game。
