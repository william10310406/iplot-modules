"""回報的內容：環境（iPLoT、作業系統、Python、出錯的模組與版本）與內文（D112）；預填的網址、截斷、存全文（D113）。
遮蔽一律交給 redact.redact，這裡不自己認路徑。core 只在函式裡 import（module_of、from_error）：直接執行
（IPLOT_DIRECT=1）時 core 不在 sys.path 上。寫檔的只有 save。"""

import contextlib
import os
import platform
import re
import sys
import unicodedata
import urllib.parse
from dataclasses import dataclass, replace
from pathlib import Path

import forum
import redact

REPORTER = "0.1.0"  # 內文最後那一行的 HTML 註解帶的版本：跟 CHANGELOG.md 最上面那一節一樣（測試核）
WHAT_HEAD = "### 發生了什麼"
WHAT_ERROR = "（請寫一兩句：按了什麼、預期是什麼）"
WHAT_BLANK = "（請寫：按了什麼、看到什麼、預期是什麼）"
LOST = "<模組>"  # 出錯的模組找不到它的資料夾時，標題與那一句白話裡的名字（不退回 error.module）

MAX_URL = 2000            # 保守值，每個平台都一樣（研究助理 2026-10-25：不實測；Windows 的 ShellExecute 約 2083，
                          # 登入的瀏覽器的實際上限沒量過）。有人反映截太多再實測放寬：Task 0 Step 2 的做法
MAX_LOGIN_REDIRECT = 5600 # 沒登入時 GitHub 轉去登入的那條網址：量到 ≤ 5742 字才完整（2026-10-24），留一點餘裕
LOGIN = "https://github.com/login?return_to="
MAX_TITLE = 200           # 網址放不下時，標題超過這麼多字一律先截到這麼多、再截內文（設計第 8 節）
HINT = "完整報告已複製，GitHub 出錯或內容被截斷時，按 ⌘V／Ctrl+V 貼上。"  # 研究助理的原句：真的複製成了才用
# 沒複製成時網址內文最後那一句（網頁那一頭也是頁面最後那一行）：剪貼簿裡是之前複製的東西，可能是沒遮過的，不叫人貼上。
# 存了 .txt 指那個檔；存不了檔的話，網頁指頁面下面那一格（#full 放回畫面上），tkinter 指訊息區（遮過的全文寫在那裡）
HINT_FILE = "剪貼簿沒有複製成功：完整報告存在 iPLoT 的 回報/{name}；GitHub 出錯或內容被截斷時，從那個檔複製全文、直接貼上。"
HINT_PAGE = "剪貼簿沒有複製成功：完整報告在 iPLoT 那一頁下面那一格；GitHub 出錯或內容被截斷時，從那裡複製全文、直接貼上。"
HINT_LOG = "剪貼簿沒有複製成功：完整報告在 iPLoT 的訊息區；GitHub 出錯或內容被截斷時，從那裡複製全文、直接貼上。"
TRUNCATED = "…（中間 {n} 行太長，已截斷；完整報告在剪貼簿裡）…"  # traceback 中間截掉的那一行：hint 是 HINT 時
TRUNCATED_ELSEWHERE = "…（中間 {n} 行太長，已截斷；完整報告在哪裡，看最後一行）…"  # 沒複製成時：不說在剪貼簿裡
CUT = "（太長，已截斷）"     # 「發生了什麼」或內文的尾巴截掉時，接在截剩的那一段後面的一行


@dataclass(frozen=True)
class Report:
    """一份遮過的回報。"""
    category: str     # forum.CATEGORIES 的鍵："BUG"、"IDEA"、"QA"
    title: str
    body: str
    notice: str       # redact.summary(...) 那一句
    ctx: redact.Ctx   # 按送出時再遮一次要用同一個


def panel_kind(modules=sys.modules) -> str:
    """後備的 tkinter 面板裡 ui.web 也在（網頁面板開不起來才退到它）：先看 ui.tk（設計第 17 節第 7 條）。"""
    if "ui.tk" in modules:
        return "tkinter"
    return "網頁" if "ui.web" in modules else "面板外"


def python_source(base: str) -> str:
    """Python 從哪裡來，只給類別、不給路徑。base 是 os.path.realpath(sys.base_prefix)：venv 裡的 sys.executable
    在 venv 裡，看不出來（設計第 17 節第 10 條）。"""
    if base.startswith("/Library/Frameworks/Python.framework/"):
        return "python.org"
    if "/Cellar/python@" in base or base.startswith(("/opt/homebrew/", "/usr/local/opt/python@")):
        return "Homebrew"
    usr = base == "/usr" or (base.startswith("/usr/") and not (base + "/").startswith("/usr/local/"))
    if usr or base.startswith(("/Applications/Xcode.app/", "/Library/Developer/CommandLineTools/")):
        return "系統"
    return "其他"


