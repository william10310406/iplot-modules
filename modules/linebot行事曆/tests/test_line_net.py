"""抓網址（docs/01_設計.md 第 4.5 節）：只 GET、逾時、大小上限、不跟轉址、所有錯誤變成一句話且不含網址。

全部用替身 opener，不連網（只有轉址那一個測試開一個 127.0.0.1 的小伺服器，不出這台電腦）。"""

import email.utils
import errno
import http.client
import http.server
import io
import json
import socket
import ssl
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request

import pytest
from support import FAKE_HOST, FAKE_TOKEN, FAKE_URL, line_payload

import line_net
import line_url

OK_BODY = json.dumps(line_payload()).encode("utf-8")


class FakeResponse:
    def __init__(self, body=OK_BODY, status=200, headers=None, on_read=None):
        self._io, self.status, self.headers, self.on_read = io.BytesIO(body), status, headers or {}, on_read
        self.served, self.closed = 0, False

    def read(self, n=-1):
        if self.on_read:
            self.on_read()
        data = self._io.read(n)
        self.served += len(data)
        return data

    def close(self):
        self.closed = True


class FakeOpener:
    """open() 回 response，或丟出 outcome（例外）。記下每個請求與 timeout。"""

    def __init__(self, outcome=None):
        self.outcome, self.requests, self.timeouts = outcome if outcome is not None else FakeResponse(), [], []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def http_error(code, headers=None):
    return urllib.error.HTTPError(FAKE_URL, code, "x", headers or http.client.HTTPMessage(), io.BytesIO(b"no"))


def headers_of(**kw):
    message = http.client.HTTPMessage()
    for key, value in kw.items():
        message[key.replace("_", "-")] = value
    return message


def fail(outcome, **kw) -> line_net.LineError:
    with pytest.raises(line_net.LineError) as caught:
        line_net.fetch(FAKE_URL, opener=FakeOpener(outcome), **kw)
    return caught.value


def test_get_only_and_headers():
    opener = FakeOpener()
    line_net.fetch(FAKE_URL, opener=opener)
    request = opener.requests[0]
    assert request.get_method() == "GET" and request.data is None
    assert request.get_header("Accept") == "application/json"
    agent = request.get_header("User-agent")
    assert agent == line_net.USER_AGENT and agent.isascii() and "@" not in agent and "/" in agent  # 一般的名字，沒有個人資料
    assert FAKE_TOKEN not in agent and FAKE_HOST not in agent


def test_query_string_has_from_and_to_only_when_given():
    plain, ranged = FakeOpener(), FakeOpener()
    line_net.fetch(FAKE_URL, opener=plain)
    line_net.fetch(FAKE_URL, "2026-11-01", "2026-11-30", opener=ranged)
    assert plain.requests[0].full_url == FAKE_URL
    base, _, query = ranged.requests[0].full_url.partition("?")
    assert base == FAKE_URL
    assert urllib.parse.parse_qs(query) == {"from": ["2026-11-01"], "to": ["2026-11-30"]}


def test_from_without_to_is_a_programming_error_and_bad_dates_are_bad_range():
    with pytest.raises(ValueError, match="from"):
        line_net.fetch(FAKE_URL, "2026-11-01", None, opener=FakeOpener())
    with pytest.raises(ValueError, match="to"):
        line_net.fetch(FAKE_URL, None, "2026-11-01", opener=FakeOpener())
    for bad in ("2026-1-1", "20261101", "x", "2026-02-30", ""):
        opener = FakeOpener()
        with pytest.raises(line_net.LineError) as caught:
            line_net.fetch(FAKE_URL, bad, "2026-12-01", opener=opener)
        assert caught.value.kind == "bad_range" and opener.requests == []  # 不送出去


