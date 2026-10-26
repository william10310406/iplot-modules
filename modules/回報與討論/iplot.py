"""回報問題、提建議、看大家在討論什麼。"""
# ── 互通 ── 直接執行這個檔（python3 iplot.py）時交給 iPLoT 用彈出式視窗跑；從 iPLoT 裡執行時這段不做事。不要可以整段刪掉
import sys

if __name__ == "__main__" and "core.runner" not in sys.modules:
    import os
    import subprocess
    here = folder = os.path.dirname(os.path.abspath(__file__))
    run = None
    while run is None and folder != os.path.dirname(folder):  # 往上一層層找 iPLoT：模組在它裡面或旁邊都找得到
        folder = os.path.dirname(folder)
        try:
            names = [""] + sorted(os.listdir(folder))
        except OSError:
            names = [""]
        runs = (os.path.join(folder, n, "modules", "互通", "run.py") for n in names)
        run = next((r for r in runs if os.path.isfile(r)), None)
    if run and not os.environ.get("IPLOT_DIRECT"):  # IPLOT_DIRECT=1：不交出去，照一般腳本跑（例如在編輯器裡除錯）
        sys.exit(subprocess.call([sys.executable, run, here, *sys.argv[1:]]))
    if not run:
        print("找不到 iPLoT 的「互通」（先在工作坊裝「互通」；模組要放在 iPLoT 資料夾裡或它旁邊），照一般的 python3 iplot.py 跑",
              file=sys.stderr)
# ── 互通 ──

import json
import threading
import time
import webbrowser
from pathlib import Path

import forum
import redact
import report

ICON = "💬"
HERE = Path(__file__).resolve().parent
OUTBOX = HERE / "回報"  # 完整的回報（.txt）與 tkinter 面板的草稿（.md）：只放在這台電腦，不進 git、不進包
BROWSER_FAILS = (webbrowser.Error, OSError, ValueError)  # 找不到瀏覽器、Windows 的 ShellExecute、3.14 對 - 開頭的網址
OPENED = ("已經在瀏覽器打開了。登入 GitHub、按 Start discussion 才會公開。{where}如果 GitHub 出錯（例如顯示 500，或填好的"
          "內容不見了）：確認瀏覽器已經登入之後，回到這裡再按一次「在瀏覽器打開」；還是不行，就在 GitHub 的新增頁把內文整個換成"
          "完整的回報、直接貼上（複製下面的網址會蓋掉剪貼簿，貼上之前先按「再複製一次」）。這個視窗可以關掉了。")
CUT_SAVED = ("內容太長，網址裡的 traceback 中間截掉了；那個檔是完整的，貼上之後也可以把它拖進留言框當附件。"
             "關掉這個視窗之後 iPLoT 會指給你看。")
CUT_UNSAVED = "內容太長，網址裡的 traceback 中間截掉了。"  # 存不了檔：沒有「那個檔」可以指
TK_CUT_SAVED = ("內容太長，網址裡的 traceback 中間截掉了；回報/{name} 是完整的，貼上之後也可以把它拖進留言框當附件。"
                "iPLoT 會指給你看。")  # tkinter 面板：截過的檔馬上就指，沒有「關掉這個視窗之後」
UNENCODABLE = "有沒辦法存成 UTF-8 的字"  # 孤立的代理字元：UnicodeEncodeError 的字不給人看（見 _cannot）
NOT_OPENED = "瀏覽器打不開。把下面這串網址整個複製到瀏覽器的網址列；{where}"
TK_NOT_OPENED = "瀏覽器打不開。{cut}把這串網址整個複製到瀏覽器的網址列：{url}"  # tkinter 面板的訊息區；cut 見 _tk_cut
MENU = "要做什麼？輸入 1 回報問題、2 提建議、3 問問題、4 看論壇"  # tkinter 面板沒有頁面：run 問這一句（設計第 9 節）
ASKS = ("IDEA", "QA")  # 提建議、問問題：直接開新增頁，內文只帶 short_env（回報問題 BUG 走預覽；公告 NEWS 不給人開）


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def render(data: dict) -> str:
    """page.html，資料以 JSON 放進 <script type="application/json">：< 換成 \\u003c，traceback 裡的 </script>
    關不掉它；頁面上的字一律用 textContent／value。"""
    return (HERE / "page.html").read_text(encoding="utf-8").replace(
        "__DATA__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c"), 1)


