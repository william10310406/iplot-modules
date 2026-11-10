"""Lean 實數遊戲：只用 Lean，從自然數一路蓋到實數，再證不等式與極限。遊戲在網路上，不用安裝。"""
import http.client
import os
import ssl
import urllib.request
import webbrowser

ICON = "📐"
GAME_URL = "https://adam.math.hhu.de/#/g/william10310406/reals-game"
CHECK_URL = "https://adam.math.hhu.de/"  # 只看伺服器連不連得上，不讀內容
TIMEOUT = 8
NETWORK = (OSError, http.client.HTTPException)  # 連不上、逾時、憑證不對、連到一半斷掉、伺服器沒回話
BROWSER_FAILS = (webbrowser.Error, OSError, ValueError)

INTRO = ("Lean 實數遊戲：只用 Lean，從自然數一路蓋到整數、有理數、實數，再證不等式與極限；遊戲內容是英文。"
         "需要網路，不用安裝任何東西：遊戲跑在 adam.math.hhu.de 的公開伺服器上，用瀏覽器玩。"
         "進度存在你用的那個瀏覽器裡，換瀏覽器或清掉網站資料就不見。")
OFFLINE = "連不上 adam.math.hhu.de（{reason}），遊戲沒有打開。確認網路連得上之後再按一次。"
OPENED = "已經用瀏覽器打開遊戲。"
NOT_OPENED = "瀏覽器打不開。把這個網址複製到瀏覽器的網址列：{url}"


def _context():
    """驗證 https 憑證用的設定（跟「工作坊」一樣）：python.org 的 macOS Python 憑證庫是空的時候，改用 macOS 自己的那一份。"""
    context = ssl.create_default_context()
    if not context.cert_store_stats()["x509_ca"] and os.path.exists("/etc/ssl/cert.pem"):
        context.load_verify_locations("/etc/ssl/cert.pem")
    return context


def unreachable(url: str = CHECK_URL, timeout: float = TIMEOUT) -> str | None:
    """連得上回 None；連不上回一句原因（給人看的，不是 traceback）。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=_context()) as response:
            response.read(1)
    except NETWORK as exc:
        return str(getattr(exc, "reason", "") or exc) or type(exc).__name__
    return None


def open_browser() -> str:
    """用瀏覽器開遊戲，回一句結果。"""
    try:
        ok = webbrowser.open(GAME_URL)
    except BROWSER_FAILS:
        ok = False
    return OPENED if ok else NOT_OPENED.format(url=GAME_URL)


def run(app):
    app.log(INTRO)
    reason = unreachable()
    if reason:
        app.log(OFFLINE.format(reason=reason))
        return
    app.log(open_browser())
