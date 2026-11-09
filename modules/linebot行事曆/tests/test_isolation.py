"""LINE 的資料跟我的日記分開（docs/01_設計.md 第 4.1、8 節）：
- pages.py 產生的網頁（私人的、「發佈」的）都不出現 LINE 的內容；只有按了「複製進日記」之後，那些字才成為我日記的一部分；
- page.html 沒有不安全的寫法（XSS）、不連網、不留網址。

用哨兵字串 LINE-SENTINEL 放進 LINE 資料的每一個欄位，再掃每一個會輸出的地方。"""

import ast
import json
import re
import shutil
import subprocess

import pytest
from support import FAKE_URL, SENTINEL, FakeLine, all_day_event, event, jot, line_payload, log, mood, task

import diary
import iplot
import pages

DATE = "2026-11-06"


def sentinel_payload():
    S = SENTINEL
    return line_payload(
        range={"from": "2026-10-04", "to": "2027-01-17"},
        events=[event(id="e1", title=f"{S}-event", note=f"{S}-note", location=f"{S}-loc", group=f"{S}-group",
                      start=f"{DATE}T10:00:00+08:00", end=f"{DATE}T11:00:00+08:00"),
                all_day_event(id="e2", title=f"{S}-trip", startDate="2026-11-08", endDate="2026-11-09", group=None)],
        tasks=[task(id="t1", title=f"{S}-task", note=f"{S}-tnote", dueDate=DATE)],
        logs=[log(date=DATE, items=[{"title": f"{S}-log", "details": f"{S}-details"}])],
        moods=[mood(date=DATE, text=f"{S}-mood")], jots=[jot(id="j1", date=DATE, text=f"{S}-jot")])


def with_line(make_api):
    fetch = FakeLine()
    fetch.script = [sentinel_payload()] * 6
    h = make_api(url=FAKE_URL, fetch=fetch)
    h.api.month("2026-11")
    assert SENTINEL in json.dumps(h.api.day(DATE)) and SENTINEL in json.dumps(h.api.month("2026-11"))   # 確認哨兵真的進了 LINE 的畫面
    return h


def files_with(root, needle):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and needle.encode() in p.read_bytes())


# ── 程式的界線 ──

