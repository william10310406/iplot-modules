"""論壇在哪裡：這個 repo 的 GitHub Discussions，與四個分類的 slug（D115）。

分類的名字定了就不要改：GitHub 的 slug 是從名字來的，改了名字這裡也要一起改（設計第 17 節第 11 條）。"""

REPO = "william10310406/iplot"
FORUM = f"https://github.com/{REPO}/discussions"
# 分類的 slug（解開 %XX 之後的樣子）；Task 0 Step 1 照實測核對
CATEGORIES = {"BUG": "問題回報", "IDEA": "功能建議", "QA": "問答", "NEWS": "公告"}
