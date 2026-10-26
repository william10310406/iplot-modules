"""遮蔽規則：回報送出去之前，把路徑、使用者名稱、疑似學號、電子郵件、下一層模組的名字與模組的原始碼行遮掉（D111）。
純函式，只用標準庫：ctx 帶這台機器的事實，所以測試可以在任何平台上餵 macOS、Windows、Linux 的路徑。
冪等：遮過的再遮一次，字一樣（記號 <…> 不會再被換；送出前會再遮一次）。"""

import contextlib
import getpass
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# 統計的鍵；也是 summary 列出來的順序
KEYS = ("路徑", "使用者名稱", "疑似學號", "電子郵件", "原始碼", "下一層模組")

# traceback 的 frame 那一行：lead 認得 ExceptionGroup 的 "  | "；path 貪婪（路徑裡有 " 也認得）；tail 可以是空的（SyntaxError）
FRAME = re.compile(r'^(?P<lead>(?:[ \t]*\|)?[ \t]*)File "(?P<path>.*)", line (?P<n>\d+)(?P<tail>[^\n]*)$')
# 本來就沒有原始碼的 frame：<frozen runpy> 這種（<string>、<stdin> 不算：底下是 eval／exec 的那個字串）
FROZEN = re.compile(r"<frozen [^\n]*>")
# 單引號當得了開頭的條件：前面不是 ASCII 英數字（Can't、couldn't 的撇號不當開頭），或前面是一個 b r u f
# （大小寫）或兩個 b r（rb、br…）、而前綴本身前面不是 ASCII 英數字——bytes／raw 的 repr：
# No such file or directory: b'HK2/王小明/a.txt'
OPEN = r"(?:(?<![A-Za-z0-9])|(?<=(?<![A-Za-z0-9])[bBrRuUfF])|(?<=(?<![A-Za-z0-9])[bBrR][bBrR]))"
# 同一個條件，給倒過來的字用：開引號前面的字在倒過來的字裡排在它後面，lookbehind 換成 lookahead
BACK_OPEN = r"(?:(?![A-Za-z0-9])|(?=[bBrRuUfF](?![A-Za-z0-9]))|(?=[bBrR][bBrR](?![A-Za-z0-9])))"
# 引號裡的路徑（第 2 步）。同一行的引號怎麼兩兩配，沒有一種規則永遠配得對（撇號、落單的引號、閉引號後面緊接著 /、
# 路徑頭尾多打的空白各騙倒過一種）：改成下面幾種讀法各配一次，哪一種讀法配出來的一對像路徑就遮（聯集，寧可多遮）。
# 每一種引號分開配，不放在同一個 | 裡：雙引號那一對不算的時候，裡面的單引號那一對照樣配得到（"<'HK2/…'"）。
# 兩頭同一個字的引號：ASCII 的 ' "、反引號、全形的 ＂ ＇；撇號的條件（OPEN）只給 ASCII 的 '
SYMMETRIC = (("'", OPEN), ('"', ""), ("`", ""), ("＂", ""), ("＇", ""))
# 開引號與閉引號不同字的（中文引號、書名號）：沒有怎麼兩兩配的問題
PAIRS = ("「」", "『』", "“”", "‘’", "《》", "〈〉")
ASCII_QUOTES = "'\""


