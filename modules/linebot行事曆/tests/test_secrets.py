"""網址等於密碼（docs/01_設計.md 第 8 節）：只存在 設定.json（0600）；任何訊息、回傳值、log、.py、.history 都沒有完整網址，token 遮起來。

整個流程（貼網址、抓、翻頁、複製、自動複製、換、清除）走一遍，掃每一個會讓人或頁面看到的輸出。"""

import inspect
import json
import re
import stat
from datetime import date, datetime

import pytest
from support import FAKE_HOST, FAKE_TOKEN, FAKE_URL, Clock, FakeLine, event, jot, line_payload, taipei_ts

import iplot
import line_net
import line_url

DATE = "2026-11-06"
MIDDLE = FAKE_TOKEN[6:-6]


def clean(text) -> bool:
    shown = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return FAKE_TOKEN not in shown and FAKE_URL not in shown and MIDDLE not in shown


def run_everything(make_api, *, fail=False):
    """走一遍所有流程，回傳每一個步驟的回傳值（頁面看得到的）。"""
    fetch = FakeLine()
    payload = line_payload(range={"from": "2026-10-04", "to": "2027-01-17"}, events=[event(id="e", title="開會")],
                           jots=[jot(id="j", date=DATE)])
    fetch.script = [line_net.LineError("not_found", line_net.RESET)] if fail else [payload] * 6
    h = make_api(url=None, fetch=fetch, today=date(2026, 11, 9), now=datetime(2026, 11, 9, 0, 10),
                 clock=Clock(taipei_ts(2026, 11, 9, 0, 10)))
    api, seen = h.api, []
    seen.append(api.line_state())
    seen.append(api.line_set_url("http://" + FAKE_HOST + "/j/" + FAKE_TOKEN + ".json"))       # 壞網址（http）
    seen.append(api.line_set_url(FAKE_URL + "?x=1"))                                           # 壞網址（有查詢字串）
    seen.append(api.line_set_url(FAKE_URL))
    seen += [api.month("2026-11"), api.month("2027-03"), api.year("2026"), api.day(DATE)]
    seen += [api.line_state(), api.line_refresh()]
    seen.append(api.line_set_auto(True))
    preview = api.line_copy_preview(DATE)
    seen += [preview, api.line_copy(DATE, preview["digest"]), api.line_copy(DATE, "stale")]
    seen += [api.line_state(), api.settings()]
    seen.append(api.line_clear())
    seen.append(api.line_state())
    return h, seen


@pytest.mark.parametrize("fail", [False, True])
def test_full_url_never_appears_in_any_api_return_value(make_api, fail):
    h, seen = run_everything(make_api, fail=fail)
    for result in seen:
        assert clean(result), result


@pytest.mark.parametrize("fail", [False, True])
def test_full_url_never_appears_in_app_log_calls_status_text_or_exceptions(make_api, fail):
    h, seen = run_everything(make_api, fail=fail)
    assert clean(h.app.logs) and clean([str(p) for p in h.app.opened]) and clean(h.app.trashed)
    for result in seen:
        for key in ("message", "error", "auto_message"):
            if isinstance(result, dict) and isinstance(result.get(key), str):
                assert clean(result[key])
    state = h.api.line_state()
    assert clean(state["message"]) and clean(state["last"]["message"]) and clean(state["auto_message"])


def test_setting_a_bad_url_does_not_echo_it_and_stores_nothing(make_api):
    h = make_api()
    for bad in (f"http://{FAKE_HOST}/j/{FAKE_TOKEN}.json", f"{FAKE_URL}#x", FAKE_TOKEN, f"https://u:p@{FAKE_HOST}/j/{FAKE_TOKEN}.json"):
        result = h.api.line_set_url(bad)
        assert result == {"error": line_url.BAD_URL_MESSAGE} and clean(result)
    assert not h.settings.exists() or "url" not in json.loads(h.settings.read_text(encoding="utf-8")).get("LINE", {})


