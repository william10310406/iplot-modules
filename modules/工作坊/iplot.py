"""工作坊：從一份清單安裝、更新別人做的模組。裝進來的東西只寫進它自己的資料夾；
覆蓋之前，舊的資料夾會整個存進它的 .history/；裝進來的模組第一次執行前會先問一次。
清單的網址寫在 config.py 的 WORKSHOP_URL。

做法都在旁邊的 workshop.py，清單那一頁是 page.html。清單最上面那一行與每一列的上傳者，都是清單給的。按了才會連網。
清單裡有維護者上傳、比自己新的工作坊，就先把自己換掉再開（selfupdate.py，D158）：工作坊是修其他模組的那一個，它一定要能開。

這個檔只用 iPLoT 0.5 起就有的 app.home、app.config.workshop_url、app.log、app.page、app.rescan；
後來才有的東西（「互通」的另開視窗）先試，不行就照舊在這裡開（tests/test_workshop_every_core.py 在每一版核心上跑過）。"""
import importlib.util
import os
import runpy
import sys
from pathlib import Path

import workshop

ICON = "🧰"
# 清單搬過家：0.5.0、0.5.1 的 config.py 還指著凍結的舊清單，那裡沒有新版的模組，也沒有新版的工作坊（2026-11-19 研究助理的老闆）
MOVED = {"https://william10310406.github.io/iplot-workshop/index.json": "https://william10310406.github.io/iplot-modules/index.json"}


def run(app):
    url = app.config.workshop_url
    if not url:
        return app.log("尚未設定工作坊的來源：在 config.py 的 WORKSHOP_URL 填 index.json 的網址")
    if url in MOVED:
        url = MOVED[url]
        app.log(f"工作坊的清單搬家了，這次改讀 {url}（config.py 的 WORKSHOP_URL 可以換成這個網址，這一句就不會再出現）")
    if not _separate(app):  # 清單在另開的程序裡抓、裡面開；面板空出來
        return
    try:
        entries, notice = workshop.read_listing(url)
    except ValueError as exc:  # 不是 JSON、格式不對、網址寫錯
        why = f"（{exc}）" if type(exc) is ValueError else ""  # 自己寫的中文原因照留；JSON 解析器的英文原文不給人看
        return app.log(f"讀不懂工作坊的清單（index.json）{why}。可能是 config.py 的 WORKSHOP_URL 寫錯了（它要指到 index.json），"
                       "或清單暫時壞了；確認之後再雙擊一次「工作坊」。")
    except workshop.NETWORK as exc:
        return app.log(f"工作坊的清單抓不下來：{workshop.plain(exc)}。也請確認 config.py 的 WORKSHOP_URL 沒有寫錯，再雙擊一次「工作坊」。")
    if _updated_self(app, entries):  # 已經換成新版、而且新版已經開過清單了
        return
    modules_dir = Path(app.home) / "modules"
    template = (Path(__file__).parent / "page.html").read_text(encoding="utf-8")
    app.page("工作坊", workshop.render(entries, modules_dir, template, notice), workshop.Api(app, entries, modules_dir))
    app.rescan()  # 頁面關掉之後：新裝的模組出現在面板上


AGAIN = "IPLOT_WORKSHOP_UPDATED"  # 換成新版之後重跑的那一次：不再檢查一次，免得清單與包對不上時一直換


def _updated_self(app, entries) -> bool:
    """清單裡有維護者上傳、比自己新的工作坊：換成那一版，用新版的 iplot.py 重跑一次 run，回 True。
    沒有新版、或換不成（任何原因）回 False，照舊用這一版開清單：自動更新絕不能讓工作坊打不開。"""
    if os.environ.get(AGAIN):
        return False
    folder = Path(__file__).resolve().parent
    try:
        import selfupdate

        entry = selfupdate.newer_entry(entries, folder, workshop)
        if entry is None:
            return False
        before = selfupdate.own_version(folder)
        version = selfupdate.update(entry, folder, workshop)
    except Exception as exc:  # noqa: BLE001  換不成就用現在這一版，原因說一句
        why = selfupdate.describe(exc, workshop) if "selfupdate" in sys.modules else str(exc)
        app.log(f"工作坊沒辦法自動更新（{why}），先用現在這一版打開")
        return False
    app.log(f"工作坊已自動更新：{before} → {version}（舊的存在 modules/工作坊/.history/）")
    for name in ("workshop", "selfupdate"):  # 新版的 iplot.py 要 import 新版的這兩個檔
        sys.modules.pop(name, None)
    os.environ[AGAIN] = "1"
    try:
        runpy.run_path(str(folder / "iplot.py"), run_name="iplot_workshop_updated")["run"](app)
    finally:
        os.environ.pop(AGAIN, None)
    return True


def _separate(app) -> bool:
    """有「互通」的 separate.py（互通 0.4.0 起）就經它另開一個程序開這一頁，面板不會被卡住；回 False 表示已經另開
    或叫到最前面了，這裡不用開。沒有就照舊在這裡開。用檔案路徑載入：這個模組的 sys.path[0] 是自己的資料夾。"""
    path = Path(app.home) / "modules" / "互通" / "separate.py"
    if not path.is_file():
        return True
    try:  # 互通壞了、跟這一版核心不合：照舊在這裡開，工作坊不能因為別的模組打不開（2026-11-19）
        spec = importlib.util.spec_from_file_location("iplot_interop_separate", path)
        separate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(separate)
        return separate.here(app)
    except Exception:  # noqa: BLE001
        return True
