"""LINE 網址：檢查、遮罩。網址等於密碼（https://<網域>/j/<token>.json，見 LINE bot 的 iPLoT-資料格式.md）。

只收 https://<網域>[:埠]/j/<token>.json，token 只含 [A-Za-z0-9_-]、長度 20–128（bot 目前是 40–64；字元集嚴格、
長度放寬，bot 改長度時這邊不會壞，L04）；不收帳號密碼、查詢字串、片段、空白與控制字元、IP 位址。
錯誤一律是固定的一句話，**不回顯使用者貼的內容**；畫面、訊息、log 只用 mask() 的結果。
這個檔只用標準庫、不 import core。"""

import hashlib
import re

BAD_URL_MESSAGE = ("這不是 iPLoT 的網址：要以 https:// 開頭、結尾是 /j/<一串字>.json。"
                   "請私訊 bot『連上iPLoT』拿網址。")
UNKNOWN_MASK = "（網址格式不對，已隱藏）"
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_URL = re.compile(rf"https://(?P<host>{_LABEL}(?:\.{_LABEL})*)(?::(?P<port>[0-9]{{1,5}}))?"
                  r"/j/(?P<token>[A-Za-z0-9_-]{20,128})\.json", re.ASCII)
_IPV4 = re.compile(r"[0-9.]+", re.ASCII)


class BadUrl(ValueError):
    """網址不合格。訊息固定，不含輸入。"""

    def __init__(self) -> None:
        super().__init__(BAD_URL_MESSAGE)


def _parse(text) -> tuple[str, str | None, str] | None:
    """(主機, 埠, token)；不合格回 None。"""
    if not isinstance(text, str):
        return None
    match = _URL.fullmatch(text.strip(" \t\r\n"))
    if match is None:
        return None
    host, port = match.group("host"), match.group("port")
    if len(host) > 253 or _IPV4.fullmatch(host) or (port is not None and not 1 <= int(port) <= 65535):
        return None
    return host, port, match.group("token")


def validate(text) -> str:
    """合格就回去掉前後空白的網址；不合格丟 BadUrl（訊息固定、不含輸入）。"""
    if _parse(text) is None:
        raise BadUrl from None
    return text.strip(" \t\r\n")


def mask(text) -> str:
    """給人看的版本：https://<主機>[:埠]/j/AbCd…wXyZ.json（token 只留前 4、後 4）。不合格的不回顯，回 UNKNOWN_MASK。"""
    parsed = _parse(text)
    if parsed is None:
        return UNKNOWN_MASK
    host, port, token = parsed
    return f"https://{host}{f':{port}' if port else ''}/j/{token[:4]}…{token[-4:]}.json"


def token_of(text) -> str:
    """合格網址的 token（抓網址、算帳號用；不放進任何訊息）。"""
    parsed = _parse(text)
    if parsed is None:
        raise BadUrl from None
    return parsed[2]


def account_id(text) -> str:
    """token 的 sha256 前 12 碼：只用來判斷「這份快取是不是這個網址的」，推不回 token。"""
    return hashlib.sha256(token_of(text).encode("ascii")).hexdigest()[:12]