def _readings(symmetric, pairs=()) -> tuple[tuple[re.Pattern, ...], tuple[re.Pattern, ...]]:
    """一組讀法：(往右配的, 在倒過來的字上配的)。"""
    forward = [re.compile(pattern) for q, opener in symmetric for pattern in (
        # (a) 引號後面緊接著絕對路徑開頭（/、X:\、X:/、\\），到下一個同種引號：路徑裡可以有空白，前面緊貼什麼都算
        rf"{q}(?:/|[A-Za-z]:[\\/]|\\\\)[^{q}\n]*{q}",
        # (b) 從左邊起兩兩配，每一對都吃掉：open(' HK2/…') 這種頭尾有空白的路徑
        rf"{opener}{q}[^{q}\n]*{q}",
        # (c) 裡面含 / 或 \、頭尾不是空白才算一對，不算的話這個開引號跳過、下一個引號再試：
        # Plan B's 'HK2/…'、'x ' / 'HK2/…'（撇號或上一對的閉引號到路徑的開引號那一段頭尾是空白，不算）
        rf"{opener}{q}(?![\s{q}])(?=[^{q}\n]*[/\\])[^{q}\n]*(?<!\s){q}")]
    # 不同字的：每一個開引號各配到它後面第一個閉引號（lookahead 抓第 1 組，每一個開引號都配得到：
    # 「<…>「HK2/…」 的兩對都是一對）；’ 也是撇號：‘ 再配到這一行最後一個 ’（‘Bob’s/王小明.txt’：最短的 ‘Bob’ 沒有分隔符號）
    forward += [re.compile(rf"(?=({o}[^{c}\n]*{c}))") for o, c in pairs]
    forward += [re.compile(r"(?=(‘[^\n]*’))")] if pairs else []
    # (d) 從右邊起兩兩配：在倒過來的字上配，配到的位置再換回來——'' HK2/…'（從左邊配是 ''，路徑的開引號落單）
    back = [re.compile(rf"{q}[^{q}\n]*{q}" + (BACK_OPEN if opener else "")) for q, opener in symmetric]
    return tuple(forward), tuple(back)


def _unclosed(text: str) -> list[tuple[int, int]]:
    """閉引號不見了的（第 4、5 步把 「HK2/王小明/a.txt」/… 的 /a.txt」/… 當成絕對路徑先遮，閉引號在標籤裡）：
    開引號一直開到行尾。不同字的：這一行最後一個閉引號後面的每一個開引號；兩頭同一個字的（ASCII 的除外）：
    這一行有奇數個時的最後一個。text 的最後一定是 \n（quoted 先補）：回 (開引號, 那一行的 \n 的位置 + 1)，
    \n 當閉引號留在標籤後面。用 find 一行一行找，不用 lookahead：很多開引號的長行不會每一個都掃到行尾"""
    out, start = [], 0
    for line in text.split("\n")[:-1]:
        end = start + len(line) + 1
        for o, c in PAIRS:
            j = line.find(o, line.rfind(c) + 1)
            while j != -1:
                out.append((start + j, end))
                j = line.find(o, j + 1)
        out += [(start + line.rfind(q), end) for q, _ in SYMMETRIC[2:] if line.count(q) % 2]
        start = end
    return out


# 第 2 步只用 ASCII 的 ' "（M8 最後審查之前的讀法，一字不差）；中文引號、反引號、全形引號的讀法（LATE，加上
# _unclosed）排在第 5 步之後：第 2–5 步原樣先跑完，M8 最後審查之前遮得到的一定遮得到；LATE 只把引號裡還剩下的
# 換成標籤，只會多遮。LATE 裡也有 ASCII 的讀法，只收裡面以 file:// 開頭的（第 2 步不收 ://，那是第 4 步遮的，可能遮到空白為止）
QUOTE_READINGS = _readings(SYMMETRIC[:2])
LATE_READINGS = _readings(SYMMETRIC, PAIRS)
# 剛好是一個標籤：path_label 回得出來的每一種樣子（<IPLOT>/、<PYTHON>/ 後面照留的那一段，也收第 7–10 步換進去的
# 記號，跟 SAFE 一樣）。LATE 裡面剛好是一個標籤的不換；「標籤＋還有字」的（<PATH>/.../<檔名已遮蔽> Xiaoming.txt）整段換
LABEL_EXT = r"(?:\.[A-Za-z0-9]{1,8})?"
PURE = re.compile(r"<IPLOT>/(?:(?i:core|ui|lib)/[^\\\n]*|(?i:main|config)\.py|[^/\\\n]*<(?:USER|下一層模組)>[^\\\n]*)"
                  r"|<PYTHON>/[^\\\n]*"
                  rf"|<模組:[^/\\\n]+?>/(?:\.\.\./<檔名已遮蔽>{LABEL_EXT}|[^/\\\n]+)"
                  rf"|<HOME>(?:/\.\.\./<檔名已遮蔽>{LABEL_EXT})?|(?:<PATH>/)?\.\.\./<檔名已遮蔽>{LABEL_EXT}")