def _again(rep: report.Report, title: str, body: str) -> tuple[str, str, str]:
    """送出前再遮一次（同一個 ctx：使用者在頁面上、草稿裡貼進來的路徑也遮），回 (title, body, full)。
    full 是剪貼簿與 .txt 那一份：遮過、沒截、不帶 HINT（設計第 17 節第 15 條）。"""
    title, body = redact.redact(title, rep.ctx)[0], redact.redact(body, rep.ctx)[0]
    return title, body, f"{title}\n\n{body}"


def _save(kind: str, full: str) -> tuple[Path | None, Exception | None]:
    """把完整的回報存進 OUTBOX（一律存，不只截過的時候）；存不了回 (None, 錯誤)，照樣往下走。
    ValueError：full 裡有孤立的代理字元（Linux 上解不開的資料夾名字）時，寫檔丟 UnicodeEncodeError
    （report.save 不留下寫壞的檔）。"""
    try:
        return report.save(OUTBOX, stamp(), kind, full), None
    except (OSError, ValueError) as exc:
        return None, exc


def _why(exc: OSError, ctx: redact.Ctx) -> str:
    """句子裡的 OSError：它的字帶著完整的路徑（家目錄、帳號名），而那一句可能被複製進公開的貼文，先用同一個 ctx 遮過。
    只給 OSError：別的例外的字（例如 UnicodeEncodeError 裡 '\\udce9' 那種跳脫）redact 會讀成路徑、遮成 <PATH>/…。"""
    return redact.redact(str(exc), ctx)[0]


def _cannot(exc: Exception | None, ctx: redact.Ctx) -> str:
    """「存不了檔（…）」「草稿存不了（…）」括號裡的字：OSError 的字遮過；ValueError（孤立的代理字元的
    UnicodeEncodeError）一律是 UNENCODABLE。"""
    return _why(exc, ctx) if isinstance(exc, OSError) else UNENCODABLE


def _open(u: str) -> bool:
    """標準庫的 webbrowser.open，不經過核心；打不開回 False，不丟例外。"""
    try:
        return bool(webbrowser.open(u))
    except BROWSER_FAILS:
        return False


def _ask_url(category: str, env: str) -> str:
    """提建議、問問題的新增頁：標題空著，內文是一條分隔線與 short_env（沒有路徑、沒有帳號名，不用遮）。"""
    return report.url(category, "", "\n\n---\n" + env)


def _browse(u: str) -> dict:
    """go、open_forum 回給頁面的：開成了 {"ok": True, "url": ""}；開不成把網址交給頁面，讓人自己複製。"""
    ok = _open(u)
    return {"ok": ok, "url": "" if ok else u}


def _uncopied(f: Path | None, nowhere: str) -> str:
    """沒複製成時網址內文最後那一句：剪貼簿裡是之前複製的東西（可能是沒遮過的 traceback），不能叫人貼上，改成指向
    回報/ 裡遮過的 .txt（report.HINT_FILE）；存不了檔的話是 nowhere——網頁是 HINT_PAGE（頁面下面那一格），
    tkinter 是 HINT_LOG（訊息區）。複製成了才是 report.HINT（研究助理的原句）。"""
    return report.HINT_FILE.format(name=f.name) if f is not None else nowhere


