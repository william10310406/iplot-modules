"""網址檢查與遮罩（docs/01_設計.md 第 4.4 節，L04）。網址等於密碼：錯誤訊息不回顯輸入，遮罩不露出整個 token。"""

import pytest
from support import FAKE_HOST, FAKE_TOKEN, FAKE_URL

import line_url


def test_accepts_https_j_token_json():
    assert line_url.validate(FAKE_URL) == FAKE_URL


def test_accepts_surrounding_whitespace_and_returns_it_trimmed():
    assert line_url.validate(f"  {FAKE_URL}\n") == FAKE_URL


def test_accepts_a_port_and_uppercase_host_and_url_safe_token_characters():
    token = "A_b-C" * 6
    url = f"https://Line.Example.TEST:8443/j/{token}.json"
    assert line_url.validate(url) == url


@pytest.mark.parametrize("url", [
    f"http://{FAKE_HOST}/j/{FAKE_TOKEN}.json",
    f"HTTP://{FAKE_HOST}/j/{FAKE_TOKEN}.json",
    f"//{FAKE_HOST}/j/{FAKE_TOKEN}.json",
    f"{FAKE_HOST}/j/{FAKE_TOKEN}.json",
])
def test_rejects_http_and_missing_scheme(url):
    with pytest.raises(line_url.BadUrl):
        line_url.validate(url)


@pytest.mark.parametrize("scheme", ["file", "ftp", "javascript", "data", "ws", "wss", "gopher", "mailto"])
def test_rejects_other_schemes(scheme):
    for url in (f"{scheme}://{FAKE_HOST}/j/{FAKE_TOKEN}.json", f"{scheme}:{FAKE_HOST}/j/{FAKE_TOKEN}.json"):
        with pytest.raises(line_url.BadUrl):
            line_url.validate(url)


@pytest.mark.parametrize("path", [
    f"/x/{FAKE_TOKEN}.json", f"/j/{FAKE_TOKEN}", f"/j/{FAKE_TOKEN}.JSON", f"/j/{FAKE_TOKEN}.json/", f"/j/a/{FAKE_TOKEN}.json",
    "/j/.json", "/j/", "/j", "/", "", f"/J/{FAKE_TOKEN}.json", f"//j/{FAKE_TOKEN}.json", f"/j/{FAKE_TOKEN}.json.json",
    f"/j/../{FAKE_TOKEN}.json", f"/j/%2e%2e/{FAKE_TOKEN}.json", f"/j/{FAKE_TOKEN}%2ejson",
])
def test_rejects_wrong_path(path):
    with pytest.raises(line_url.BadUrl):
        line_url.validate(f"https://{FAKE_HOST}{path}")


@pytest.mark.parametrize("url", [
    f"https://user:pass@{FAKE_HOST}/j/{FAKE_TOKEN}.json",
    f"https://user@{FAKE_HOST}/j/{FAKE_TOKEN}.json",
    f"https://{FAKE_HOST}/j/{FAKE_TOKEN}.json?from=2026-01-01",
    f"https://{FAKE_HOST}/j/{FAKE_TOKEN}.json?",
    f"https://{FAKE_HOST}/j/{FAKE_TOKEN}.json#frag",
    f"https://{FAKE_HOST}/j/{FAKE_TOKEN}.json#",
    f"https://{FAKE_HOST}/j/{FAKE_TOKEN} .json",
    f"https://{FAKE_HOST} /j/{FAKE_TOKEN}.json",
    f"https://{FAKE_HOST}/j/{FAKE_TOKEN}.json extra",
    f"https://{FAKE_HOST}/j/{FAKE_TOKEN}.json\nhttps://evil.test/",
    f"https://{FAKE_HOST}/j/{FAKE_TOKEN}.json\x00",
    f"https://{FAKE_HOST}/j/{FAKE_TOKEN}\t.json",
    f"https://{FAKE_HOST}/j/{FAKE_TOKEN}.json\x7f",
])
def test_rejects_userinfo_query_fragment_whitespace_and_control_chars(url):
    with pytest.raises(line_url.BadUrl):
        line_url.validate(url)


@pytest.mark.parametrize("token", [
    "A" * 19, "A" * 129, "", "A" * 20 + "+", "A" * 20 + "/", "A" * 20 + "=", "A" * 20 + ".", "A" * 20 + "中文", "A" * 20 + "é",
    "A" * 20 + "%41", "A" * 20 + "\u2028", "Ａ" * 30,
])
def test_rejects_bad_token_charset_and_length(token):
    with pytest.raises(line_url.BadUrl):
        line_url.validate(f"https://{FAKE_HOST}/j/{token}.json")


