"""抓 LINE 的網址：用 urllib，只 GET，有逾時、大小上限、不跟轉址；所有錯誤變成 LineError（一句話、不含網址）。

- 網址只經過 line_url.validate；抓到的 JSON 只檢查「是不是 JSON 物件」，欄位的檢查是 line_data.parse 的事。
- 逾時 15 秒（docs/07 第 6 節：讀 json 15 秒），整個回應最多 2 倍時間；最多讀 2 MiB，超過就放棄。
- **不跟轉址**：轉到別的主機會把 token 一起帶過去。https:// 驗證憑證，不關；python.org 的 macOS Python 沒有根憑證時，
  改用 macOS 自己的 /etc/ssl/cert.pem（docs/07 第 6 節的做法）。
- **LineError 的訊息是我們自己寫的，不用 str(exc)**：URLError、InvalidURL 的訊息可能含網址，而錯誤回報會把訊息送出去。
  原本的例外不掛在 __cause__／__context__ 上，也不留 url、fp。
這個檔只用標準庫、不 import core。"""

import contextlib
import datetime
import email.utils
import errno
import http.client
import json
import math
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import line_url

TIMEOUT = 15
MAX_BYTES = 2 * 1024 * 1024
CHUNK = 64 * 1024
USER_AGENT = "iPLoT-calendar2/0.1.0"  # 一般的名字，不放任何個人資料（標頭要 ASCII）
MAC_CERT_FILE = "/etc/ssl/cert.pem"
RETRY_DEFAULT, RETRY_MIN, RETRY_MAX = 60, 1, 3600
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
_SECONDS = re.compile(r"[+-]?[0-9]+", re.ASCII)
STATUS_KIND = {400: "bad_range", 404: "not_found", 405: "method"}
_OFFLINE = (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN, errno.EHOSTDOWN)
RESET = "LINE 說找不到：網址可能已經重設，請私訊 bot『連上iPLoT』拿新的"
MESSAGES = {
    "not_found": RESET,
    "bad_range": "LINE 說日期範圍不對（只能看今天前後 400 天、一次最多 100 天）",
    "method": "LINE 拒絕這種請求（方法不對）。這是程式的問題，請回報",
    "redirect": "LINE 的網址被轉到別的地方，已拒絕",
    "timeout": "連不上 LINE（逾時）",
    "offline": "連不上 LINE（沒有網路）",
    "dropped": "連不上 LINE（連線中斷）",
    "tls": "連不上 LINE（加密連線失敗）",
    "certificate": "連不上 LINE（憑證驗證失敗）",
    "network": "連不上 LINE（網路錯誤）",
    "bad_url": line_url.BAD_URL_MESSAGE,
}