def test_the_url_is_only_in_the_settings_file(make_api):
    h, _ = run_everything(make_api)
    h.api.line_set_url(FAKE_URL)                       # run_everything 最後清除了；再貼一次
    holders = [p for p in h.module.rglob("*") if p.is_file() and FAKE_TOKEN in p.read_text(encoding="utf-8", errors="replace")]
    assert holders == [h.settings]
    assert all(FAKE_TOKEN not in p.read_text(encoding="utf-8", errors="replace") for p in h.root.rglob("*") if p.is_file())


def test_no_py_file_history_or_page_in_the_module_contains_a_url_or_token():
    shipped = [*iplot.HERE.glob("*.py"), iplot.HERE / "page.html", *(iplot.HERE / ".history").glob("*")]
    assert shipped
    pattern = re.compile(r"/j/[A-Za-z0-9_-]{20,}")
    for path in shipped:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not pattern.search(text) and "FAKE-TOKEN" not in text, path.name


def test_settings_cache_and_ledger_files_are_not_world_readable(make_api):
    h, _ = run_everything(make_api)
    h.api.line_set_url(FAKE_URL)
    h.api.line_refresh()
    for path in (h.settings, h.cache, h.ledger):
        assert path.exists() and stat.S_IMODE(path.stat().st_mode) == 0o600, path.name


def test_the_cache_and_ledger_do_not_contain_the_token(make_api):
    h, _ = run_everything(make_api)
    h.api.line_set_url(FAKE_URL)
    h.api.line_refresh()
    for path in (h.cache, h.ledger):
        assert clean(path.read_text(encoding="utf-8"))
    assert json.loads(h.cache.read_text(encoding="utf-8"))["account"] == line_url.account_id(FAKE_URL)


def test_masked_url_in_state_hides_the_middle_of_the_token(make_api):
    h = make_api(url=FAKE_URL)
    masked = h.api.line_state()["masked_url"]
    assert masked == line_url.mask(FAKE_URL) and FAKE_TOKEN[:4] in masked and FAKE_TOKEN[-4:] in masked and MIDDLE not in masked


# ── 介面 ──

ORIGINAL_METHODS = {"month", "year", "day", "save", "set_public", "add_image", "remove_image", "open_page", "publish", "modules",
                    "launch", "settings", "change_folder", "reveal_folder", "rebuild"}
LINE_METHODS = {"line_state", "line_refresh", "line_set_url", "line_clear", "line_set_auto", "line_copy_preview", "line_copy"}


def test_api_exposes_exactly_the_documented_public_methods(make_api):
    h = make_api()
    public = {name for name in dir(h.api) if not name.startswith("_")}
    assert public == ORIGINAL_METHODS | LINE_METHODS and len(public) == 22
    assert all(callable(getattr(h.api, name)) for name in public)
    assert all(name.startswith("_") for name in vars(h.api))        # pywebview 會把不以底線開頭的屬性攤給頁面


def test_no_api_method_takes_a_path_or_a_folder(make_api):
    h = make_api()
    for name in ORIGINAL_METHODS | LINE_METHODS:
        for parameter in inspect.signature(getattr(h.api, name)).parameters:
            assert parameter not in ("path", "folder", "file", "filename", "dir", "root"), (name, parameter)


def test_the_only_method_that_takes_a_url_never_returns_it(make_api):
    h = make_api()
    assert [n for n in LINE_METHODS if "url" in inspect.signature(getattr(h.api, n)).parameters] == ["line_set_url"]
    assert clean(h.api.line_set_url(FAKE_URL))


def test_line_methods_that_write_files_are_serialised_on_the_api_lock(make_api):
    h = make_api()
    for name in ("line_set_url", "line_clear", "line_set_auto", "line_copy_preview", "line_copy"):
        assert getattr(type(h.api), name).__wrapped__ is not None, name
    for name in ("line_state", "line_refresh"):
        assert not hasattr(getattr(type(h.api), name), "__wrapped__"), name      # 這兩個不拿鎖（頁面一直在問）