# 第 2 步到最後那一次 ASCII 引號，整串最多重複幾次（見 redact）
ROUNDS = 10
# 括號裡的絕對路徑，整段（可以有空白）：ImportError 的 (…/My Drive/…/工具.py)
PAREN_ABS = re.compile(r"\((?P<p>(?:/|[A-Za-z]:[\\/]|\\\\)[^()\n]*)\)")
# 路徑開頭之後的延伸：吃到同一行裡、不跨過引號 ( ) < > 的最後一個 / 或 \，最後一段到空白、引號、括號為止。
# 中文的閉引號照吃：資料夾或檔名裡常有（《論語》心得_王小明.txt、「HK2」/…），停在那裡的話後半段連名字一起露出來
TAIL = r"(?:[^'\"\n()<>]*[/\\])?[^\s'\"()<>/\\]*"
# 第 4、5 步換出來、有遮掉東西的標籤（與出錯模組第一層的檔名）先做記號：< 後面一個私用字元。第 2 步再找一次之後，
# 記號的標籤後面接著的，中間那一段可以有 ( ) 與 '（Windows 的「新增資料夾 (2)」、Bob's 這種資料夾：TAIL 停在那裡的話
# 後半段連名字一起露出來）：到同一行裡、不跨過 " < > :// 的最後一個 / 或 \ 與後面那一段為止，路上碰到的記號的標籤
# （第 5 步從那個 / 起另外遮的後半段）一起併進一個標籤（只多遮）。不直接放寬 TAIL：放寬的 TAIL 會吃掉第 2 步再找一次
# 要用的引號、留著原樣的標籤（<IPLOT>/core/…）會把吃進去的字原樣留下來
MARK = "\ue000"
MARKED = rf"<{MARK}(?P<top>HOME|PATH|模組:[^/\\\n]+?)>(?:/\.\.\./<檔名已遮蔽>{LABEL_EXT}|/[^\s'\"()<>/\\]*)?"
LINK = r"(?:(?!://)[^\"\n<>])*"  # 中間那一段：不跨過 " < > 與 ://（網址；file:// 後面是另一個標籤）
EXTEND = re.compile(MARKED + rf"(?P<more>(?:{LINK}{MARKED.replace('?P<top>', '?:')})*(?:{LINK}[/\\][^\s'\"()<>/\\]+)?)")
# 已知開頭（第 4 步）後面要接的：分隔符號、空白、引號、) 或字串結尾——以分隔符號為界
KNOWN_END = r"(?=$|[/\\\s'\")])"
# 沒有引號的其他絕對路徑：前面只看 ASCII（中文字也算 \w）；POSIX 至少兩段、Windows 的 X:\ 或 X:/、UNC 的 \\。
# 緊接在冒號後面的也算（讀不到:/Volumes/…），:// 不算（網址；https://github.com/… 後面那幾段前面是英數字或 /）
OTHER_ABS = re.compile(r"(?<![A-Za-z0-9_>.~/\\-])(?!(?<=:)//)"
                       r"(?:/[^\s'\"()<>/\\]+(?=[/\\][^\s'\"()<>/\\])|(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\)" + TAIL)