@pytest.mark.parametrize("name", ["diary.py", "pages.py", "photos.py"])
def test_diary_pages_photos_do_not_import_any_line_module(name):
    tree = ast.parse((iplot.HERE / name).read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not [m for m in imported if m.startswith("line_")], imported
    assert '"LINE"' not in (iplot.HERE / name).read_text(encoding="utf-8")        # 連設定檔裡 LINE 那一區都不碰


def test_only_line_copy_and_iplot_write_line_content_into_the_diary():
    """哪些檔會呼叫 diary 寫日記內容的函式（save_day、set_public）：只有 iplot.py（自己的存檔）與 line_copy.py（複製進日記）。"""
    writers = []
    for path in sorted(iplot.HERE.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if re.search(r"diary\.(save_day|set_public)\(", text) and path.name != "diary.py":
            writers.append(path.name)
    assert writers == ["iplot.py", "line_copy.py"]


# ── 網頁沒有 LINE ──

def test_every_build_function_output_has_no_line_content(make_api):
    h = with_line(make_api)
    diary.save_day(h.root, DATE, {"行程": "我的行程", "心情": diary.mood_text("😄", "好")}, 20)
    diary.save_day(h.root, "2026-11-08", {"看到": "我看到的"}, 20)
    for date in (DATE, "2026-11-08"):
        diary.set_public(h.root, date, True)
    for public in (False, True):
        for text in (pages.render_day(h.root, DATE, public=public), pages.render_month(h.root, "2026-11", public=public),
                     pages.render_year(h.root, "2026", public=public), pages.render_index(h.root, public=public)):
            assert SENTINEL not in text and "LINE" not in text


def test_rebuild_all_output_has_no_line_content(make_api):
    h = with_line(make_api)
    diary.save_day(h.root, DATE, {"行程": "我的行程", "做了": "我做的", "看到": "我看的", "心情": diary.mood_text("🙂", "")}, 20)
    pages.rebuild_all(h.root)
    h.api.rebuild()
    assert (h.root / "index.html").exists() and files_with(h.root, SENTINEL) == []


def test_publish_folder_has_no_line_content(make_api):
    h = with_line(make_api)
    h.api.save(DATE, {"行程": "公開的行程"})
    h.api.set_public(DATE, True)
    h.api.publish()
    assert (h.root / "發佈" / "index.html").exists() and files_with(h.root, SENTINEL) == []


def test_api_save_set_public_open_page_and_publish_never_write_line_content(make_api):
    h = with_line(make_api)
    h.api.save(DATE, {"行程": "我的", "mood": "😄", "note": "x"})
    h.api.set_public(DATE, True)
    for kind, key in (("day", DATE), ("month", "2026-11"), ("year", "2026"), ("index", "")):
        h.api.open_page(kind, key)
    h.api.publish()
    h.api.rebuild()
    assert files_with(h.root, SENTINEL) == []


def test_diary_folder_has_no_line_content_until_a_copy_happens(make_api):
    h = with_line(make_api)
    h.api.line_refresh()
    h.api.year("2026")
    preview = h.api.line_copy_preview(DATE)
    assert SENTINEL in json.dumps(preview) and files_with(h.root, SENTINEL) == []            # 預覽只是看，什麼都沒寫
    h.api.line_set_auto(True)
    assert files_with(h.root, SENTINEL) == []
    h.api.line_copy(DATE, preview["digest"])
    assert files_with(h.root, SENTINEL)                                                     # 你按了確定：現在才有


def test_after_a_manual_copy_the_text_is_in_the_diary_and_so_in_the_private_pages_only_as_my_text(make_api):
    h = with_line(make_api)
    h.api.line_copy(DATE, h.api.line_copy_preview(DATE)["digest"])
    assert SENTINEL in diary.read_day(h.root, DATE)["行程"]
    assert SENTINEL in pages.render_day(h.root, DATE)                                       # 複製之後它就是我日記的一部分
    assert "還沒有打開" in h.api.publish()["error"] and not (h.root / "發佈").exists()       # 這天沒勾公開：「發佈」什麼都不產生


def test_after_a_copy_on_a_public_day_the_published_pages_contain_it_but_private_items_were_skipped(make_api):
    fetch = FakeLine()
    secret = "LINE-PRIVATE-ONLY-77"
    fetch.script = [line_payload(range={"from": "2026-10-04", "to": "2027-01-17"},
                                 events=[event(id="a", title=f"{SENTINEL}-public-event", private=False),
                                         event(id="b", title=secret, private=True)],
                                 tasks=[task(id="c", title=f"{secret}-task", private=True)], logs=[], moods=[], jots=[])] * 4
    h = make_api(url=FAKE_URL, fetch=fetch)
    h.api.month("2026-11")
    h.api.set_public(DATE, True)
    preview = h.api.line_copy_preview(DATE)
    assert preview["public"] is True and preview["skipped"]["private"] == 2 and secret not in json.dumps(preview["additions"])
    h.api.line_copy(DATE, preview["digest"])
    h.api.publish()
    assert files_with(h.root / "發佈", f"{SENTINEL}-public-event") and files_with(h.root, secret) == []


def test_auto_copy_leaves_public_days_alone_so_nothing_reaches_the_published_pages(make_api):
    import datetime

    from support import Clock, taipei_ts

    fetch = FakeLine(today="2026-11-09")
    fetch.script = [line_payload(range={"from": "2026-10-05", "to": "2027-01-18"}, events=[event(
        id="a", title=f"{SENTINEL}-auto", startDate="2026-11-08", endDate="2026-11-08", start="2026-11-08T10:00:00+08:00",
        end="2026-11-08T11:00:00+08:00")], tasks=[], logs=[], moods=[], jots=[])] * 4
    h = make_api(url=FAKE_URL, fetch=fetch, today=datetime.date(2026, 11, 9), now=datetime.datetime(2026, 11, 9, 0, 10),
                 clock=Clock(taipei_ts(2026, 11, 9, 0, 10)))
    h.api.set_public("2026-11-08", True)
    h.api.line_set_auto(True)
    ledger = json.loads(h.ledger.read_text(encoding="utf-8"))
    ledger["auto_through"] = "2026-11-07"
    h.ledger.write_text(json.dumps(ledger), encoding="utf-8")
    h.api.month("2026-11")
    h.api.publish()
    assert files_with(h.root, SENTINEL) == [] and "公開的日子" in h.api.line_state()["auto_message"]


# ── 輸出是純文字，不是 HTML ──

def test_python_side_returns_line_text_as_plain_strings_not_html(make_api):
    nasty = "<img src=x onerror=alert(1)>\"q\" </script><b>" + chr(0x2028)
    fetch = FakeLine()
    everything = line_payload(range={"from": "2026-10-04", "to": "2027-01-17"},
                              events=[event(id="a", title=nasty, note=nasty, location=nasty, group=nasty)],
                              tasks=[task(id="b", title=nasty, note=nasty)], logs=[log(items=[{"title": nasty, "details": nasty}])],
                              moods=[mood(text=nasty)], jots=[jot(id="c", text=nasty)])
    fetch.script = [everything] * 3
    h = make_api(url=FAKE_URL, fetch=fetch)
    results = [h.api.month("2026-11"), h.api.day(DATE), h.api.year("2026"), h.api.line_copy_preview(DATE)]
    for result in results:
        dumped = json.dumps(result, ensure_ascii=False).replace(json.dumps(nasty, ensure_ascii=False)[1:-1], "")
        assert "<" not in dumped and ">" not in dumped, "LINE 的字旁邊多了標記"
    assert results[1]["line"]["events"][0]["title"] == nasty and results[1]["line"]["jots"][0]["text"] == nasty


# ── page.html ──

PAGE = (iplot.HERE / "page.html").read_text(encoding="utf-8")
SCRIPT = PAGE[PAGE.index("<script>") + 8:PAGE.rindex("</script>")]


def test_page_html_has_no_unsafe_dom_sinks():
    banned = [r"innerHTML", r"outerHTML", r"insertAdjacentHTML", r"document\.write", r"\beval\s*\(", r"new\s+Function", r"srcdoc",
              r"setTimeout\s*\(\s*[\"'`]", r"setInterval\s*\(\s*[\"'`]", r"javascript:", r"createContextualFragment", r"DOMParser"]
    for pattern in banned:
        assert not re.search(pattern, PAGE), pattern
    assert not re.search(r"<[^>]*\son[a-z]+\s*=", PAGE, re.I), "HTML 裡有行內的事件屬性"
    assert not re.search(r"""["'`]\s*<\s*[a-z]+[\s>]""", SCRIPT, re.I), "JS 裡有拼 HTML 的字串"


def test_page_html_makes_no_network_requests_and_loads_nothing_external():
    for pattern in (r"<script[^>]*\ssrc=", r"<link\b", r"<img[^>]*\ssrc=\"?https?:", r"@import", r"url\(\s*[\"']?https?:", r"\bfetch\s*\(",
                    r"XMLHttpRequest", r"WebSocket", r"EventSource", r"sendBeacon", r"<iframe", r"<form\b", r"<base\b"):
        assert not re.search(pattern, PAGE, re.I), pattern


def test_page_html_keeps_nothing_in_browser_storage_and_never_stores_the_url():
    for pattern in (r"localStorage", r"sessionStorage", r"document\.cookie", r"indexedDB"):
        assert not re.search(pattern, PAGE), pattern
    assert '$("lineUrl").value = ""' in PAGE and 'type="password"' in PAGE and 'autocomplete="off"' in PAGE
    assert PAGE.count("lineUrl") == 3 and "masked_url" in PAGE and re.search(r"\.url\b", SCRIPT) is None   # 只拿得到遮過的


def test_line_text_reaches_the_page_only_through_textcontent_or_append():
    """LINE 區塊相關的函式：放字只用 el(…, 字)（textContent）與 append(字串)。"""
    names = ("eventRow", "taskRow", "jotRow", "logRows", "fillLine", "addLineRows", "lineMoodMark", "openCopy", "renderChip",
             "fillSettings")
    for name in names:
        body = SCRIPT[SCRIPT.index(f"function {name}") if f"function {name}" in SCRIPT else SCRIPT.index(f"const {name}"):]
        body = body[:body.index("\n}\n") + 3] if "\n}\n" in body else body[:600]
        assert "innerHTML" not in body and "innerText" not in body and "insertAdjacentHTML" not in body, name
    assert "textContent" in SCRIPT and "const el = (tag, cls, text)" in SCRIPT


def test_page_html_title_placeholder_is_in_the_title_and_replaced_from_the_folder_name(tmp_path):
    assert PAGE.count("{{TITLE}}") == 1 and "<title>{{TITLE}}</title>" in PAGE
    from support import FakeApp
    folder = tmp_path / "modules" / "行事曆 2"
    folder.mkdir(parents=True)
    shutil.copy(iplot.HERE / "page.html", folder / "page.html")
    app = FakeApp(tmp_path / "iPLoT")
    iplot.open_or_focus(app, folder, environ={iplot.ENV: "1"}, ps=lambda: "", api=object(), me=1)
    title, html, _ = app.pages[0]
    assert title == "行事曆 2" and "<title>行事曆 2</title>" in html and "{{TITLE}}" not in html


def test_every_api_method_the_page_calls_exists_and_nothing_else_is_called(make_api):
    h = make_api()
    called = set(re.findall(r"call\(\s*\"([a-z_]+)\"", SCRIPT))
    public = {name for name in dir(h.api) if not name.startswith("_")}
    assert called <= public, called - public
    assert {"line_state", "line_refresh", "line_set_url", "line_clear", "line_set_auto", "line_copy_preview", "line_copy"} <= called


def test_every_element_id_the_script_uses_exists_in_the_html():
    ids = set(re.findall(r'\bid="([A-Za-z]+)"', PAGE))
    made_by_js = set(re.findall(r"\.id = \"([A-Za-z]+)\"", SCRIPT))       # 「note」「photos」「copyLine」是 JS 自己造的
    used = set(re.findall(r"\$\(\"([A-Za-z]+)\"\)", SCRIPT))
    assert used - ids - made_by_js == set(), used - ids - made_by_js


@pytest.mark.skipif(shutil.which("node") is None, reason="沒有 node：跳過 JS 語法檢查")
def test_page_script_parses_as_javascript(tmp_path):
    script = tmp_path / "page.js"
    script.write_text(SCRIPT, encoding="utf-8")
    done = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