def test_invalid_url_is_refused_before_any_request_and_without_echo():
    opener = FakeOpener()
    with pytest.raises(line_net.LineError) as caught:
        line_net.fetch("http://x.example.test/j/" + "a" * 40 + ".json", opener=opener)
    assert caught.value.kind == "bad_url" and caught.value.message == line_url.BAD_URL_MESSAGE
    assert opener.requests == []


def test_200_returns_parsed_json_and_closes_the_response_and_passes_the_timeout():
    response, opener = FakeResponse(), FakeOpener()
    opener.outcome = response
    assert line_net.fetch(FAKE_URL, opener=opener) == line_payload()
    assert response.closed and opener.timeouts == [15]
    other = FakeOpener()
    line_net.fetch(FAKE_URL, opener=other, timeout=3)
    assert other.timeouts == [3]


@pytest.mark.parametrize(("code", "kind"), [
    (404, "not_found"), (400, "bad_range"), (405, "method"), (429, "rate_limit"),
    (500, "server"), (502, "server"), (503, "server"), (504, "server"), (599, "server"),
    (401, "http"), (403, "http"), (410, "http"), (418, "http"),
    (301, "redirect"), (302, "redirect"), (303, "redirect"), (307, "redirect"), (308, "redirect"),
])
def test_status_maps_to_kind(code, kind):
    error = fail(http_error(code))
    assert error.kind == kind
    assert "\n" not in error.message and error.message


def test_each_status_message_says_what_to_do():
    assert "連上iPLoT" in fail(http_error(404)).message and "重設" in fail(http_error(404)).message
    assert "400" in fail(http_error(400)).message
    assert "回報" in fail(http_error(405)).message
    assert "503" in fail(http_error(503)).message
    assert "403" in fail(http_error(403)).message


def test_429_reads_retry_after_seconds():
    error = fail(http_error(429, headers_of(Retry_After="42")))
    assert error.kind == "rate_limit" and error.retry_after == 42 and "42" in error.message


def test_429_reads_retry_after_http_date():
    now = 1_800_000_000.0
    stamp = email.utils.formatdate(now + 90, usegmt=True)
    error = fail(http_error(429, headers_of(Retry_After=stamp)), now=lambda: now)
    assert error.retry_after == 90


def test_429_without_header_defaults_to_60():
    assert fail(http_error(429)).retry_after == 60
    assert fail(http_error(429, headers_of(Retry_After="soon"))).retry_after == 60
    assert fail(http_error(429, headers_of(Retry_After=""))).retry_after == 60


@pytest.mark.parametrize(("value", "expected"), [("1", 1), ("0", 1), ("-5", 1), ("3600", 3600), ("99999", 3600), (" 7 ", 7), ("2.9", 60)])
def test_retry_after_is_clamped(value, expected):
    assert line_net.parse_retry_after(value, now=1_800_000_000.0) == expected


def test_retry_after_date_in_the_past_means_one_second():
    stamp = email.utils.formatdate(1_700_000_000, usegmt=True)
    assert line_net.parse_retry_after(stamp, now=1_800_000_000.0) == 1


def test_only_429_has_a_retry_after():
    assert fail(http_error(404)).retry_after is None and fail(http_error(500)).retry_after is None


NETWORK = [
    (TimeoutError("timed out"), "timeout"), (urllib.error.URLError(TimeoutError()), "timeout"),
    (socket.gaierror(8, "no such host"), "offline"), (urllib.error.URLError(socket.gaierror(8, "x")), "offline"),
    (ConnectionRefusedError(), "offline"), (urllib.error.URLError(ConnectionRefusedError()), "offline"),
    (OSError(errno.ENETUNREACH, "unreachable"), "offline"), (OSError(errno.EHOSTUNREACH, "no route"), "offline"),
    (ConnectionResetError(), "dropped"), (BrokenPipeError(), "dropped"), (ConnectionAbortedError(), "dropped"),
    (http.client.RemoteDisconnected("bye"), "dropped"), (http.client.IncompleteRead(b"x"), "dropped"),
    (http.client.BadStatusLine("x"), "dropped"), (urllib.error.URLError(ConnectionResetError()), "dropped"),
    (ssl.SSLCertVerificationError("bad cert"), "certificate"), (urllib.error.URLError(ssl.SSLCertVerificationError("x")), "certificate"),
    (ssl.SSLError("handshake"), "tls"), (urllib.error.URLError(ssl.SSLError("x")), "tls"),
    (OSError("weird"), "network"), (urllib.error.URLError("some reason"), "network"),
]


