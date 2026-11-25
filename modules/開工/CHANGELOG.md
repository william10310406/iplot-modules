# Changelog

「開工」這個模組的版本紀錄，格式跟 iPLoT 的 CHANGELOG.md 一樣（[Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)）。`tools/publish.py` 取最上面那一節的版本號當工作坊裡的版本，取那一節的第一段當清單頁上的「這一版」。

## [Unreleased]

## [0.5.3] - 2026-11-24

在編輯器裡直接執行 `iplot.py` 時，檔頭那一小段改成交給 iPLoT 的 `python3 main.py --run`，不再寫死「互通」的路徑（D163）。要 iPLoT 0.9。

## [0.5.2] - 2026-11-15

### 修正
- docs 或設計文件被刪掉時，最後一行說哪個找不到，不再說「都開了」。

## [0.5.1] - 2026-10-07

加上「互通」的那一小段：可以直接 python3 iplot.py。

## [0.5.0] - 2026-10-05

跟 0.4.0 一樣，第一次放進工作坊。