def os_line(system: str, machine: str, mac: str = "", build: str = "", linux: str = "") -> str:
    """作業系統那一行，不帶主機名稱：macOS 26.5（arm64）、Windows（build 22631，AMD64）、
    Linux：Ubuntu 24.04 LTS（x86_64）；細節讀不到的寫 Linux（x86_64）這種。"""
    if system == "Darwin" and mac:
        return f"macOS {mac}（{machine}）"
    if system == "Windows" and build:
        return f"Windows（build {build}，{machine}）"
    if system == "Linux" and linux:
        return f"Linux：{linux}（{machine}）"
    return f"{system}（{machine}）"


def this_os() -> str:
    """這台的作業系統。macOS 用 mac_ver（platform.release() 是 Darwin 的版本）；Windows 寫 build 號（3.10 的
    platform.release() 把 Windows 11 說成 10）；不讀 platform.node()：主機名稱常常是人名。"""
    system = platform.system()
    mac = platform.mac_ver()[0] if system == "Darwin" else ""
    build = platform.version().rsplit(".", 1)[-1] if system == "Windows" else ""
    linux = ""
    if system == "Linux":
        try:
            linux = platform.freedesktop_os_release().get("PRETTY_NAME", "")
        except OSError:  # 沒有 os-release
            linux = ""
    return os_line(system, platform.machine(), mac=mac, build=build, linux=linux)


def _nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def module_of(error) -> tuple[Path | None, tuple[str, ...]]:
    """出錯的模組的最上層模組資料夾，與中間那幾層下一層模組的名字（要藏的；從出錯的那一層往上）。
    從 error.file 往上找第一個是模組、名字是 error.module 的資料夾，再往上到上一層不是模組為止
    （設計第 17 節第 8 條）。「是模組」用核心的 is_module：符號連結不算、iPLoT.py 不算。
    核心與設定的錯誤、找不到那個資料夾的，回 (None, ())。"""
    from core.scan import is_module

    if error.file is None or error.module is None:
        return None, ()
    want = _nfc(error.module)
    mod = next((p for p in Path(error.file).parents if _nfc(p.name) == want and is_module(p)), None)
    if mod is None:
        return None, ()
    names, top = [], mod
    while top.parent != top and is_module(top.parent):
        names.append(_nfc(top.name))
        top = top.parent
    return top, tuple(names)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError):  # 讀不到、不是 UTF-8：當作沒有
        return ""


def module_version(folder: Path) -> str:
    """模組的版本：工作坊裝的看 .origin 的 version（標「工作坊」）；否則 CHANGELOG.md 最上面那一節
    （[Unreleased] 不算，D78）；都沒有是「版本未知」。"""
    for line in _read(folder / ".origin").splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "version" and value.strip():
            return f"{value.strip()}（工作坊）"
    heads = (h.strip() for h in re.findall(r"^## \[([^\]]*)\]", _read(folder / "CHANGELOG.md"), re.M))
    return next((h for h in heads if h and h.casefold() != "unreleased"), "版本未知")


def environment(app, top: Path | None, hidden: bool, source: str | None) -> list[str]:
    """「環境」那一節，一行一個。source 是 error.source；沒有錯誤的回報傳 None，沒有模組那一行
    （top 有值的話照樣寫）。"""
    python = f"{platform.python_version()}（{python_source(os.path.realpath(sys.base_prefix))}）"
    lines = [f"- iPLoT：{app.version}（面板：{panel_kind()}）", f"- 作業系統：{this_os()}", f"- Python：{python}"]
    if top is not None:
        note = "（出錯的是它的下一層模組，名稱已遮蔽）" if hidden else ""
        lines.append(f"- 模組：{top.name} {module_version(top)}{note}")
    elif source == "module":  # 按鈕按下去之前，那個資料夾被刪、改名或搬走了
        lines.append("- 模組：（找不到它的資料夾，名稱已遮蔽）")
    elif source == "core":
        lines.append("- 模組：—（核心的錯誤）")
    elif source == "config":
        lines.append("- 模組：—（config.py）")
    return lines