@pytest.mark.parametrize(("outcome", "kind"), NETWORK, ids=lambda v: type(v).__name__ if isinstance(v, BaseException) else v)
def test_network_trouble_is_one_sentence_each(outcome, kind):
    error = fail(outcome)
    assert error.kind == kind
    assert error.message.startswith("連上") is False and error.message.startswith("連不上 LINE")
    assert "\n" not in error.message and "Traceback" not in error.message


def test_a_stalled_body_read_and_a_slow_drip_both_become_timeouts():
    class Stalled(FakeResponse):
        def read(self, n=-1):
            raise TimeoutError

    assert fail(Stalled()).kind == "timeout"
    ticks = iter(range(0, 1000, 20))
    clock = lambda: next(ticks)  # noqa: E731  每看一次時間過 20 秒
    drip = FakeResponse(b"{" + b" " * 300000)
    assert fail(drip, clock=clock).kind == "timeout"


def test_redirect_response_is_an_error_not_followed():
    error = fail(http_error(302, headers_of(Location="https://evil.example.test/steal")))
    assert error.kind == "redirect" and "evil" not in error.message


def test_the_real_no_redirect_handler_refuses_to_follow_a_redirect_to_another_server():
    """真的用 line_net 的轉址處理器（不是替身）打一個 127.0.0.1 的小伺服器：它回 302，第二台伺服器不能被打到。"""
    hits = []

    class Target(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    target = http.server.HTTPServer(("127.0.0.1", 0), Target)

    class Redirector(Target):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_address[1]}/stolen")
            self.end_headers()

    first = http.server.HTTPServer(("127.0.0.1", 0), Redirector)
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (first, target)]
    for thread in threads:
        thread.start()
    try:
        opener = urllib.request.build_opener(line_net.NoRedirect)
        with pytest.raises(urllib.error.HTTPError) as caught:
            opener.open(f"http://127.0.0.1:{first.server_address[1]}/j/x", timeout=5)
        assert caught.value.code == 302 and hits == []
        caught.value.close()
    finally:
        for server in (first, target):
            server.shutdown()
            server.server_close()


def test_too_big_body_is_refused_without_reading_it_all():
    response = FakeResponse(b"x" * 5_000_000)
    error = fail(response, max_bytes=1000)
    assert error.kind == "too_big" and "已拒絕" in error.message and "1000 bytes" in error.message
    assert response.served <= 1000 + 65536  # 最多多讀一個區塊，不會把 5 MB 全讀完


def test_declared_content_length_over_the_limit_is_refused_without_reading():
    response = FakeResponse(headers={"Content-Length": "999999999"})
    error = fail(response)
    assert error.kind == "too_big" and response.served == 0 and "2 MiB" in error.message


def test_body_exactly_at_the_limit_is_accepted():
    body = json.dumps({"a": "x" * 50}).encode()
    assert line_net.fetch(FAKE_URL, opener=FakeOpener(FakeResponse(body)), max_bytes=len(body)) == {"a": "x" * 50}


@pytest.mark.parametrize("body", [b"\xff\xfe\x00", b"<html>not json</html>", b"", b"[1, 2]", b"null", b'"text"', b"123", b"[" * 200000,
                                  b'{"a": ', b"{'single': 'quotes'}"])
def test_invalid_utf8_non_json_and_wrong_top_level_are_format_errors(body):
    error = fail(FakeResponse(body))
    assert error.kind == "format" and "格式" in error.message and "沒有更新快取" in error.message


