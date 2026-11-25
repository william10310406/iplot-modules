"""頁面：模組呼叫 app.page 時，在那個模組自己的程序開一個視窗；關掉才回來，但只卡住它自己（D161）。"""
import json

ICON = "🪟"
# iPLoT 1.0 起每按一次另開一個程序跑模組（指令集第 6 版），app.page 交給提供它的模組在那個程序開視窗
PROVIDES = {"app.page": "page"}
ROLE_NAMES = {"app.page": "模組打開的頁面視窗", "page.top": "頁面最上面的導覽列"}  # 「要允許嗎？」用（D166）
# 用到的角色（D160 R5）：頁面上方那一排問提供 page.top 的模組（隨附的「導覽列」）
NEEDS = ("page.top", "os.app_name")
MIN_API = 6
HELLO = "頁面：其他模組打開頁面（例如行事曆、工作坊）時，視窗是這裡開的。頁面開著的時候，面板上照樣可以按別的模組。"
NO_WINDOW = "開不了頁面視窗：{why}。到工作坊重新安裝 iPLoT 的介面（重新啟動 iPLoT 會自動補裝）後再試"


def run(app):
    app.log(HELLO)


def page(app, title, html, api=None, owner=None):
    """開一個視窗顯示 html，關掉才回傳；api 的公開方法給那一頁的 JS 用。owner 是開頁面的模組：
    提供 page.top 的模組回了一排格子，就注入頁面最上面；按了一格就關掉這一頁、開始跑那個模組（不等它）。"""
    try:
        import webview  # iPLoT 的 lib/ 裡的 pywebview；工作程序的 sys.path 有 lib/
    except ImportError as exc:
        app.log(NO_WINDOW.format(why=exc))
        return
    app.call("os.app_name", owner.title if owner is not None else title)  # Dock 上寫模組的名字，不是「Python」（D166）
    window = webview.create_window(title, html=html, js_api=api, width=640, height=520)
    top = app.call("page.top", owner) if owner is not None else None
    chosen = []
    if _valid(top):
        targets = top["targets"]

        def _iplot_nav(i):  # 頁面只送一個編號；只認整數，連按兩下第一次算數
            if not chosen and type(i) is int and 0 <= i < len(targets):
                chosen.append(targets[i])
                window.destroy()

        window.expose(_iplot_nav)
        window.events.loaded += lambda: window.evaluate_js(f"({top['js']})({json.dumps(top['cells'])})")
    webview.start()
    if chosen and chosen[0] is not None:  # None 是「只關掉這一頁」（回主控面板）
        app.start(chosen[0])


def _valid(top):
    return (isinstance(top, dict) and isinstance(top.get("js"), str) and isinstance(top.get("cells"), list)
            and isinstance(top.get("targets"), list) and len(top["cells"]) == len(top["targets"]))