def fence(text: str) -> str:
    """traceback 的框：至少 4 個 ~，而且比 text 裡最長的一串 ~ 多一個（3.11 起的 ~^ 標記不會把框提早關掉）。"""
    longest = max((len(run) for run in re.findall(r"~+", text)), default=0)
    return "~" * max(4, longest + 1)


def body(what: str, env: list[str], sentence: str | None, tb: str | None) -> str:
    """內文（設計第 7 節）。sentence 與 tb 都是 None：沒有「錯誤」那一節；tb 是 ""：框裡寫「（沒有 traceback）」。"""
    parts = [f"{WHAT_HEAD}\n{what}", "### 環境\n" + "\n".join(env)]
    if sentence is not None or tb is not None:
        inner = (tb or "").rstrip("\n") or "（沒有 traceback）"
        mark = fence(inner)
        parts.append(f"### 錯誤\n{sentence or ''}\n\n{mark}text\n{inner}\n{mark}")
    parts.append(f"<!-- iPLoT 回報 {REPORTER} -->")
    return "\n\n".join(parts)


def _masked(category: str, title: str, text: str, ctx: redact.Ctx) -> Report:
    """標題、內文各遮一次，統計加起來給 summary。"""
    title, one = redact.redact(title, ctx)
    text, two = redact.redact(text, ctx)
    counts = {key: one[key] + two[key] for key in redact.KEYS}
    return Report(category, title, text, redact.summary(counts, ctx), ctx)


def from_error(error, app) -> Report:
    """「回報這個問題」：一筆 ErrorInfo 變成遮過的回報。下一層模組的名字藏起來，標題用最上層模組的名字。
    出錯的模組找不到它的資料夾時，名字一律寫 <模組>：error.module 可能是學生的名字，也不放進 secrets
    （redact 的第 7 步不分大小寫、沒有字界，叫 A 的模組會把整段 traceback 換爛）。"""
    from core.errors import describe

    top, hidden = module_of(error)
    ctx = redact.context(app.home, top, hidden)
    lost = top is None and error.source == "module"
    if top is not None:
        name = top.name
    elif lost:
        name = LOST
    else:
        name = {"core": "核心", "config": "config.py"}.get(error.source, "iPLoT")
    sentence = describe(replace(error, module=LOST) if lost else error)
    text = body(WHAT_ERROR, environment(app, top, bool(hidden), error.source), sentence, error.traceback_text)
    return _masked("BUG", f"[回報] {name}：{error.kind}（iPLoT {app.version}）", text, ctx)


def blank(app, category: str, module: str | None = None) -> Report:
    """沒有錯誤的回報（面板上的「回報問題」）：沒有「錯誤」那一節；module 有值就寫那個最上層模組與版本。"""
    top = None
    if module is not None:
        top = next((m.folder for m in app.modules if m.name == module and m.level != "child"), None)
    text = body(WHAT_BLANK, environment(app, top, False, None), None, None)
    return _masked(category, "[回報] ", text, redact.context(app.home, top))


def short_env(app) -> str:
    """提建議、問問題的內文最後那一行：iPLoT 0.6.0・macOS 26.5（arm64）・Python 3.14.7（沒有路徑）。"""
    return f"iPLoT {app.version}・{this_os()}・Python {platform.python_version()}"


def max_url(platform: str = sys.platform) -> int:
    """網址的上限：一律 MAX_URL（留著 platform 參數：之後要分平台放寬時不用改呼叫的地方）。"""
    return MAX_URL


def login_redirect(u: str) -> int:
    """沒登入時 GitHub 轉去登入的那條網址的長度：整條網址再編碼一次放進 return_to（跟量到的四組一字不差）。"""
    return len(LOGIN + urllib.parse.quote(u, safe=""))


def _q(s: str) -> str:
    """一個參數的值：孤立的代理字元（Linux 上 os.fsdecode 解不開的檔名）先換成 ?，quote 才不會丟例外。"""
    return urllib.parse.quote(s.encode("utf-8", "replace").decode("utf-8"), safe="")


def url(category: str, title: str, body: str) -> str:
    """論壇的新增頁，分類、標題、內文都預填好（設計第 8 節）。category 是 forum.CATEGORIES 的鍵。"""
    return f"{forum.FORUM}/new?category={_q(forum.CATEGORIES[category])}&title={_q(title)}&body={_q(body)}"


def with_hint(body: str, hint: str = HINT) -> str:
    """網址裡的內文：最後一律是 hint 那一句——複製成了是 HINT，沒成是 HINT_FILE、HINT_PAGE、HINT_LOG 其中一句
    （剪貼簿與 .txt 那一份不帶它，設計第 17 節第 15 條）。"""
    return body.rstrip("\n") + "\n\n" + hint


