"""機器人回覆的句子：設計第 10 節的表（逐字）、加上表裡沒有的幾句（設計第 5.2、7、8 節）。

從使用者來的字串（名稱、帳號名、路徑、版本、訊息）一律經過 code()：issue 的字是資料，
放進回覆時不能變成 @ 提及、#1 連結或 markdown。
"""

from collections.abc import Iterable
from dataclasses import dataclass

from iplot_rules import BAD_NAME_TEXT

SAY: dict[str, str] = {
    "not_user": "只收一般帳號上傳的。",
    "gone": "上傳的帳號已經不在了，不收。",
    "no_zip": "沒有找到 zip：把模組資料夾壓成 .zip，拖進「模組的 zip」那一格。",
    "many_zips": "一次只能傳一個 zip。",
    "not_agreed": "沒有勾「我知道…」：用表單重新開一個，勾了再送出。",
    "download": "下載不到附件（{reason}）。等一下再開一個新的。",
    "too_big": "zip 超過 25 MB。",
    "not_zip": "附件不是 zip。",
    "broken": "這個 zip 打不開或壞了（{kind}）：用 Finder 重新壓縮一次，不要加密碼。",
    "shape": "zip 裡要剛好是一個資料夾（模組的資料夾），裡面有 iplot.py（檔名全小寫）：在 Finder 對著那個資料夾按右鍵「壓縮」。",
    "bad_path": "zip 裡有不能用的路徑：{path}（..、絕對路徑、反斜線、控制字元、Windows 不能用的字元與保留字、"
                "結尾是 . 或空白、空的一段、重複或只差大小寫、檔跟資料夾同名）。",
    "names_not_utf8": "zip 裡的檔名不是 UTF-8（舊的 Windows 內建壓縮會這樣）：在 Mac 上用 Finder 壓縮，或用 7-Zip。",
    "too_large": "解開之後超過 100 MB。",
    "too_many_files": "解開之後超過 2000 個檔。",
    "too_many_entries": "zip 裡的條目太多（超過 20000 條）。",
    "bad_name": BAD_NAME_TEXT,
    "invisible": "名稱裡有看不見的字元、特別的空白，或混用了不同文字的字母：用一般的字重新取名。",
    "similar": "「{name}」跟「{other}」太像：換一個名字。",
    "reserved": "「{name}」是 iPLoT 自己要用的模組，不能上傳。",
    "removed": "「{name}」已經下架；有問題找研究助理（README 的聯絡方式）。",
    "taken": "「{name}」已經是別的帳號（{owner}）的模組；換一個名字（改資料夾名稱）再傳。",
    "title_taken": "iplot.py 的 TITLE「{title}」是別人的、保留的，或太像別人的名字：拿掉 TITLE，或改成自己的名稱。",
    "case": "大小寫要跟第一次一樣：這個名字第一次傳的是「{first}」。",
    "too_many_uploads": "這個帳號 24 小時內已經傳了 {n} 份：明天再傳，或找研究助理。",
    "too_many_names": "這個帳號已經有 {n} 個名字：明天再傳，或找研究助理。",
    "full": "工作坊的空間快滿了，研究助理處理中；暫時不收新的名字。",
    "syntax": "iplot.py 第 {line} 行：{message}。",
    "syntax_310": "iplot.py 第 {line} 行：{message}。iPLoT 要能在 Python 3.10 跑。",
    "not_utf8": "iplot.py 不是 UTF-8：用 UTF-8 存檔再傳。",
    "too_complex": "iplot.py 解析不了（太複雜）。",
    "changelog": "CHANGELOG.md 讀不出最上面那一版：{reason}。",
    "not_newer": "CHANGELOG.md 最上面那一節的版本 {v} 不比現在的 {cur} 新：把版本號加大再傳。",
    "blocked": "推不上去（{reason}）：多半是檔案裡有密碼或金鑰，拿掉再傳。",
    "retry": "這次沒收成，一小時內會自動再試；一天後還是這樣，在這裡留言。",
    "stuck": "機器人處理不了這份上傳，研究助理會看。",
    "iplot_big": "iplot.py 超過 1 MB。",
    "bad_version": "版本不是 1.2.0 這種寫法：{version}。",
    "not_writable": "這份 zip 寫不進 repo。",
    "held": "{reason}",
}


@dataclass(frozen=True)
class Refusal:
    key: str
    text: str


def _longest_run(text: str) -> int:
    longest = run = 0
    for ch in text:
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    return longest


def code(text: str) -> str:
    """行內程式碼：反引號的數目比內容裡最長的一串多一個；開頭或結尾是反引號、或頭尾都是空白時兩邊補一個空白。"""
    fence = "`" * (_longest_run(text) + 1)
    pad = text.startswith("`") or text.endswith("`") or (bool(text) and text[0].isspace() and text[-1].isspace())
    return f"{fence} {text} {fence}" if pad else f"{fence}{text}{fence}"


def block(lines: Iterable[str]) -> str:
    """程式碼區塊：圍欄比內容裡最長的一串反引號長（至少三個）。"""
    body = "\n".join(lines)
    fence = "`" * max(3, _longest_run(body) + 1)
    return f"{fence}\n{body}\n{fence}"


def clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[: limit - 1] + "…", True


def refuse(key: str, **params: str | int) -> Refusal:
    shown = {k: str(v) if isinstance(v, int) else code(v) for k, v in params.items()}
    return Refusal(key, SAY[key].format(**shown))