# file:// 的網址：file:// 留著、後面的路徑換成標籤。file:///C:/… 的第三個 / 也留著，路徑從磁碟機開頭（家目錄才認得）；
# 遮過的 file:///<HOME>/… 也拆在同一個地方（冪等）
FILE = re.compile(r"file://(?:/(?=[A-Za-z]:[\\/]|<))?", re.IGNORECASE)
# 沒有引號的（第 4 步）：開頭之後第一個不是分隔符號的字要是路徑的字——不是 < 或 .（遮過的標籤不再換）、
# 不是中文的閉引號（「…file://」 的 file:// 後面沒有路徑）
FILE_URL = re.compile(rf"(?P<head>{FILE.pattern})(?=[/\\]*[^\s'\"()<>./\\」』”’》〉])(?P<path>{TAIL})", re.IGNORECASE)
# SyntaxError 訊息尾巴的 (檔名, line N)：檔名裡可以有一層括號（王小明 (1).py），不吃掉前面的 '(' was never closed
SYNTAX_FILE = re.compile(r"\((?P<f>[^()\n/\\<]+(?:\([^()\n/\\<]*\)[^()\n/\\<]*)*), line (?P<n>\d+)\)")
# SyntaxError 尾巴裡留著的檔名：iPLoT 自己的
KEEP_FILES = ("iplot.py", "config.py", "main.py")
# 遮出來的記號：第 7–10 步只換記號之外的字
TOKEN = re.compile(r"<(?:HOME|PATH|USER|EMAIL|IPLOT|PYTHON|疑似學號|下一層模組|檔名已遮蔽)>")
# 電子郵件
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 疑似學號：英文字母接 7–9 位數字、或 8–10 位數字；前後只看 ASCII（王小明B11201234 要中）
STUDENT_ID = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]\d{7,9}|\d{8,10})(?![A-Za-z0-9])")
# 留下來的副檔名
EXT = re.compile(r"\.[A-Za-z0-9]{1,8}")
# 分隔符號：/ 與 \ 都算，連續的當一個（Windows 的 repr 是兩個反斜線）
SEP = re.compile(r"[/\\]+")
# Windows 的磁碟機開頭（分隔符號換成 / 之後）
DRIVE = re.compile(r"[A-Za-z]:/")
# 換過之後還是 iPLoT 自己、Python 的 frame：原始碼留著。<IPLOT>/ 後面第一段含 <USER> 或 <下一層模組> 的也算：
# 帳號名或下一層模組的名字剛好是 core、lib、main、re 這種（是第一段的一部分），第一次遮完的標籤是
# <IPLOT>/<下一層模組>/runner.py、<IPLOT>/co<下一層模組>/…、<IPLOT>/<USER>.py；不認的話遮第二次會把留著的原始碼拿掉，不冪等
SAFE = re.compile(r"<PYTHON>/|<IPLOT>/(?:core/|ui/|lib/|main\.py|[^/]*<(?:USER|下一層模組)>)")
# 路徑被遮掉的記號：結果含這幾個的才算一個「路徑」
MASKED = ("<HOME>", "<PATH>", "<檔名已遮蔽>")
SKIPPED = "  （原始碼已略過）"
SHORT_USER = "你的使用者名稱太短，沒有自動遮，請自己找找看。"


@dataclass(frozen=True)
class Ctx:
    """這台機器上要認得的東西。都是字串；比對時不分大小寫、/ 與 \\ 都算分隔符號。"""
    home: str                       # 家目錄
    users: tuple[str, ...]          # 使用者名稱（去重）
    iplot: str                      # iPLoT 資料夾（app.home）
    pythons: tuple[str, ...]        # Python 的 prefix（含 realpath）
    module: str | None = None       # 出錯模組的「最上層」模組資料夾（report.module_of 算的）
    module_name: str | None = None  # 那個資料夾的名稱
    secrets: tuple[str, ...] = ()   # 一定要藏的字（中間那幾層下一層模組的名字）


