# Changelog

「重新啟動」這個模組的版本紀錄，格式跟 iPLoT 的 CHANGELOG.md 一樣（[Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)）。`tools/publish.py` 取最上面那一節的版本號當工作坊裡的版本，取那一節的第一段當清單頁上的「這一版」。

## [Unreleased]

## [1.0.0] - 2026-11-25

在 iPLoT 1.0 上請面板自己重新啟動（`app.restart`，D166）：模組在自己的程序裡跑，以前只換掉了跑模組的那個程序。安全模式開的，重新啟動之後還是安全模式。比 1.0 舊的 iPLoT 照舊自己換掉程序。

### 新增
- 從面板外（`python3 main.py --run`）按，說一句要從面板按。
- 這以前的版本沒有記錄；從 1.0 起補上，版本號跟著 iPLoT。
