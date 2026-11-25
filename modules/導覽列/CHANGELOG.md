# Changelog

「導覽列」這個模組的版本紀錄，格式跟 iPLoT 的 CHANGELOG.md 一樣（[Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/)）。`tools/publish.py` 取最上面那一節的版本號當工作坊裡的版本，取那一節的第一段當清單頁上的「這一版」。

## [Unreleased]

## [0.2.0] - 2026-11-25

不再借用核心的掃描、也不再用名字認面板：上一層、同一層、下一層改問 iPLoT 1.0 的 `app.top_modules`、`app.parent_of`、`app.children_of`，面板就是提供 `main` 的那一個，第一格寫它的名字（D164）。要 iPLoT 1.0 以上（`MIN_API = 7`）；舊版的 iPLoT 會請你先更新。

### 修正
- 內容置中的頁面（例如車車），導覽列貼在視窗最上面，不再跟著內容一起置中。

## [0.1.0] - 2026-11-23

頁面最上面那一排從核心搬到這個模組（D159），並多了「同一層」：最上層的模組沒有上一層、多半也沒有下一層，以前那一排只剩「主控面板」（Discussion #9）。面板裡開的頁面與「互通」另開的頁面用同一份。