def _sentence(ok: bool, cut: bool, f: Path | None, err: Exception | None, ctx: redact.Ctx, copied: bool) -> str:
    """send 回給頁面的那一句：只講檔案與網址（剪貼簿成不成那一句由頁面加）。截過的話，開成了、開不成都接截斷的
    那一句：只叫人複製網址的話，人不知道網址裡的 traceback 少了一段。存不了檔又沒複製成的話，完整的回報只在
    頁面下面那一格（頁面接著說「剪貼簿沒有複製成功」，不說「只在剪貼簿裡」）。"""
    if f is None:
        only = "剪貼簿裡" if copied else "下面那一格"
        where = f"存不了檔（{_cannot(err, ctx)}）；完整的回報只在{only}。"
    elif ok:
        where = f"完整的回報也存在 回報/{f.name}。"
    elif cut:  # 「關掉這個視窗之後 iPLoT 會指給你看」由後面的 CUT_SAVED 說，不說兩次
        where = f"完整的回報存在 回報/{f.name}。"
    else:
        where = f"完整的回報存在 回報/{f.name}，關掉這個視窗之後 iPLoT 會指給你看。"
    text = (OPENED if ok else NOT_OPENED).format(where=where)
    if cut:
        text += CUT_SAVED if f else CUT_UNSAVED
    return text


class Api:
    """預覽頁的 JS 呼叫的入口（pywebview.api.measure／send；run 的那一頁另外有 start／go／open_forum），照「工作坊」
    的樣子：在 pywebview 的執行緒上跑，只遮、組網址、存檔、開瀏覽器，不叫 app、不碰 core（設計第 17 節第 4 條）；
    屬性都以底線開頭，不丟例外。on_error 只給前三個；starts、short_env 是 run 先算好的（start、go 不碰 app）。"""

    def __init__(self, rep: report.Report, kind: str, saved: list[Path],
                 starts: dict[str, report.Report] | None = None, short_env: str = ""):
        self._rep, self._kind = rep, kind  # _rep 是「目前這一份」：start 換掉它，measure、send 拿著鎖讀它
        self._first = rep  # start 不認得的名字一律回到這一份（run 給的是沒指定模組的那一份）
        self._starts = dict(starts or {})  # {最上層模組的名字: 那一份}：下一層模組的名字不在裡面（可能是學生的名字）
        self._env = short_env
        self._saved = saved  # 截過、或瀏覽器打不開的那一次存的檔：頁面關掉之後才拿著 _lock 看，指給人看（_reveal）
        self._lock = threading.Lock()  # pywebview 每一次 api 呼叫各一條執行緒；頁面關掉時 send 可能還拿著它

    def start(self, module: str = "") -> dict:
        """「回報問題」：換成那個模組的那一份（不在 starts 裡的，包括下一層模組的名字與 ""，一律是沒指定模組的那一份），
        之後 measure、send 用它的分類與 ctx。只查表，不碰 app。"""
        rep = self._starts.get(module, self._first) if isinstance(module, str) else self._first
        with self._lock:
            self._rep = rep
        return {"title": rep.title, "body": rep.body, "notice": rep.notice}

    def go(self, category: str) -> dict:
        """「提建議」「問問題」：開那個分類的新增頁（ASKS 以外的分類不開）。不存檔：內文沒有使用者寫的東西。"""
        if category not in ASKS:
            return {"ok": False, "url": ""}
        return _browse(_ask_url(category, self._env))

    def open_forum(self) -> dict:
        """「看論壇」。"""
        return _browse(forum.FORUM)

    def measure(self, title: str, body: str) -> dict:
        """長度那一行與 full：頁面把 full 放進 #full，按下去時複製的就是它（跟 send 存的檔一字不差）。"""
        with self._lock:
            rep = self._rep
            title, body, full = _again(rep, title, body)
            u, limit = report.url(rep.category, title, report.with_hint(body)), report.max_url()
            sentence = f"網址長度 {len(u)}／{limit}"
            if not report.fits(u, limit):
                sentence += "：traceback 會從中間截斷；完整的會在剪貼簿與檔案裡"
            return {"length": len(u), "limit": limit, "sentence": sentence, "full": full}

    def send(self, title: str, body: str, copied: bool = False) -> dict:
        """再遮一次、先存檔、再組網址開瀏覽器（研究助理 2026-10-24：登入之後 GitHub 可能回 500，不能只靠網址）。
        copied 是頁面在叫 send 之前那一下 execCommand("copy") 的結果：真的是 True 才算複製成了，網址內文最後才是
        HINT；不然是 uncopied（_uncopied）。hint 是網址內文最後那一句，頁面把它放進 #hint；「再複製一次」沒成時頁面
        換成 uncopied。"""
        with self._lock:
            rep = self._rep
            title, body, full = _again(rep, title, body)
            f, err = _save(self._kind, full)
            copied = copied is True
            uncopied = _uncopied(f, report.HINT_PAGE)
            hint = report.HINT if copied else uncopied
            u, cut = report.fit(rep.category, title, body, report.max_url(), hint)
            if cut:  # 截過的：開瀏覽器之前就記下（webbrowser.open 還沒回來，頁面就可能被關掉）
                self._mark(f)
            ok = _open(u)
            if not ok:
                self._mark(f)
            return {"ok": ok, "url": "" if ok else u, "file": f.name if f else "", "cut": cut, "hint": hint,
                    "uncopied": uncopied, "new_url": report.url(rep.category, "", ""),
                    "sentence": _sentence(ok, cut, f, err, rep.ctx, copied)}

    def _mark(self, f: Path | None) -> None:
        """記下頁面關掉之後要指給人看的檔：存不了的不記；同一秒按兩次（檔名一樣）不記兩次。"""
        if f is not None and f not in self._saved:
            self._saved.append(f)