def context(iplot, module=None, secrets=()) -> Ctx:
    """讀這台機器：家目錄、使用者名稱（getpass、USER、USERNAME、LOGNAME、家目錄最後一段；不分大小寫去重，
    留第一次出現的寫法）、Python 的 prefix（sys.prefix、base_prefix、exec_prefix 與它們的 realpath）；
    iplot 與 module 是 resolve 過的絕對路徑。"""
    home = str(Path.home())
    names = []
    with contextlib.suppress(ImportError, KeyError, OSError):  # 找不到名字：3.10、3.12 是 ModuleNotFoundError／KeyError，3.13 起是 OSError
        names.append(getpass.getuser())
    names += [os.environ.get(key, "") for key in ("USER", "USERNAME", "LOGNAME")]
    names.append(Path(home).name)
    users, seen = [], set()
    for name in names:
        if name and name.lower() not in seen:
            seen.add(name.lower())
            users.append(name)
    prefixes = (sys.prefix, sys.base_prefix, sys.exec_prefix)
    pythons = tuple(dict.fromkeys([*prefixes, *map(os.path.realpath, prefixes)]))
    folder = None if module is None else str(Path(module).resolve())
    return Ctx(home, tuple(users), str(Path(iplot).resolve()), pythons, folder,
               None if folder is None else Path(folder).name, tuple(secrets))


def _below(n: str, base: str | None) -> str | None:
    """n（分隔符號已經換成 /）在 base 底下就回相對路徑（n 原本的大小寫），等於 base 回 ""，都不是回 None。
    不分大小寫，以分隔符號為界：家目錄不吃到名字比較長的另一個家目錄。"""
    b = SEP.sub("/", base or "").rstrip("/")
    if not b or n[:len(b)].lower() != b.lower():
        return None
    rest = n[len(b):]
    if rest == "":
        return ""
    return rest[1:] if rest.startswith("/") else None


def _ext(name: str) -> str:
    """最後一段的副檔名，像副檔名的才留（.py、.csv），不然是空字串。"""
    suffix = PurePosixPath(name).suffix
    return suffix if EXT.fullmatch(suffix) else ""


def _file_url(s: str) -> tuple[str, str]:
    """file:// 的網址拆成 (開頭, 路徑)；不是的話開頭是空字串。"""
    m = FILE.match(s)
    return (m.group(), s[m.end():]) if m else ("", s)


def path_label(p: str, ctx: Ctx) -> str:
    """一個路徑換成什麼：iPLoT 自己的 <IPLOT>/…、Python 的 <PYTHON>/…、出錯模組第一層的 <模組:X>/檔名，
    其他都只留副檔名（<模組:X>/.../、<HOME>/.../、<PATH>/.../、.../ 加上 <檔名已遮蔽>）。以 < 開頭的原樣。"""
    if p.startswith("<"):
        return p
    n = SEP.sub("/", p)
    ext = _ext(n.rsplit("/", 1)[-1])
    rel = _below(n, ctx.iplot)
    if rel and (rel.lower().startswith(("core/", "ui/", "lib/")) or rel.lower() in ("main.py", "config.py")):
        return "<IPLOT>/" + rel
    # Python 的只認 prefix 底下的 lib/、lib64/（Windows 的 Lib/）：Linux 的 prefix 是 /usr，/usr/local/… 是使用者的。
    # prefix 是家目錄，或在 iPLoT、出錯的模組、家目錄的上面的（--prefix=$HOME 這種），整個不算
    mine = [SEP.sub("/", d) for d in (ctx.iplot, ctx.module, ctx.home) if d]
    for base in sorted(ctx.pythons, key=lambda b: len(SEP.sub("/", b)), reverse=True):  # 最長的先比
        rel = _below(n, base)
        if rel and rel.lower().startswith(("lib/", "lib64/")) and all(_below(d, base) is None for d in mine):
            return "<PYTHON>/" + rel
    rel = _below(n, ctx.module)
    if rel:
        return f"<模組:{ctx.module_name}>/" + (rel if "/" not in rel else f".../<檔名已遮蔽>{ext}")
    rel = _below(n, ctx.home)
    if rel == "":
        return "<HOME>"
    if rel is not None:
        return f"<HOME>/.../<檔名已遮蔽>{ext}"
    if n.startswith("/") or DRIVE.match(n):
        return f"<PATH>/.../<檔名已遮蔽>{ext}"
    return f".../<檔名已遮蔽>{ext}"


