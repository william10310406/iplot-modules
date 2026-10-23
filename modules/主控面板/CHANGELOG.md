# Changelog

「主控面板」這個模組的版本紀錄，格式跟 iPLoT 的 CHANGELOG.md 一樣（[Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)）。`tools/publish.py` 取最上面那一節的版本號當工作坊裡的版本，取那一節的第一段當清單頁上的「這一版」。

## [0.1.0] - 2026-10-07

第一版：打開 iPLoT 的面板；已經開著就叫到最前面。任何模組寫 `app.run("主控面板")` 就會用到這裡；在面板外（「互通」的捷徑、指令）也一樣。叫到最前面只在 macOS；別的系統一律開一個新的面板。
