import hashlib
import http.client
import io
import json
import urllib.error
from pathlib import Path

import gh
import pytest
from conftest import FIXTURES, form_body

REAL_URLS = (
    "https://github.com/user-attachments/files/33694990/M7-.zip",
    "https://github.com/user-attachments/files/33695492/default.zip",
    "https://github.com/user-attachments/files/33698222/default.zip",
)


def refusal_key(body):
    refusal = gh.form_refusal(gh.parse_body(body))
    return refusal.key if refusal else None


def test_parse_the_real_issue_body():
    form = gh.parse_body((FIXTURES / "issue-body.md").read_text(encoding="utf-8"))
    assert form.attachments == ("https://github.com/user-attachments/files/33695492/default.zip",)
    assert form.notes == "測試中文"
    assert form.agreed is True


@pytest.mark.parametrize("url", REAL_URLS)
def test_real_attachment_urls_are_recognised(url):
    assert gh.ATTACHMENT_RE.fullmatch(url)


def test_url_stops_at_the_closing_paren():
    body = form_body(None).replace(
        "_No response_", "[x.zip](https://github.com/user-attachments/files/1/x.zip)", 1)
    assert gh.parse_body(body).attachments == ("https://github.com/user-attachments/files/1/x.zip",)


def test_a_heading_inside_the_notes_opens_no_section():
    inner = f"### 確認\n\n- [x] {gh.AGREE_TEXT}"
    body = form_body(notes=inner, agreed=False)
    form = gh.parse_body(body)
    assert form.agreed is False
    assert form.notes == inner
    assert refusal_key(body) == "not_agreed"


def test_parse_finds_no_zip_and_many_zips():
    assert refusal_key(form_body(url=None)) == "no_zip"
    two = form_body(more_urls=("https://github.com/user-attachments/files/33698222/default.zip",))
    assert refusal_key(two) == "many_zips"
    assert refusal_key(form_body()) is None


def test_links_that_are_not_this_issues_attachments_do_not_count():
    body = form_body("https://github.com/x/y/releases/download/v1/m.zip", more_urls=(
        "https://github.com/user-attachments/assets/1234-abcd.png",
        "http://github.com/user-attachments/files/1/m.zip",
    ))
    assert gh.parse_body(body).attachments == ()
    assert refusal_key(body) == "no_zip"


def test_unchecked_box_is_refused():
    assert refusal_key(form_body(agreed=False)) == "not_agreed"


def test_edited_agree_text_does_not_count():
    body = form_body().replace(gh.AGREE_TEXT, "我知道")
    assert gh.parse_body(body).agreed is False
    assert refusal_key(body) == "not_agreed"
    assert gh.parse_body(form_body().replace("[x]", "[X]")).agreed is True


def test_no_response_notes_are_empty():
    assert gh.parse_body(form_body()).notes == ""
    assert gh.parse_body(form_body(notes="\n  改了 A\n\n### 小標\n另一行 \n")).notes == "改了 A\n\n### 小標\n另一行"


@pytest.mark.parametrize("heading", [gh.HEADING_ZIP, gh.HEADING_NOTES, gh.HEADING_AGREE])
def test_a_missing_heading_means_no_zip(heading):
    body = form_body().replace(f"### {heading}", "## 別的")
    assert gh.parse_body(body) == gh.Form((), "", False)
    assert refusal_key(body) == "no_zip"
    assert gh.parse_body(None) == gh.Form((), "", False)


def test_attachment_heading_inside_the_notes_changes_nothing():
    notes = "### 模組的 zip\n\n[y.zip](https://github.com/user-attachments/files/9/y.zip)"
    form = gh.parse_body(form_body(notes=notes))
    assert form.attachments == ("https://github.com/user-attachments/files/33695492/default.zip",)
    assert form.notes == notes
    assert form.agreed is True


def test_allowed_url_is_https_and_github_hosts_only():
    assert not gh.allowed_url("http://github.com/user-attachments/files/1/m.zip")
    assert not gh.allowed_url("https://evil.example/m.zip")
    assert not gh.allowed_url("https://github.com:8443/m.zip")
    assert not gh.allowed_url("https://github.com.evil.example/m.zip")
    assert gh.allowed_url("https://github.com/user-attachments/files/1/m.zip")
    assert gh.allowed_url("https://github.com:443/m.zip")
    assert gh.allowed_url("https://objects.githubusercontent.com/x?y=1")