def fits(u: str, limit: int) -> bool:
    """「放得下」：網址 ≤ limit，而且沒登入時轉去登入的那條 ≤ MAX_LOGIN_REDIRECT。"""
    return len(u) <= limit and login_redirect(u) <= MAX_LOGIN_REDIRECT


def _most(ok, lo: int, hi: int) -> int:
    """二分：ok(lo) 已知成立，回 lo..hi 之間 ok 成立的最大的那個。回的一定是試過、成立的那個，
    所以就算 ok 不是一路成立到某處為止，回的網址也一定放得下。"""
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def _opener(line: str) -> str | None:
    """traceback 的框的開框那一行（body 寫的 ~~~~text，~ 至少 4 個）：回那一串 ~（關框那一行就是它）；
    不是回 None。"""
    return line[:-len("text")] if re.fullmatch(r"~{4,}text", line) else None


def _fence(lines: list[str]) -> tuple[int, int] | None:
    """traceback 的框：第一個開框那一行（_opener）與它下面只有同樣長度的 ~ 的那一行（行號）；沒有就 None。"""
    i = next((i for i, line in enumerate(lines) if _opener(line)), None)
    if i is None:
        return None
    mark = _opener(lines[i])
    j = next((j for j in range(i + 1, len(lines)) if lines[j] == mark), None)
    return None if j is None else (i, j)


def _grow(ok, cut, low: int, top: int) -> str | None:
    """cut(low) 放得下的話，回 low..top 之間放得下的、留得最多的那一份 cut(n)；放不下回 None。"""
    if not ok(cut(low)):
        return None
    return cut(_most(lambda n: ok(cut(n)), low, top))


def _middle(body: str, marker: str):
    """第 2 步：框裡多於 2 行的話，回 (cut, 1, top)：cut(k) 是留框裡的第一行與最後 k 行、中間換成 marker（TRUNCATED
    或 TRUNCATED_ELSEWHERE）的內文，1 ≤ k ≤ top。沒有框、或框裡不到 3 行，回 None。"""
    lines = body.split("\n")
    box = _fence(lines)
    if box is None or box[1] - box[0] - 1 <= 2:
        return None
    i, j = box
    inner = lines[i + 1:j]

    def cut(k: int) -> str:
        mid = marker.format(n=len(inner) - 1 - k)
        return "\n".join([*lines[:i + 1], inner[0], mid, *inner[-k:], *lines[j:]])
    return cut, 1, len(inner) - 2


def _tail(text: str, n: int) -> str:
    """text 留前 n 個字，後面加一行 CUT。截在 traceback 的框的開框或關框那一行的中間的話，那半行拿掉（~~~、~~~~tex
    在 GitHub 上也會開框：CommonMark 的 ~ 至少 3 個、後面帶什麼字都算）；截完還在框裡的話，補上關框的那一行。
    不然 GitHub 會把 CUT 與 HINT 都畫成程式碼。看的是那一行原本的整行，不是截剩的樣子：只看樣子的話，
    分不出半個開框行與使用者自己打的 ~~~ 那一行（例如關掉他自己的框的那一行）。"""
    lines = text[:n].split("\n")
    rest = text[n:].partition("\n")[0]  # 最後一行被截掉的那一段；截在行尾就是空的
    mark = None
    for i, line in enumerate(lines):
        whole = line + rest if i == len(lines) - 1 else line
        if whole != line and (whole == mark if mark else _opener(whole)):
            line = lines[i] = ""  # 半個開框或關框行
        if mark is None:
            mark = _opener(line)
        elif line == mark:
            mark = None
    head = "\n".join(lines).rstrip("\n")
    if mark:
        head += "\n" + mark
    return f"{head}\n{CUT}" if head else CUT


def _what(body: str):
    """第 3 步的前半：框以外、WHAT_HEAD 底下那一段（到下一個 ### 標題或框為止）。回 (cut, 0, top)：cut(n) 是那一段
    留前 n 個字、加一行 CUT 的內文，0 ≤ n ≤ top。找不到、或那一段是空的，回 None。"""
    lines = body.split("\n")
    i, j = _fence(lines) or (-1, -1)
    h = next((h for h, line in enumerate(lines) if line == WHAT_HEAD and not i <= h <= j), None)
    if h is None:
        return None
    e = next((e for e in range(h + 1, len(lines)) if lines[e].startswith("### ") or e == i), len(lines))
    section = "\n".join(lines[h + 1:e])
    text = section.rstrip("\n")
    if not text.strip():
        return None
    before = "\n".join(lines[:h + 1]) + "\n"
    after = section[len(text):] + ("\n" + "\n".join(lines[e:]) if e < len(lines) else "")
    return (lambda n: before + _tail(text, n) + after), 0, len(text)