def _labeler(ctx: Ctx, counts: dict[str, int]):
    """path_label，順便數：換掉了、而且結果有遮掉東西的，算一個路徑。"""
    def label(p: str) -> str:
        out = path_label(p, ctx)
        if out != p and any(mark in out for mark in MASKED):
            counts["路徑"] += 1
        return out
    return label


def _frames(text: str, label, counts: dict[str, int]) -> str:
    """第 1 步：frame 的路徑換成標籤；不安全的 frame 底下的原始碼與 ~^ 標記換成一行「（原始碼已略過）」。"""
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        m = FRAME.match(lines[i])
        i += 1
        if m is None:
            out.append(lines[i - 1])
            continue
        lead, path = m["lead"], m["path"]
        new = label(path)
        out.append(f'{lead}File "{new}", line {m["n"]}{m["tail"]}')
        if SAFE.match(new) or FROZEN.fullmatch(path):
            continue
        prefix = lead[:lead.find("|") + 1]  # 到 | 為止（含 |）；沒有 | 是空字串
        depth = len(lead) - len(prefix)
        j = i
        while j < len(lines) and lines[j].startswith(prefix):  # 比 frame 那一行縮得深、不是下一個 frame 的
            rest = lines[j][len(prefix):]
            body = rest.lstrip(" \t")
            if len(rest) - len(body) <= depth or body.startswith('File "'):
                break
            j += 1
        if j > i:
            out.append(lead + SKIPPED)
            counts["原始碼"] += 1
            i = j
    return "\n".join(out)


def _outside(text: str, pattern: re.Pattern, repl: str, counts: dict[str, int], key: str) -> str:
    """只換記號之外的字：先用 TOKEN 切開（每次都重新切：前一個換出來的記號也擋住），只對記號之間的段落換。"""
    pieces, pos = [], 0
    for m in TOKEN.finditer(text):
        pieces += [text[pos:m.start()], m.group()]
        pos = m.end()
    pieces.append(text[pos:])
    for k in range(0, len(pieces), 2):
        pieces[k], n = pattern.subn(repl, pieces[k])
        counts[key] += n
    return "".join(pieces)


