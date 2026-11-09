"""新舊兩個行事曆同時開不會打架（docs/01_設計.md 第 3 節）：.pid、環境變數、找自己的程序、名字、圖示。

用假的 ps、假的 popen、假的 environ，不真的開任何程序。舊的行事曆資料夾叫「行事曆」，是新的「行事曆 2」的前綴。"""

import hashlib
import struct
import types
import unicodedata
import zlib

import pytest
from support import FakeApp

import iplot

OLD_ICON_SHA = "63f1ee6e7f9b14bb9c4047ec99f0e875379799b05ebb474f7543cf8b7807f671"   # 行事曆 0.1.1 的 icon.png
RUN = "/Users/someone/iPLoT/modules/互通/run.py"


def command(folder, python="/usr/bin/python3"):
    return f"{python} {RUN} {folder}"


def fake_ps(*processes):
    return lambda: "".join(f"  {pid} {cmd}\n" for pid, cmd in processes)


@pytest.fixture
def folders(tmp_path):
    modules = tmp_path / "modules"
    new, old = modules / "行事曆 2", modules / "行事曆"
    for folder in (new, old):
        folder.mkdir(parents=True)
    return types.SimpleNamespace(new=new, old=old, modules=modules)


class Popen:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))


def home_with_interop(home):
    run = home / "modules" / "互通" / "run.py"
    run.parent.mkdir(parents=True, exist_ok=True)
    run.write_text("", encoding="utf-8")
    return home


# ── 找自己的程序 ──

def test_the_old_folder_name_really_is_a_prefix_of_the_new_one(folders):
    assert str(folders.new).startswith(str(folders.old)) and str(folders.old) in command(folders.new)   # 「含有」比對會出事的原因


def test_old_calendar_command_is_not_mistaken_for_the_new_one(folders):
    pid_file = folders.new / ".pid"
    pid_file.write_text("111", encoding="utf-8")
    assert iplot.running_pid(folders.new, pid_file, fake_ps((111, command(folders.old))), me=1) is None


def test_new_calendar_command_is_not_mistaken_for_the_old_one(folders):
    """用舊行事曆的資料夾當目標、去比新行事曆的指令：舊的「含有」比對會誤認（上一個測試證明路徑含有它），結尾比對不會。"""
    pid_file = folders.old / ".pid"
    pid_file.write_text("222", encoding="utf-8")
    assert iplot.running_pid(folders.old, pid_file, fake_ps((222, command(folders.new))), me=1) is None


def test_folder_name_that_extends_ours_is_not_mistaken_for_us(folders):
    pid_file = folders.new / ".pid"
    pid_file.write_text("333", encoding="utf-8")
    for other in (f"{folders.new} 備份", f"{folders.new}2", f"{folders.new}/子資料夾", f"{folders.new}-copy"):
        assert iplot.running_pid(folders.new, pid_file, fake_ps((333, command(other))), me=1) is None, other


def test_a_name_that_merely_ends_the_same_way_is_not_us(folders, tmp_path):
    """別的地方也有一個「行事曆 2」：路徑前面不一樣，不是我們。"""
    elsewhere = tmp_path / "別處" / "modules" / "行事曆 2"
    pid_file = folders.new / ".pid"
    pid_file.write_text("444", encoding="utf-8")
    assert iplot.running_pid(folders.new, pid_file, fake_ps((444, command(elsewhere))), me=1) is None


def test_our_own_command_is_recognised_even_with_trailing_space_and_a_different_python(folders):
    pid_file = folders.new / ".pid"
    pid_file.write_text("555", encoding="utf-8")
    app_python = "/Applications/Python 3.14/Python.app/Contents/MacOS/Python"
    for cmd in (command(folders.new), command(folders.new) + "  ", command(folders.new, app_python)):
        assert iplot.running_pid(folders.new, pid_file, fake_ps((555, cmd)), me=1) == 555


def test_a_process_without_run_py_is_not_us(folders):
    pid_file = folders.new / ".pid"
    pid_file.write_text("555", encoding="utf-8")
    assert iplot.running_pid(folders.new, pid_file, fake_ps((555, f"/usr/bin/vim {folders.new}")), me=1) is None


def test_unicode_normalization_nfc_vs_nfd(tmp_path):
    folder = tmp_path / "modules" / "café 行事曆 2"
    folder.mkdir(parents=True)
    pid_file = folder / ".pid"
    pid_file.write_text("666", encoding="utf-8")
    decomposed = unicodedata.normalize("NFD", command(folder))
    assert decomposed != command(folder)
    assert iplot.running_pid(folder, pid_file, fake_ps((666, decomposed)), me=1) == 666