def _shorten(category: str, title: str, body: str, limit: int, hint: str) -> str | None:
    """fit 的第 2、3 步，標題不動：回截到放得下的內文（不用截就是 body）；內文只剩 CUT 也放不下，回 None。
    每一步放不下時，下一步從比較短的那一份接著截（框裡只有 3 行時，換成 TRUNCATED 那一句反而比較長）。
    traceback 中間截掉的那一行：hint 是 HINT（真的複製成了）才說在剪貼簿裡，不然是 TRUNCATED_ELSEWHERE。"""
    marker = TRUNCATED if hint == HINT else TRUNCATED_ELSEWHERE

    def ok(b: str) -> bool:
        return fits(url(category, title, with_hint(b, hint)), limit)

    def size(b: str) -> int:
        return len(url(category, title, with_hint(b, hint)))

    if ok(body):
        return body
    for step in (lambda b: _middle(b, marker), _what):
        found = step(body)
        if found is not None:
            cut, low, top = found
            done = _grow(ok, cut, low, top)
            if done is not None:
                return done
            body = min(body, cut(low), key=size)
    return _grow(ok, lambda n: _tail(body, n), 0, len(body))


def fit(category: str, title: str, body: str, limit: int, hint: str = HINT) -> tuple[str, bool]:
    """預填的網址與有沒有截（設計第 8 節、第 17 節第 2、15 條）。內文最後一定是 hint（with_hint；預設 HINT，
    沒複製成時呼叫的那一頭給 HINT_FILE、HINT_PAGE 或 HINT_LOG），截的時候也留著；
    limit 不比下限（見最後）短的話，回的網址 ≤ limit、轉去登入的那條 ≤ MAX_LOGIN_REDIRECT。順序：①放得下就照用
    （標題再長也不動）；放不下的話，標題超過 MAX_TITLE 字一律先截到 MAX_TITLE，再截內文：②traceback 的框留第一行與
    最後 k 行；③「發生了什麼」從後面截，還是放不下就從內文的尾巴截；④內文只剩 CUT 也放不下（標題本身就很長）就再截
    標題。都是在編碼之前以行或字為單位截，不會切在 %XX 中間。
    下限是「標題空白、內文只剩一行 CUT 加 hint」的那一條網址（HINT 的話現在 BUG、IDEA 433 字，QA、NEWS 415 字；body
    本來就是空字串的話內文只有 HINT：361、343 字。BUG 的話 HINT_LOG 是 600、HINT_PAGE 636，HINT_FILE 看檔名，
    20261025-143005-ZeroDivisionError.txt 是 652）。整條放不下、limit 又比下限短時，沒有網址放得下：回的就是下限那一條
    與 True，它比 limit 長，fits(網址, limit) 是 False。MAX_URL 是 2000，走不到（HINT_FILE 的檔名裡錯誤的種類要長到
    150 多個中文字、或 1300 多個英文字母才會）。"""
    u = url(category, title, with_hint(body, hint))
    if fits(u, limit):
        return u, False
    t = title[:MAX_TITLE]
    b = _shorten(category, t, body, limit, hint)
    if b is not None:
        return url(category, t, with_hint(b, hint)), True
    b = _tail(body, 0) if body else body
    n = _most(lambda n: fits(url(category, t[:n], with_hint(b, hint)), limit), 0, len(t))
    return url(category, t[:n], with_hint(b, hint)), True


def save(folder: Path, stamp: str, kind: str, text: str) -> Path:
    """完整的回報（遮過、沒截、不帶 HINT）存成 folder/<stamp>-<kind>.txt（UTF-8、換行 \\n）；folder 不在就建。
    回寫好的那個檔。檔開了之後才失敗的（孤立的代理字元的 UnicodeEncodeError、磁碟滿了）先把那個檔刪掉再丟出去：
    回報/ 裡不留空的或寫一半的檔。開不了的（沒有權限）不刪：這一次什麼都還沒寫。"""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stamp}-{kind}.txt"
    created = False
    try:
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            created = True
            fh.write(text)
    except BaseException:
        if created:  # 關了檔才刪（Windows 刪不了開著的檔）；刪不掉就算了，丟出去的是原來那個錯誤
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
        raise
    return path