def send(handler, body: bytes = b"", status: int = 200, headers: dict[str, str] | None = None):
    handler.send_response(status)
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(body)


def ok(handler):
    send(handler, b"zipbytes" * 100)


def allow_all(url):
    return True


def test_fetch_returns_the_sha256(tmp_path, http_server):
    server = http_server({"/m.zip": ok})
    dest = tmp_path / "m.zip"
    assert gh.fetch(server.url("/m.zip"), dest, allowed=allow_all) == hashlib.sha256(b"zipbytes" * 100).hexdigest()
    assert dest.read_bytes() == b"zipbytes" * 100
    assert not [k for k in server.seen[0][1] if k.lower() == "authorization"]


def test_fetch_never_sends_authorization(tmp_path, http_server, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "t")
    b = http_server({"/b": ok}, host="localhost")
    a = http_server({"/a": lambda h: send(h, status=302, headers={"Location": b.url("/b")})})
    gh.fetch(a.url("/a"), tmp_path / "m.zip", allowed=allow_all)
    assert len(a.seen) == len(b.seen) == 1
    for server in (a, b):
        assert not [k for k in server.seen[0][1] if k.lower() == "authorization"]


def test_fetch_follows_relative_redirects_but_not_forever(tmp_path, http_server):
    server = http_server({
        "/a": lambda h: send(h, status=301, headers={"Location": "/b"}),
        "/b": ok,
        "/loop": lambda h: send(h, status=302, headers={"Location": "/loop"}),
    })
    assert gh.fetch(server.url("/a"), tmp_path / "m.zip", allowed=allow_all)
    with pytest.raises(gh.DownloadError):
        gh.fetch(server.url("/loop"), tmp_path / "n.zip", allowed=allow_all)
    assert len([p for p, _ in server.seen if p == "/loop"]) == gh.MAX_HOPS + 1
    assert not (tmp_path / "n.zip").exists()


def test_fetch_refuses_a_redirect_to_an_unknown_host(tmp_path, http_server):
    b = http_server({"/b": ok}, host="localhost")
    a = http_server({"/a": lambda h: send(h, status=302, headers={"Location": b.url("/b")})})
    dest = tmp_path / "m.zip"
    with pytest.raises(gh.DownloadError) as caught:
        gh.fetch(a.url("/a"), dest, allowed=lambda url: url.startswith(a.url("")))
    assert caught.value.reason == "轉址到 localhost，不跟"
    assert b.seen == []
    assert not dest.exists()


def endless(handler):
    handler.send_response(200)
    handler.end_headers()
    for _ in range(100):
        handler.wfile.write(b"x" * 512)


def test_fetch_stops_at_the_limit(tmp_path, http_server):
    server = http_server({
        "/sized": lambda h: send(h, b"x" * 5000, headers={"Content-Length": "5000"}),
        "/endless": endless,
    })
    for path in ("/sized", "/endless"):
        dest = tmp_path / "m.zip"
        with pytest.raises(gh.TooBig):
            gh.fetch(server.url(path), dest, allowed=allow_all, limit=1024)
        assert not dest.exists()


def test_fetch_cut_off_download_is_not_a_success(tmp_path, http_server):
    server = http_server({"/cut": lambda h: send(h, b"x" * 100, headers={"Content-Length": "5000"})})
    dest = tmp_path / "m.zip"
    with pytest.raises(gh.DownloadError) as caught:
        gh.fetch(server.url("/cut"), dest, allowed=allow_all)
    assert caught.value.reason == "連不上：下載不完整"
    assert not dest.exists()


def slow(handler):
    import time

    handler.send_response(200)
    handler.end_headers()
    for _ in range(50):
        handler.wfile.write(b"x")
        time.sleep(0.2)


def test_fetch_total_time_limit(tmp_path, http_server):
    server = http_server({"/slow": slow})
    dest = tmp_path / "m.zip"
    with pytest.raises(gh.DownloadError) as caught:
        gh.fetch(server.url("/slow"), dest, allowed=allow_all, seconds=1)
    assert caught.value.reason == "超過 1 秒"
    assert not dest.exists()