def redact(text: str, ctx: Ctx) -> tuple[str, dict[str, int]]:
    """遮蔽，冪等（遮過的再遮一次，字一樣）。回 (遮過的字, 統計)；統計的鍵是 KEYS，沒遮到的鍵是 0。"""
    counts = dict.fromkeys(KEYS, 0)
    label = _labeler(ctx, counts)
    # 1. frame
    text = _frames(text, label, counts)

    # 2. 引號裡的路徑：每一種讀法配出來的一對，裡面含 / 或 \、去掉頭尾空白之後不以 < 開頭（遮過的記號）、
    # 不含 ://（網址）的才算；重疊或共用一個引號的幾對合成一段。每一段裡面整個換成一個標籤，引號與頭尾的空白
    # 留在標籤外面（'HK2/…/成績.csv ' → '.../<檔名已遮蔽>.csv '）。
    # late（第 5 步之後那一次）：裡面去掉開頭的 file:// 再看（file:// 留在標籤外面），剛好是一個標籤的（PURE）不算，
    # 「標籤＋還有字」的整段換成一個標籤；ASCII 的引號只收 file:// 開頭的
    def quoted(text: str, readings, late=False) -> str:
        forward, back, n = *readings, len(text)
        pairs = [m.span(m.lastindex or 0) for pattern in forward for m in pattern.finditer(text)]  # 有第 1 組的用第 1 組
        pairs += [(n - m.end(), n - m.start()) for pattern in back for m in pattern.finditer(text[::-1])]
        pairs += _unclosed(text) if late else []
        spans, bare = [], -1  # bare：裡面沒有 / \ <HOME> 的那一對的結尾；同一個結尾、開頭更後面的也沒有
        for s, e in sorted(pairs):  # text[s] 是這一對的開引號（每一種讀法都是）
            if spans and e <= spans[-1][1] or e == bare:  # 整個在上一段裡、或一定不算的：不用看裡面（很多開引號的長行）
                continue
            head, inner = _file_url(text[s + 1:e - 1].strip()) if late else ("", text[s + 1:e - 1].strip())
            if late and (PURE.fullmatch(inner) or text[s] in ASCII_QUOTES and not head):
                continue
            path = "/" in inner or "\\" in inner or late and "<HOME>" in inner  # <HOME> 這個標籤沒有分隔符號
            if not path and not head:
                bare = e
            if not path or inner.startswith("<") and not late or "://" in inner:
                continue
            if spans and s < spans[-1][1]:  # 重疊，或這一對的開引號就是上一段的閉引號
                spans[-1] = (spans[-1][0], max(spans[-1][1], e))
            else:
                spans.append((s, e))
        out, pos = [], 0
        for s, e in spans:
            inner = text[s + 1:e - 1]
            lead, trail = inner[:len(inner) - len(inner.lstrip())], inner[len(inner.rstrip()):]
            head, inner = _file_url(inner.strip()) if late else ("", inner.strip())
            out += [text[pos:s + 1], lead, head, relabel(inner) if late else label(inner), trail]
            pos = e - 1
        return "".join(out) + text[pos:]

    def relabel(inner: str) -> str:
        """late 那一段的標籤：以 < 開頭的是前面的標籤＋還有字，開頭的 <HOME> 留著（不然是 <PATH>）、只留最後一段的副檔名。"""
        if PURE.fullmatch(inner):  # 幾對合成一段之後剛好是一個標籤
            return inner
        if not inner.startswith("<"):
            return label(inner)
        counts["路徑"] += 1
        top = "<HOME>" if inner.startswith("<HOME>") else "<PATH>"
        return f"{top}/.../<檔名已遮蔽>{_ext(SEP.split(inner)[-1])}"

    def mark(out: str) -> str:
        """第 4、5 步的標籤：有遮掉東西的（與出錯模組第一層的檔名）做記號，等一下往後延伸；<IPLOT>/、<PYTHON>/ 照留的不做。"""
        return "<" + MARK + out[1:] if out.startswith(("<HOME>", "<PATH>", "<模組:")) else out

    starts = []
    for s in (ctx.iplot, *ctx.pythons, ctx.module, ctx.home):
        s = (s or "").rstrip("/\\")
        if s:
            starts += [s.replace("\\", "/"), s.replace("/", "\\")]
    alts = "|".join(re.escape(s) for s in sorted(dict.fromkeys(starts), key=len, reverse=True))
    known = re.compile(f"(?:{alts}){KNOWN_END}{TAIL}", re.IGNORECASE) if starts else None

    def paths(text: str) -> str:
        """第 2–5 步（M8 最後審查之前的整串，原樣），接著往後延伸、中文引號那幾種的讀法、ASCII 引號再一次。"""
        text = quoted(text, QUOTE_READINGS)
        # 3. 括號裡的絕對路徑
        text = PAREN_ABS.sub(lambda m: "(" + label(m["p"]) + ")", text)
        # 4. 沒有引號的 file:// 網址（file:// 留著；排在其他絕對路徑前面：file:///D:/… 的 D: 後面那個 / 不是開頭），
        # 與沒有引號的已知開頭（長的先比；/ 與 \ 兩種寫法都試；不分大小寫）
        text = FILE_URL.sub(lambda m: m["head"] + mark(label(m["path"])), text)
        if known:
            text = known.sub(lambda m: mark(label(m.group())), text)
        # 5. 沒有引號的其他絕對路徑
        text = OTHER_ABS.sub(lambda m: mark(label(m.group())), text)
        # 第 2 步再找一次：第 3–5 步換出來的標籤緊貼著引號時（\\a'HK2/…' 的 \\a 換成標籤），那個引號才當得了開頭
        text = quoted(text, QUOTE_READINGS)
        # 第 4、5 步的標籤往後延伸（中間那一段可以有 ( ) '），拿掉記號
        text = EXTEND.sub(lambda m: f"<{m['top']}>/.../<檔名已遮蔽>{_ext(SEP.split(m['more'])[-1])}" if m["more"]
                          else m.group().replace(MARK, ""), text).replace("<" + MARK, "<")
        # 中文引號、反引號、全形引號（與 ASCII 引號裡的 file://）：第 2–5 步都跑完之後才配，只換引號裡還剩下的；
        # 接著 ASCII 引號再找一次
        return quoted(quoted(text + "\n", LATE_READINGS, late=True)[:-1], QUOTE_READINGS)

    # 整串重複到不再變為止：換掉的那一段裡的引號、括號不見了，剩下的兩兩配起來、第 3–5 步看到的可能不一樣
    # （幾對合成一段時前面那一對的閉引號被吃掉；括號裡的 ( 不見了，第 3 步才認得那一對括號），遮第二次才遮到的話
    # 不冪等。第一次就是 M8 最後審查之前的整串加上後面那幾步；之後每一次只把字換成標籤，幾次就停（ROUNDS 只是保險）
    for _ in range(ROUNDS):
        before, text = text, paths(text)
        if text == before:
            break

    # 6. SyntaxError 訊息尾巴的檔名
    def syntax(m: re.Match) -> str:
        if m["f"] in KEEP_FILES:
            return m.group()
        counts["路徑"] += 1
        return f"(<檔名已遮蔽>{_ext(m['f'])}, line {m['n']})"

    text = SYNTAX_FILE.sub(syntax, text)
    # 7–10. 只換記號之外的字；排在路徑規則後面（路徑先整段變成標籤）。長的先換：短的是長的一部分時才不會留下半截
    for secret in sorted(filter(None, ctx.secrets), key=len, reverse=True):
        text = _outside(text, re.compile(re.escape(secret), re.IGNORECASE), "<下一層模組>", counts, "下一層模組")
    text = _outside(text, EMAIL, "<EMAIL>", counts, "電子郵件")  # 信箱裡常常有帳號名：排在使用者名稱前面
    text = _outside(text, STUDENT_ID, "<疑似學號>", counts, "疑似學號")  # 中文的帳號名接著學號：也排在前面
    for user in sorted((u for u in ctx.users if len(u) >= 3), key=len, reverse=True):
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(user)}(?![A-Za-z0-9])", re.IGNORECASE)
        text = _outside(text, pattern, "<USER>", counts, "使用者名稱")
    return text, counts


def summary(counts: dict[str, int], ctx: Ctx) -> str:
    """頁面最上面那一行：「已自動遮蔽：3 個路徑、1 個使用者名稱。」；都是 0 就「沒有找到要自動遮的東西。」；
    使用者名稱有少於 3 個字的（沒有遮）再提醒一句。"""
    parts = [f"{counts[key]} 段原始碼" if key == "原始碼" else f"{counts[key]} 個{key}"
             for key in KEYS if counts.get(key)]
    text = "已自動遮蔽：" + "、".join(parts) + "。" if parts else "沒有找到要自動遮的東西。"
    return text + SHORT_USER if any(len(u) < 3 for u in ctx.users) else text