def test_pid_that_is_ourselves_or_garbage_or_missing_is_not_running(folders):
    pid_file = folders.new / ".pid"
    assert iplot.running_pid(folders.new, pid_file, fake_ps(), me=1) is None
    for text in ("", "abc", "12 34", "-1"):
        pid_file.write_text(text, encoding="utf-8")
        assert iplot.running_pid(folders.new, pid_file, fake_ps((12, command(folders.new))), me=1) is None
    pid_file.write_text("777", encoding="utf-8")
    assert iplot.running_pid(folders.new, pid_file, fake_ps((777, command(folders.new))), me=777) is None


# ── 開起來 ──

def test_pid_file_is_inside_our_own_folder_and_removed_when_the_page_closes(folders):
    seen = {}

    class App(FakeApp):
        def page(self, title, html, api=None):
            seen["ours"] = (folders.new / ".pid").exists()
            seen["old"] = (folders.old / ".pid").exists()

    (folders.new / "page.html").write_text("<title>{{TITLE}}</title>", encoding="utf-8")
    assert iplot.PID == ".pid"
    iplot.open_or_focus(App(folders.modules.parent), folders.new, environ={iplot.ENV: "1"}, ps=fake_ps(), api=object(), me=1)
    assert seen == {"ours": True, "old": False} and not (folders.new / ".pid").exists()


def test_the_env_marker_is_taken_out_of_the_environment_so_children_do_not_inherit_it(folders):
    environ = {iplot.ENV: "1", "KEEP": "x"}
    (folders.new / "page.html").write_text("<title>{{TITLE}}</title>", encoding="utf-8")
    iplot.open_or_focus(FakeApp(folders.modules.parent), folders.new, environ=environ, ps=fake_ps(), api=object(), me=1)
    assert environ == {"KEEP": "x"}


def test_env_name_differs_from_the_old_calendars_and_launch_sets_only_ours(folders):
    assert iplot.ENV == "IPLOT_CALENDAR_LINE" and iplot.ENV != "IPLOT_CALENDAR"
    popen = Popen()
    iplot.launch(folders.modules.parent, folders.new, popen=popen, python="/py", environ={"HOME": "/h"})
    args, kwargs = popen.calls[0]
    assert args == ["/py", str(folders.modules.parent / "modules" / "互通" / "run.py"), str(folders.new)]
    assert kwargs["env"] == {"HOME": "/h", iplot.ENV: "1"} and "IPLOT_CALENDAR" not in kwargs["env"] and kwargs["start_new_session"] is True


def test_the_old_calendars_marker_in_the_environment_does_not_make_us_open_in_this_process(folders, tmp_path):
    """舊的記號（IPLOT_CALENDAR=1）跑進來：我們不當它是自己的，照樣另開一個程序，不會在面板的程序裡開頁面把面板鎖住。"""
    app, popen = FakeApp(home_with_interop(tmp_path / "iPLoT")), Popen()
    iplot.open_or_focus(app, folders.new, environ={"IPLOT_CALENDAR": "1"}, ps=fake_ps(), popen=popen, platform="linux", me=1)
    assert app.pages == [] and len(popen.calls) == 1 and popen.calls[0][1]["env"]["IPLOT_CALENDAR_LINE"] == "1"


def test_open_while_the_old_calendar_is_running_still_opens_ours(folders, tmp_path):
    app, popen = FakeApp(home_with_interop(tmp_path / "iPLoT")), Popen()
    (folders.old / ".pid").write_text("900", encoding="utf-8")
    iplot.open_or_focus(app, folders.new, environ={}, ps=fake_ps((900, command(folders.old))), popen=popen, platform="linux", me=1)
    assert len(popen.calls) == 1 and popen.calls[0][0][-1] == str(folders.new) and app.logs == ["打開行事曆 2"]


def test_open_while_ours_is_running_focuses_ours_and_never_launches_a_second(folders, tmp_path):
    app, popen, activated = FakeApp(home_with_interop(tmp_path / "iPLoT")), Popen(), []
    (folders.new / ".pid").write_text("901", encoding="utf-8")
    ps = fake_ps((901, command(folders.new)), (902, command(folders.old)))
    iplot.open_or_focus(app, folders.new, environ={}, ps=ps, popen=popen, platform="linux", me=1)
    assert popen.calls == [] and app.logs == ["行事曆 2已經開著（在 Dock 上找月曆的圖示）"]
    iplot.open_or_focus(app, folders.new, environ={}, ps=ps, popen=popen, platform="darwin", me=1,
                        activate=lambda pid, platform: activated.append(pid) or True)
    assert popen.calls == [] and activated == [901] and app.logs[-1] == "行事曆 2已經開著"