def _every_failure():
    yield http_error(404)
    yield http_error(429, headers_of(Retry_After="5"))
    yield http_error(500)
    yield http_error(302)
    for outcome, _ in NETWORK:
        yield outcome
    yield FakeResponse(b"<html>")
    yield FakeResponse(b"x" * 100, headers={"Content-Length": "9999999999"})
    # 訊息裡含網址的例外：我們的訊息不能用 str(exc)
    yield urllib.error.URLError(f"failed to open {FAKE_URL}")
    yield urllib.error.HTTPError(FAKE_URL, 404, f"Not Found {FAKE_URL}", http.client.HTTPMessage(), io.BytesIO(FAKE_URL.encode()))
    yield OSError(FAKE_URL)
    yield ValueError(FAKE_URL)
    yield http.client.InvalidURL(FAKE_URL)
    yield http.client.IncompleteRead(FAKE_URL.encode())
    yield ConnectionResetError(f"reset by {FAKE_HOST}")
    yield urllib.error.URLError(socket.gaierror(8, f"nodename {FAKE_HOST} not known"))
    yield ssl.SSLCertVerificationError(f"certificate verify failed for {FAKE_HOST}")


@pytest.mark.parametrize("outcome", list(_every_failure()), ids=lambda v: type(v).__name__)
def test_no_error_contains_the_url_or_token_anywhere(outcome):
    error = fail(outcome)
    shown = [str(error), repr(error), error.message, *map(str, error.args), "".join(traceback.format_exception(error))]
    for text in shown:
        assert FAKE_TOKEN not in text and FAKE_URL not in text and FAKE_HOST not in text, text
    assert error.__cause__ is None and error.__context__ is None  # 原本的例外（帶著網址）沒有掛在後面
    assert not hasattr(error, "url") and not hasattr(error, "fp")


def test_urlerror_reason_that_contains_the_url_is_never_copied():
    error = fail(urllib.error.URLError(OSError(f"cannot reach {FAKE_URL}")))
    assert FAKE_TOKEN not in error.message and FAKE_TOKEN not in str(error)


def test_unexpected_programming_errors_are_not_swallowed():
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        line_net.fetch(FAKE_URL, opener=FakeOpener(Boom("bug")))


def test_http_error_response_is_closed():
    error = http_error(500)
    fail(error)
    assert error.fp is None or error.fp.closed


# ── 憑證 ──

class FakeContext:
    def __init__(self, loaded):
        self.loaded, self.files = loaded, []

    def cert_store_stats(self):
        return {"x509_ca": self.loaded, "x509": self.loaded, "crl": 0}

    def load_verify_locations(self, cafile=None, **kw):
        self.files.append(cafile)


def test_trust_store_fallback_used_only_when_default_store_is_empty():
    empty, full = FakeContext(0), FakeContext(140)
    line_net.make_context(create=lambda: empty, cert_file="/etc/ssl/cert.pem", exists=lambda p: True)
    line_net.make_context(create=lambda: full, cert_file="/etc/ssl/cert.pem", exists=lambda p: True)
    assert empty.files == ["/etc/ssl/cert.pem"] and full.files == []
    nothing = FakeContext(0)
    line_net.make_context(create=lambda: nothing, cert_file="/etc/ssl/cert.pem", exists=lambda p: False)
    assert nothing.files == []


def test_default_context_still_verifies_certificates():
    context = line_net.make_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True


def test_default_opener_has_no_redirect_handler_and_uses_our_context():
    opener = line_net.default_opener()
    kinds = [type(h) for h in opener.handlers]
    assert line_net.NoRedirect in kinds
    assert not any(k is urllib.request.HTTPRedirectHandler for k in kinds)
    assert any(isinstance(h, urllib.request.HTTPSHandler) for h in opener.handlers)