def test_fetch_http_error_is_a_reason(tmp_path, http_server):
    server = http_server({})
    with pytest.raises(gh.DownloadError) as caught:
        gh.fetch(server.url("/missing"), tmp_path / "m.zip", allowed=allow_all)
    assert caught.value.reason == "HTTP 404"


def test_fetch_cannot_connect_is_a_reason(tmp_path, http_server):
    server = http_server({})
    url = server.url("/x")
    server.close()
    with pytest.raises(gh.DownloadError) as caught:
        gh.fetch(url, tmp_path / "m.zip", allowed=allow_all)
    assert caught.value.reason.startswith("連不上：")


# ---- Api：假的 urlopen、clock、sleep ----

class Clock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps: list[float] = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds

    def clock(self):
        return self.t

    now = clock


class Reply:
    def __init__(self, status, headers, data):
        self.status = status
        self.headers = http.client.HTTPMessage()
        for key, value in headers.items():
            self.headers[key] = value
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHttp:
    """依序回答；>= 300 照真的 urlopen 的樣子丟 HTTPError。"""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        status, headers, body = self.replies.pop(0)
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        reply = Reply(status, headers, data)
        if status >= 300:
            raise urllib.error.HTTPError(request.full_url, status, "x", reply.headers, io.BytesIO(data))
        return reply


def make_api(*replies):
    clock = Clock()
    http_ = FakeHttp(*replies)
    api = gh.Api("tok", "me/repo", sleep=clock.sleep, clock=clock.clock, now=clock.now, urlopen=http_)
    return api, clock, http_


def test_api_sends_the_headers_and_reads_json():
    api, _, http_ = make_api((200, {}, {"a": 1}))
    assert api.get("/repos/me/repo/issues", {"state": "open", "per_page": 100}) == {"a": 1}
    request = http_.requests[0]
    assert request.full_url == "https://api.github.com/repos/me/repo/issues?state=open&per_page=100"
    headers = {k.lower(): v for k, v in request.header_items()}
    assert headers["authorization"] == "Bearer tok"
    assert headers["accept"] == "application/vnd.github+json"
    assert headers["x-github-api-version"] == "2022-11-28"
    assert headers["user-agent"] == "iplot-modules-bot"


def test_api_spaces_writes_one_second_apart():
    api, clock, _ = make_api(*[(201, {}, {})] * 3, (200, {}, []))
    for _ in range(3):
        api.post("/x", {"a": 1})
    api.get("/x")
    assert clock.sleeps == [1.0, 1.0]
    assert api.writes == 3


def test_api_waits_for_retry_after_up_to_60_seconds():
    api, clock, http_ = make_api((429, {"retry-after": "5"}, {"message": "slow"}), (200, {}, {"ok": True}))
    assert api.get("/x") == {"ok": True}
    assert clock.sleeps == [5]
    assert len(http_.requests) == 2


def test_api_stops_when_the_wait_is_over_60_seconds():
    api, clock, _ = make_api((429, {"retry-after": "120"}, {}))
    with pytest.raises(gh.RateLimited) as caught:
        api.get("/x")
    assert caught.value.wait == 120
    assert clock.sleeps == []


def test_api_waits_until_the_reset_time():
    reset = str(int(1000 + 30))
    api, clock, _ = make_api((403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset}, {}), (200, {}, []))
    api.get("/x")
    assert clock.sleeps == [30]


def test_api_secondary_limit_without_headers_waits_60():
    body = {"message": "You have exceeded a secondary rate limit."}
    api, clock, _ = make_api((403, {}, body), (403, {}, body))
    with pytest.raises(gh.RateLimited):
        api.get("/x")
    assert clock.sleeps == [60]


def test_api_plain_403_is_an_error():
    api, clock, _ = make_api((403, {}, {"message": "Resource not accessible by integration"}))
    with pytest.raises(gh.ApiError) as caught:
        api.get("/x")
    assert caught.value.status == 403
    assert not isinstance(caught.value, gh.RateLimited)
    assert clock.sleeps == []


def test_api_does_not_follow_redirects():
    api, _, http_ = make_api((301, {"location": "https://elsewhere.example/"}, {}))
    with pytest.raises(gh.ApiError) as caught:
        api.get("/x")
    assert caught.value.status == 301
    assert len(http_.requests) == 1