def run(app):
    """面板上的「回報與討論」這一格（D114，設計第 5、9 節）：回報問題、提建議、問問題、看論壇。回報問題可以指定一個
    最上層的模組（下一層模組的名字可能是學生的名字，不列）；每一份都在這裡先算好，頁面那一頭只查表、不碰 app。"""
    if report.panel_kind() == "tkinter":
        return _menu_by_ask(app)
    env = report.short_env(app)
    names = list(dict.fromkeys(m.name for m in app.modules if m.level != "child"))  # 不同的根底下同名的只列一次
    saved = []
    data = {"mode": "menu", "modules": names, "short_env": env,
            "hint": report.HINT}  # HINT：「回報問題」換到預覽那一段才顯示（page.html 的 show），#menu 上什麼都還沒複製
    api = Api(report.blank(app, "BUG"), "回報", saved, {n: report.blank(app, "BUG", n) for n in names}, env)
    app.page("回報與討論", render(data), api)
    _reveal(app, api)


def on_error(app, error):
    """面板上的「回報這個問題」（D110）：遮過的回報給人看、讓人改，再用預填的網址開瀏覽器（設計第 5.1、5.2 節）。
    頁面那一頭不碰 app：存了要指給人看的檔，等頁面關掉、回到這裡才 reveal。"""
    rep = report.from_error(error, app)
    if report.panel_kind() == "tkinter":
        return _by_file(app, rep, error.kind)
    saved = []
    data = {"mode": "edit", "title": rep.title, "body": rep.body, "notice": rep.notice, "hint": report.HINT}
    api = Api(rep, error.kind, saved)
    app.page("回報這個問題", render(data), api)
    _reveal(app, api)


def _reveal(app, api: Api) -> None:
    """頁面關掉之後，指出 send 記下的檔。頁面關掉的時候 send 可能還在 pywebview 的執行緒上跑（例如卡在
    webbrowser.open）：拿著它的鎖、等它做完再看。"""
    with api._lock:
        files = list(api._saved)
    for p in files:
        app.reveal(p)