class LineError(Exception):
    """抓不到或不能用。kind 是種類（not_found、rate_limit、timeout…）；message 是一句話，不含網址；
    retry_after 只有 rate_limit 有（幾秒後可以再試）。"""

    def __init__(self, kind: str, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.kind, self.message, self.retry_after = kind, message, retry_after


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """不跟轉址：回 None 就會變成 HTTPError（3xx）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def make_context(*, create=ssl.create_default_context, cert_file: str = MAC_CERT_FILE, exists=os.path.exists):
    """驗證 https 憑證用的設定。預設的憑證庫是空的（python.org 的 macOS Python），又有 cert_file，就載入它；驗證本身不關。"""
    context = create()
    if not context.cert_store_stats().get("x509_ca", 0) and exists(cert_file):
        context.load_verify_locations(cert_file)
    return context


def default_opener():
    return urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=make_context()))


def parse_retry_after(value, now: float) -> int:
    """Retry-After（秒數或 HTTP 日期）→ 幾秒，夾在 1 到 3600 之間；沒有或看不懂就 60。"""
    text = "" if value is None else str(value).strip()
    if _SECONDS.fullmatch(text):
        seconds = int(text)
    else:
        try:
            when = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return RETRY_DEFAULT
        if when.tzinfo is None:
            when = when.replace(tzinfo=datetime.timezone.utc)
        seconds = math.ceil(when.timestamp() - now)
    return max(RETRY_MIN, min(RETRY_MAX, seconds))


def _limit_text(max_bytes: int) -> str:
    return f"{max_bytes / 1048576:g} MiB" if max_bytes >= 1048576 else f"{max_bytes} bytes"


def _http_problem(code: int, retry_after: int | None) -> LineError:
    if code == 429:
        return LineError("rate_limit", f"LINE 說請求太多，{retry_after} 秒後可以再更新", retry_after)
    if 300 <= code < 400:
        return LineError("redirect", MESSAGES["redirect"])
    if code >= 500:
        return LineError("server", f"LINE 那邊出錯了（HTTP {code}），晚點再試")
    if code in STATUS_KIND:
        return LineError(STATUS_KIND[code], MESSAGES[STATUS_KIND[code]])
    return LineError("http", f"LINE 回了 HTTP {code}，這個網址用不了")


def _classify(exc: BaseException, now) -> LineError:
    """例外 → LineError。只看例外的種類與錯誤碼，不看（也不複製）它的訊息。"""
    if isinstance(exc, urllib.error.HTTPError):
        retry = parse_retry_after(exc.headers.get("Retry-After") if exc.headers else None, now()) if exc.code == 429 else None
        with contextlib.suppress(OSError, AttributeError):
            exc.close()
        return _http_problem(exc.code, retry)
    if isinstance(exc, urllib.error.URLError):
        return _classify(exc.reason, now) if isinstance(exc.reason, BaseException) else LineError("network", MESSAGES["network"])
    if isinstance(exc, http.client.InvalidURL):
        return LineError("bad_url", MESSAGES["bad_url"])
    if isinstance(exc, ssl.SSLCertVerificationError):
        kind = "certificate"
    elif isinstance(exc, ssl.SSLError):
        kind = "tls"
    elif isinstance(exc, TimeoutError):
        kind = "timeout"
    elif isinstance(exc, (socket.gaierror, ConnectionRefusedError)):
        kind = "offline"
    elif isinstance(exc, (ConnectionError, http.client.HTTPException)):
        kind = "dropped"
    elif isinstance(exc, OSError) and exc.errno in _OFFLINE:
        kind = "offline"
    else:
        kind = "network"
    return LineError(kind, MESSAGES[kind])


def _request(url, from_, to) -> urllib.request.Request:
    if (from_ is None) != (to is None):
        raise ValueError("from 與 to 要一起給")
    try:
        full = line_url.validate(url)
    except line_url.BadUrl:
        raise LineError("bad_url", MESSAGES["bad_url"]) from None
    if from_ is not None:
        for day in (from_, to):
            try:
                if not isinstance(day, str) or not _DATE.fullmatch(day):
                    raise ValueError
                datetime.date.fromisoformat(day)
            except ValueError:
                raise LineError("bad_range", MESSAGES["bad_range"]) from None
        full += "?" + urllib.parse.urlencode({"from": from_, "to": to})
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    return urllib.request.Request(full, method="GET", headers=headers)  # noqa: S310  line_url.validate 只放行 https://


def _read(response, max_bytes: int, timeout: float, clock) -> bytes:
    """最多讀 max_bytes；宣告的長度就超過、或讀超過了就放棄；整個讀取最多 2 倍逾時（防一點一點滴的伺服器）。"""
    too_big = LineError("too_big", f"LINE 回的資料超過 {_limit_text(max_bytes)}，已拒絕")
    declared = (response.headers.get("Content-Length") if response.headers else None) or ""
    if declared.strip().isdigit() and int(declared) > max_bytes:
        raise too_big
    deadline, chunks, total = clock() + 2 * timeout, [], 0
    while True:
        chunk = response.read(min(CHUNK, max_bytes + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise too_big
        if clock() > deadline:
            raise LineError("timeout", MESSAGES["timeout"])


def fetch(url, from_: str | None = None, to: str | None = None, *, opener=None, timeout: float = TIMEOUT,
          max_bytes: int = MAX_BYTES, now=time.time, clock=time.monotonic) -> dict:
    """GET <url>[?from=…&to=…]，回 JSON 物件（還沒檢查欄位）。from_、to 要一起給或都不給。失敗丟 LineError。"""
    request = _request(url, from_, to)
    problem, body = None, b""
    try:
        with contextlib.closing((opener or default_opener()).open(request, timeout=timeout)) as response:
            body = _read(response, max_bytes, timeout, clock)
    except (OSError, http.client.HTTPException, ValueError) as exc:
        problem = _classify(exc, now)
    if problem is not None:
        raise problem  # 在 except 外面丟：原本的例外（可能帶著網址）不會掛在 __context__ 上
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        data = None
    if not isinstance(data, dict):
        raise LineError("format", "LINE 回的資料格式不對（不是 JSON 物件），沒有更新快取")
    return data