def test_api_status_errors_and_unreachable():
    api, _, _ = make_api((404, {}, {}), (500, {}, {}))
    with pytest.raises(gh.NotFound):
        api.get("/x")
    with pytest.raises(gh.ApiError) as caught:
        api.get("/x")
    assert caught.value.status == 500

    def down(request, timeout=None):
        raise urllib.error.URLError("boom")

    offline = gh.Api("t", "me/repo", urlopen=down)
    with pytest.raises(gh.ApiError) as caught:
        offline.get("/x")
    assert caught.value.status == 0


def test_api_non_json_success_is_an_api_error():
    api, _, _ = make_api((200, {}, b"<html>oops</html>"))
    with pytest.raises(gh.ApiError) as caught:
        api.get("/x")
    assert caught.value.status == 200


# ---- 小函式：一個只記錄的替身 ----

class Recorder:
    repo = "me/repo"

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []
        self.writes = 0

    def get(self, path, params=None):
        self.calls.append(("GET", path, params))
        return self.answers[path]

    def post(self, path, body):
        self.calls.append(("POST", path, body))
        self.writes += 1

    def patch(self, path, body):
        self.calls.append(("PATCH", path, body))
        self.writes += 1


def test_ensure_labels_creates_only_missing():
    api = Recorder({"/repos/me/repo/labels": [{"name": "上傳"}, {"name": "別的"}]})
    gh.ensure_labels(api)
    posts = [c for c in api.calls if c[0] == "POST"]
    assert [c[2]["name"] for c in posts] == ["已發佈", "沒收", "卡住"]
    assert posts[0][1] == "/repos/me/repo/labels"
    assert posts[0][2] == {"name": "已發佈", "color": "0e8a16", "description": "收進工作坊了"}
    assert api.calls[0] == ("GET", "/repos/me/repo/labels", {"per_page": 100})


def test_open_uploads_skips_prs_and_finished_oldest_first():
    labelled = lambda *names: [{"name": n} for n in names]  # noqa: E731
    api = Recorder({"/repos/me/repo/issues": [
        {"number": 7, "labels": labelled("上傳")},
        {"number": 5, "labels": labelled("上傳"), "pull_request": {}},
        {"number": 4, "labels": labelled("上傳", "卡住")},
        {"number": 3, "labels": labelled("上傳")},
        {"number": 2, "labels": labelled("上傳", "已發佈")},
    ]})
    assert [i["number"] for i in gh.open_uploads(api)] == [3, 7]
    assert api.calls[0][2] == {"state": "open", "labels": "上傳", "sort": "created", "direction": "asc",
                               "per_page": 100}


def test_has_marker_and_comment():
    api = Recorder({"/repos/me/repo/issues/3/comments": [{"body": "x"}, {"body": None}, {"body": f"y {gh_mark()}"}]})
    assert gh.has_marker(api, 3, gh_mark())
    assert not gh.has_marker(api, 3, "<!-- nope -->")
    assert api.calls[0] == ("GET", "/repos/me/repo/issues/3/comments", {"per_page": 100})
    gh.comment(api, 3, "hi")
    assert api.calls[-1] == ("POST", "/repos/me/repo/issues/3/comments", {"body": "hi"})


def gh_mark():
    import say

    return say.MARK_RECEIVED


def test_set_state_is_one_patch():
    api = Recorder()
    gh.set_state(api, 3, ["上傳", "已發佈"], "closed", "completed")
    assert api.writes == 1
    assert api.calls == [("PATCH", "/repos/me/repo/issues/3",
                          {"labels": ["上傳", "已發佈"], "state": "closed", "state_reason": "completed"})]
    gh.set_state(api, 4, ["上傳"])
    assert api.calls[-1][2] == {"labels": ["上傳"]}


def test_login_of_404_is_not_found():
    class Gone(Recorder):
        def get(self, path, params=None):
            if path == "/user/9":
                raise gh.NotFound(404, "x")
            return {"login": "someone"}

    assert gh.login_of(Gone(), 5) == "someone"
    with pytest.raises(gh.NotFound):
        gh.login_of(Gone(), 9)


def test_fixture_file_is_where_the_tests_expect():
    assert Path(FIXTURES / "issue-body.md").is_file()