def _menu_by_ask(app) -> None:
    """tkinter 面板沒有頁面（設計第 9 節）：問一次。1 走跟「回報這個問題」一樣的草稿檔（沒有錯誤、不指定模組），
    2、3、4 直接開瀏覽器，開不成就把網址寫在訊息區；按取消什麼都不做。只認剛好 "1"–"4"（工作單）："1 "、" 4" 之類
    的也是「請輸入 1 到 4」。"""
    answer = app.ask(MENU)
    if answer is None:
        return
    if answer == "1":
        _by_file(app, report.blank(app, "BUG"), "回報")
    elif answer in ("2", "3"):
        _open_or_log(app, _ask_url({"2": "IDEA", "3": "QA"}[answer], report.short_env(app)))
    elif answer == "4":
        _open_or_log(app, forum.FORUM)
    else:
        app.log("請輸入 1 到 4")


def _open_or_log(app, u: str) -> None:
    """tkinter 面板開瀏覽器：找不到瀏覽器不變成這個模組的錯誤，網址寫在訊息區讓人自己複製。"""
    if not _open(u):
        app.log(TK_NOT_OPENED.format(cut="", url=u))


def _by_file(app, rep: report.Report, kind: str) -> None:
    """tkinter 面板沒有頁面（設計第 5.2 節）：草稿用編輯器打開，改好按「確定」才送。草稿沒有再遮過、只留在這台電腦；
    拿去貼、拖去當附件的是讀回來再遮過、存成 .txt 的那一份。tkinter 的模組在主執行緒上跑，這裡叫 app 沒問題。"""
    draft, content = OUTBOX / f"{stamp()}-{kind}.md", f"{rep.title}\n\n{rep.body}"
    try:
        content.encode("utf-8")  # 孤立的代理字元在建檔之前就丟：write_text 先建檔再編碼，會留下一個空的草稿
        OUTBOX.mkdir(parents=True, exist_ok=True)
        draft.write_text(content, encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:  # 回報/ 寫不進去、標題裡有孤立的代理字元：一句話，不變成這個模組自己的錯誤
        app.log(f"草稿存不了（{_cannot(exc, rep.ctx)}），沒有送出。")
        return
    app.log(rep.notice)
    app.edit(draft)
    if not app.confirm(f"草稿在 回報/{draft.name}，已經用編輯器打開。改好、存檔之後按「確定」就用瀏覽器打開；"
                       "按「取消」就不送，草稿留著。"):
        app.log(f"沒有送出；草稿留在 回報/{draft.name}")
        return
    try:
        text = draft.read_text(encoding="utf-8-sig")  # 記事本存檔可能加 BOM
    except (OSError, UnicodeDecodeError) as exc:  # 按「確定」之前草稿被刪了，或存成了 Big5 之類的編碼
        app.log(_unreadable(exc, draft.name, rep.ctx))
        return
    first, _, rest = text.partition("\n")
    lines = rest.split("\n")
    while lines and not lines[0].strip():  # 標題底下的空行不算內文
        lines.pop(0)
    title, body, full = _again(rep, first, "\n".join(lines))
    p, err = _save(kind, full)  # 先存檔、複製，再開瀏覽器
    copied = _copy_tk(full)
    hint = report.HINT if copied else _uncopied(p, report.HINT_LOG)  # 跟訊息區那一句（_tk_sentence）說的一樣
    u, cut = report.fit(rep.category, title, body, report.max_url(), hint)
    ok = _open(u)
    said = _tk_cut(p, cut)  # 截過的那一句：開成了接在下面這一句裡，開不成跟網址寫在同一行（只說一次）
    app.log(_tk_sentence(p, err, copied, report.url(rep.category, "", ""), rep.ctx, said if ok else ""))
    if p is None and not copied:  # 遮過的全文只剩訊息區這一份（草稿沒有再遮過，不叫人從草稿貼）
        app.log(full)
    if not ok:
        app.log(TK_NOT_OPENED.format(cut=said, url=u))
    if p is not None and (cut or not ok):
        app.reveal(p)


def _unreadable(exc: Exception, draft: str, ctx: redact.Ctx) -> str:
    """草稿讀不回來時訊息區的那一句（不開瀏覽器）：編碼不對的草稿還在，叫人這次存成 UTF-8；刪掉了的就只叫人再試一次。
    不提任何一顆鈕：「回報這個問題」（on_error）與選單的「1」（run）都走 _by_file，兩邊按的不一樣。"""
    if isinstance(exc, UnicodeDecodeError):  # 它的字只有編碼的名字、那個位元組與位置，沒有路徑：不經過 _why
        return (f"讀不回草稿（{exc}），沒有送出；改過的草稿留在 回報/{draft}，請再試一次（會開新的一份），"
                "這次存成 UTF-8。")
    return f"讀不回草稿（{_why(exc, ctx)}），沒有送出；請再試一次（會開新的一份）。"


def _tk_sentence(p: Path | None, err: Exception | None, copied: bool, new_url: str, ctx: redact.Ctx,
                 cut: str = "") -> str:
    """tkinter 面板開了瀏覽器之後訊息區的那一句：完整的回報在哪裡、GitHub 出錯時怎麼貼。存不了檔、也沒複製成的話，
    遮過的全文由 _by_file 接在這一句的下一則（草稿沒有再遮過，不是拿去貼的那一份）。cut 是截過時的那一句（_tk_cut），
    接在後面；複製成了的話 HINT 照樣是最後一句。"""
    if p is None and copied:
        text = (f"完整的回報已經複製到剪貼簿；存不了檔（{_cannot(err, ctx)}），完整的回報只在剪貼簿裡。如果 GitHub 出錯"
                f"（例如顯示 500）：確認瀏覽器已經登入之後再選一次；還是不行，就打開 {new_url}、直接貼上（複製這個網址會蓋掉"
                "剪貼簿）。")
    elif p is None:
        text = (f"存不了檔（{_cannot(err, ctx)}），剪貼簿也沒有複製成功：完整的回報（遮過的）是下面那一則訊息。"
                f"如果 GitHub 出錯，打開 {new_url}，再從訊息區複製下面那一則、直接貼上。")
    elif copied:
        text = (f"完整的回報已經複製到剪貼簿，也存在 回報/{p.name}。如果 GitHub 出錯（例如顯示 500）：確認瀏覽器已經登入之後"
                f"再選一次；還是不行，就打開 {new_url}（複製這個網址會蓋掉剪貼簿），再從 回報/{p.name} 複製全文、直接貼上。")
    else:
        text = (f"完整的回報存在 回報/{p.name}（剪貼簿沒有複製成功）：如果 GitHub 出錯，打開 {new_url}，"
                "再從那個檔複製全文、直接貼上。")
    return text + cut + (report.HINT if copied else "")


def _tk_cut(p: Path | None, cut: bool) -> str:
    """tkinter 面板截過時的那一句（照網頁的 CUT_SAVED／CUT_UNSAVED）；沒截回 ""。存了檔的話 _by_file 接著就 reveal 它。"""
    if not cut:
        return ""
    return CUT_UNSAVED if p is None else TK_CUT_SAVED.format(name=p.name)


def _copy_tk(text: str) -> bool:
    """複製到 tkinter 面板自己的那個 Tk 的剪貼簿（app 沒有剪貼簿的動作）。只在 tkinter 面板叫：網頁面板開著的時候
    import tkinter 會被擋。拿不到那個 Tk、或任何一步出錯，回 False。"""
    try:
        import tkinter

        root = getattr(tkinter, "_default_root", None)
        if root is None:
            return False
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update_idletasks()  # 不用 update()：它會在模組裡面重入地處理排著的滑鼠事件
    except Exception:  # noqa: BLE001  複製不成不能讓整個回報停下來
        return False
    return True
