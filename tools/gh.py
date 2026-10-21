"""機器人跟 GitHub 說話：讀表單、下載附件（轉址自己跟）、GitHub API（速率與寫入間隔）。

只用標準庫。下載附件的 fetch 永遠不送 Authorization、不知道 GH_TOKEN；只有 Api 帶 token。
"""

import hashlib
import http.client
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

from say import Refusal, refuse

API = "https://api.github.com"
API_VERSION = "2022-11-28"
USER_AGENT = "iplot-modules-bot"
MAX_ZIP = 25 * 1024 * 1024
DOWNLOAD_SECONDS = 60
HOP_TIMEOUT = 15
MAX_HOPS = 5
WRITE_GAP = 1.0
MAX_WAIT = 60
CHUNK = 64 * 1024
REQUEST_TIMEOUT = 30

HEADING_ZIP = "模組的 zip"
HEADING_NOTES = "這一版改了什麼（選填）"
HEADING_AGREE = "確認"
AGREE_TEXT = "我知道上傳的東西誰都看得到、誰都能下載執行；收到之後，這個名字只有我的帳號能更新。"
NO_RESPONSE = "_No response_"

# 檔名那一段等 Task 0 Step 10 再定；先照目前的規則（不支援括號、空白）
ATTACHMENT_RE = re.compile(r"https://github\.com/user-attachments/files/[0-9]+/[^/?#\s)\]]+\.zip")
URL_RE = re.compile(r"https?://[^\s)\]>]+")
DOWNLOAD_HOSTS = frozenset({"github.com", "objects.githubusercontent.com"})

LABELS = {
    "上傳": ("1d76db", "用表單上傳的模組，等機器人收"),
    "已發佈": ("0e8a16", "收進工作坊了"),
    "沒收": ("e4e669", "沒有收，原因在留言裡"),
    "卡住": ("d93f0b", "機器人處理不了，等研究助理"),
}
DONE = ("已發佈", "沒收", "卡住")


@dataclass(frozen=True)
class Form:
    attachments: tuple[str, ...]
    notes: str
    agreed: bool


def parse_body(body: str | None) -> Form:
    """照三個固定的標題、固定的順序切。notes 是上傳的人寫的，裡面的 ### 行不開新的一節。"""
    lines = (body or "").replace("\r\n", "\n").split("\n")

    def heading_at(title: str) -> list[int]:
        return [i for i, line in enumerate(lines) if line.rstrip() == f"### {title}"]

    zips, notes, agrees = heading_at(HEADING_ZIP), heading_at(HEADING_NOTES), heading_at(HEADING_AGREE)
    if not (zips and notes and agrees):
        return Form((), "", False)
    zip_at, agree_at = zips[0], agrees[-1]
    notes_at = next((i for i in notes if i > zip_at), None)
    if notes_at is None or notes_at >= agree_at:
        return Form((), "", False)

    section = "\n".join(lines[zip_at + 1:notes_at])
    attachments = tuple(u for u in URL_RE.findall(section) if ATTACHMENT_RE.fullmatch(u))
    text = "\n".join(lines[notes_at + 1:agree_at]).strip()
    boxes = {f"- [{mark}] {AGREE_TEXT}" for mark in "xX"}
    agreed = any(line.rstrip() in boxes for line in lines[agree_at + 1:])
    return Form(attachments, "" if text == NO_RESPONSE else text, agreed)


def form_refusal(form: Form) -> Refusal | None:
    if not form.attachments:
        return refuse("no_zip")
    if len(form.attachments) > 1:
        return refuse("many_zips")
    if not form.agreed:
        return refuse("not_agreed")
    return None


def allowed_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return parts.scheme == "https" and parts.hostname in DOWNLOAD_HOSTS and parts.port in (None, 443)
    except ValueError:
        return False


class DownloadError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class TooBig(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)
_REDIRECTS = (301, 302, 303, 307, 308)


def fetch(url: str, dest: Path, *, allowed=allowed_url, limit: int = MAX_ZIP, seconds: float = DOWNLOAD_SECONDS,
          clock=time.monotonic) -> str:
    """把 url 下載到 dest，回 sha256。轉址自己跟、每一站先過 allowed；永遠不送 Authorization。"""
    start = clock()
    try:
        return _fetch(url, dest, allowed, limit, seconds, clock, start)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def _fetch(url, dest, allowed, limit, seconds, clock, start) -> str:
    for _ in range(MAX_HOPS + 1):
        if not allowed(url):
            raise DownloadError(f"轉址到 {urlsplit(url).hostname}，不跟")
        left = seconds - (clock() - start)
        if left <= 0:
            raise DownloadError(f"超過 {seconds:g} 秒")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with _OPENER.open(request, timeout=min(HOP_TIMEOUT, left)) as response:
                return _save(response, dest, limit, seconds, clock, start)
        except urllib.error.HTTPError as exc:
            try:
                code, location = exc.code, exc.headers.get("Location")
            finally:
                exc.close()
            if code not in _REDIRECTS or not location:
                raise DownloadError(f"HTTP {code}") from None
            url = urljoin(url, location)
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as exc:
            reason = getattr(exc, "reason", None) or exc
            raise DownloadError(f"連不上：{reason}") from exc
    raise DownloadError("轉址太多次")