def test_stale_pid_for_a_recycled_pid_that_now_runs_the_old_calendar_is_not_ours(folders, tmp_path):
    app, popen = FakeApp(home_with_interop(tmp_path / "iPLoT")), Popen()
    (folders.new / ".pid").write_text("903", encoding="utf-8")   # 我們上次關掉了沒清乾淨；那個號碼現在是舊行事曆的程序
    iplot.open_or_focus(app, folders.new, environ={}, ps=fake_ps((903, command(folders.old))), popen=popen, platform="linux", me=1)
    assert len(popen.calls) == 1 and "已經開著" not in "".join(app.logs)


def test_without_interop_it_says_so_with_our_name_and_does_nothing_else(folders, tmp_path):
    app, popen = FakeApp(tmp_path / "沒有互通的 iPLoT"), Popen()
    iplot.open_or_focus(app, folders.new, environ={}, ps=fake_ps(), popen=popen, platform="linux", me=1)
    assert popen.calls == [] and app.logs == ["行事曆 2要用「互通」另開視窗：到工作坊裝「互通」"]


def test_window_title_page_title_and_messages_come_from_the_folder_name(tmp_path):
    mine = tmp_path / "modules" / "我的 <日記> & 行事曆"
    mine.mkdir(parents=True)
    (mine / "page.html").write_text("<title>{{TITLE}}</title><h1>{{TITLE}}</h1>", encoding="utf-8")
    app = FakeApp(home_with_interop(tmp_path / "iPLoT"))
    iplot.open_or_focus(app, mine, environ={iplot.ENV: "1"}, ps=fake_ps(), api=object(), me=1)
    title, html, _ = app.pages[0]
    assert title == "我的 <日記> & 行事曆"
    assert "<title>我的 &lt;日記&gt; &amp; 行事曆</title>" in html and "<日記>" not in html     # 放進頁面的名字有跳脫
    popen = Popen()
    iplot.open_or_focus(app, mine, environ={}, ps=fake_ps(), popen=popen, platform="linux", me=1)
    assert app.logs == ["打開我的 <日記> & 行事曆"]


def test_this_module_never_writes_the_old_name_into_a_message(folders, tmp_path):
    app = FakeApp(home_with_interop(tmp_path / "iPLoT"))
    iplot.open_or_focus(app, folders.new, environ={}, ps=fake_ps(), popen=Popen(), platform="linux", me=1)
    assert app.logs == ["打開行事曆 2"]
    for text in (iplot.NO_INTEROP, iplot.OPENED, iplot.ALREADY, iplot.ALREADY_BEHIND):
        assert "{name}" in text and "行事曆" not in text            # 名字用資料夾名，不寫死


# ── 圖示、模組列 ──

def test_icon_png_differs_from_the_old_one_and_is_a_valid_png():
    data = (iplot.HERE / "icon.png").read_bytes()
    assert hashlib.sha256(data).hexdigest() != OLD_ICON_SHA and data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) < 1024 * 1024
    position, chunks = 8, []
    while position < len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        body, crc = data[position + 8:position + 8 + length], struct.unpack(">I", data[position + 8 + length:position + 12 + length])[0]
        assert zlib.crc32(kind + body) & 0xFFFFFFFF == crc, kind
        chunks.append((kind, body))
        position += 12 + length
    assert [kind for kind, _ in chunks][0] == b"IHDR" and chunks[-1][0] == b"IEND"
    width, height, depth, color = struct.unpack(">IIBB", chunks[0][1][:10])
    assert (width, height, depth, color) == (256, 256, 8, 6)
    raw = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    assert len(raw) == height * (1 + width * 4)


def test_icon_file_constant_points_at_our_own_icon():
    assert iplot.ICON_FILE == iplot.HERE / "icon.png" and iplot.ICON_FILE.is_file() and iplot.ICON != "📅"


def test_module_bar_lists_the_old_calendar_and_skips_ourselves_the_system_module_and_the_panel(fake_app, monkeypatch, tmp_path):
    def module(name):
        return types.SimpleNamespace(name=name, icon=None, title=name, folder=tmp_path / name)

    names = ["行事曆", iplot.HERE.name, "作業系統", "主控面板", "開工"]
    fake_scan = types.SimpleNamespace(roots_from_config=lambda home, roots: ["R"],
                                      find_modules=lambda roots: [types.SimpleNamespace(modules=[module(n) for n in names])])
    monkeypatch.setattr(iplot, "scan", fake_scan)
    api = iplot.Api(fake_app, tmp_path / "設定.json", default_root=tmp_path / "d", platform="linux", environ={})
    bar = api.modules()
    assert [m["name"] for m in bar["modules"]] == ["行事曆", "開工"] and bar["panel"] is True
    assert iplot.HERE.name == "行事曆 2"