@pytest.mark.parametrize("length", [20, 40, 64, 128])
def test_accepts_token_lengths_from_20_to_128(length):
    url = f"https://{FAKE_HOST}/j/{'a' * length}.json"
    assert line_url.validate(url) == url


@pytest.mark.parametrize("host", [
    "[::1]", "[2001:db8::1]", "127.0.0.1", "10.0.0.1", "192.168.1.1:8080", "-.x", "a-.example.test", "-a.example.test",
    "a..example.test", ".example.test", "example.test.", "", ":443", "exa mple.test", "例子.測試", "exa_mple.test",
    "a" * 64 + ".test", "example.test:", "example.test:99999", "example.test:0", "example.test:abc",
    "local\u200bhost.test",
])
def test_rejects_ip_literals_and_garbage_hosts(host):
    with pytest.raises(line_url.BadUrl):
        line_url.validate(f"https://{host}/j/{FAKE_TOKEN}.json")


@pytest.mark.parametrize("junk", [None, 5, b"https://x", ["https://x"], {"url": FAKE_URL}, 1.5, object()])
def test_rejects_non_strings(junk):
    with pytest.raises(line_url.BadUrl):
        line_url.validate(junk)


@pytest.mark.parametrize("secret", [
    "https://hunter2.example.test/j/SECRETSECRETSECRETSECRET.txt", "把這串字當密碼 PASSWORD-123", FAKE_TOKEN + "!",
])
def test_error_message_never_echoes_the_input(secret):
    with pytest.raises(line_url.BadUrl) as caught:
        line_url.validate(secret)
    shown = [str(caught.value), repr(caught.value), *map(str, caught.value.args)]
    for text in shown:
        assert "hunter2" not in text and "SECRET" not in text and "PASSWORD" not in text and FAKE_TOKEN not in text
    assert str(caught.value) == line_url.BAD_URL_MESSAGE


def test_the_message_says_how_to_get_a_url():
    assert "https://" in line_url.BAD_URL_MESSAGE and "/j/" in line_url.BAD_URL_MESSAGE
    assert "連上iPLoT" in line_url.BAD_URL_MESSAGE and "私訊" in line_url.BAD_URL_MESSAGE


def test_mask_hides_the_middle_of_the_token():
    masked = line_url.mask(FAKE_URL)
    assert masked == f"https://{FAKE_HOST}/j/{FAKE_TOKEN[:4]}…{FAKE_TOKEN[-4:]}.json"


def test_mask_keeps_the_port():
    assert line_url.mask(f"https://{FAKE_HOST}:8443/j/{FAKE_TOKEN}.json").startswith(f"https://{FAKE_HOST}:8443/j/")


def test_mask_never_contains_the_full_token_or_the_middle_of_it():
    masked = line_url.mask(FAKE_URL)
    assert FAKE_TOKEN not in masked
    assert FAKE_TOKEN[4:-4] not in masked
    assert FAKE_TOKEN[8:20] not in masked


@pytest.mark.parametrize("junk", ["", "短", "https://x/j/short.json", "http://h/j/" + "a" * 40 + ".json", None, 5])
def test_mask_of_something_that_is_not_a_valid_url_is_safe_and_does_not_echo_it(junk):
    masked = line_url.mask(junk)
    assert masked == line_url.UNKNOWN_MASK
    assert "a" * 10 not in masked


def test_token_of_and_account_id():
    assert line_url.token_of(FAKE_URL) == FAKE_TOKEN
    account = line_url.account_id(FAKE_URL)
    assert len(account) == 12 and all(c in "0123456789abcdef" for c in account)
    assert account !=line_url.account_id(FAKE_URL.replace("FAKE", "FAKF"))


def test_account_id_is_stable_and_not_the_token():
    other_host = f"https://other.example.test/j/{FAKE_TOKEN}.json"
    assert line_url.account_id(FAKE_URL) == line_url.account_id(other_host)  # 同一個 token＝同一個帳號
    assert FAKE_TOKEN not in line_url.account_id(FAKE_URL)
    assert line_url.account_id(FAKE_URL)[:6] not in FAKE_TOKEN.lower()