def _save(response, dest: Path, limit: int, seconds: float, clock, start: float) -> str:
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise TooBig
    digest, size = hashlib.sha256(), 0
    with dest.open("wb") as out:
        while True:
            chunk = response.read1(CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise TooBig
            digest.update(chunk)
            out.write(chunk)
            if clock() - start > seconds:
                raise DownloadError(f"超過 {seconds:g} 秒")
    # read1 在連線提早斷掉時只回 b""、不丟 IncompleteRead：宣告的長度沒讀滿就是下載不完整
    if declared and declared.isdigit() and size != int(declared):
        raise DownloadError("連不上：下載不完整")
    return digest.hexdigest()


class ApiError(Exception):
    def __init__(self, status: int, message: str = ""):
        super().__init__(f"HTTP {status} {message}".strip())
        self.status = status


class NotFound(ApiError):
    pass


class RateLimited(Exception):
    def __init__(self, wait: float):
        super().__init__(f"GitHub 要我們等 {wait:g} 秒")
        self.wait = wait


class Api:
    def __init__(self, token: str, repo: str, base: str = API, *, sleep=time.sleep, clock=time.monotonic,
                 now=time.time, urlopen=None):
        self.token, self.repo, self.base = token, repo, base
        self._sleep, self._clock, self._now = sleep, clock, now
        self._urlopen = urlopen or _OPENER.open
        self._last_write: float | None = None
        self.writes = 0

    def get(self, path: str, params: dict | None = None):
        return self._request("GET", path, params, None)

    def post(self, path: str, body: dict):
        return self._request("POST", path, None, body)

    def patch(self, path: str, body: dict):
        return self._request("PATCH", path, None, body)

    def _request(self, method: str, path: str, params: dict | None, body: dict | None):
        url = self.base + path + (f"?{urlencode(params)}" if params else "")
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        write = method != "GET"
        if write:
            self.writes += 1
        for attempt in (1, 2):
            if write and self._last_write is not None:
                gap = WRITE_GAP - (self._clock() - self._last_write)
                if gap > 0:
                    self._sleep(gap)
            request = urllib.request.Request(url, data=data, method=method, headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": USER_AGENT,
                **({"Content-Type": "application/json"} if data is not None else {}),
            })
            status, headers, text = self._send(request)
            if write:
                self._last_write = self._clock()
            if status < 300:
                try:
                    return json.loads(text) if text else None
                except ValueError as exc:
                    raise ApiError(status, "回應不是 JSON") from exc
            if status in (403, 429):
                wait = self._wait(status, headers, text)
                if wait is not None:
                    if wait > MAX_WAIT or attempt == 2:
                        raise RateLimited(wait)
                    self._sleep(wait)
                    continue
            if status == 404:
                raise NotFound(status, text[:200])
            raise ApiError(status, text[:200])
        raise AssertionError("unreachable")  # pragma: no cover

    def _send(self, request) -> tuple[int, http.client.HTTPMessage, str]:
        try:
            with self._urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return response.status, response.headers, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, exc.headers, exc.read().decode("utf-8", "replace")
            finally:
                exc.close()
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            raise ApiError(0, str(getattr(exc, "reason", None) or exc)) from exc

    def _wait(self, status: int, headers, text: str) -> float | None:
        """是速率限制的話要等幾秒；不是就 None。"""
        retry_after = headers.get("retry-after")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        if headers.get("x-ratelimit-remaining") == "0":
            try:
                return max(0.0, float(headers.get("x-ratelimit-reset", "")) - self._now())
            except ValueError:
                pass
        if status == 429 or "secondary rate limit" in text.lower():
            return 60.0
        return None


def ensure_labels(api) -> None:
    path = f"/repos/{api.repo}/labels"
    have = {label["name"] for label in api.get(path, {"per_page": 100})}
    for name, (color, description) in LABELS.items():
        if name not in have:
            api.post(path, {"name": name, "color": color, "description": description})


def open_uploads(api) -> list[dict]:
    issues = api.get(f"/repos/{api.repo}/issues", {
        "state": "open", "labels": "上傳", "sort": "created", "direction": "asc", "per_page": 100})
    keep = [i for i in issues
            if "pull_request" not in i and not any(label["name"] in DONE for label in i.get("labels", []))]
    return sorted(keep, key=lambda i: i["number"])


def has_marker(api, number: int, mark: str) -> bool:
    comments = api.get(f"/repos/{api.repo}/issues/{number}/comments", {"per_page": 100})
    return any(mark in (c.get("body") or "") for c in comments)


def comment(api, number: int, body: str) -> None:
    api.post(f"/repos/{api.repo}/issues/{number}/comments", {"body": body})


def set_state(api, number: int, labels: list[str], state: str | None = None, reason: str | None = None) -> None:
    body: dict = {"labels": labels}
    if state:
        body["state"] = state
    if reason:
        body["state_reason"] = reason
    api.patch(f"/repos/{api.repo}/issues/{number}", body)


def login_of(api, user_id: int) -> str:
    return api.get(f"/user/{user_id}")["login"]
