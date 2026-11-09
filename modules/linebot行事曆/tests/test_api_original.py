"""原本的 Api（行事曆 0.1.1）的行為沒有被改壞：舊的測試（tests/test_calendar.py）沒有跟著模組一起發，這裡補一組輕量的。

不測 LINE（沒有設網址）；只確認存檔、公開、網頁、設定、錯誤這些原本的事照舊。"""

import json

import pytest

import diary

DATE = "2026-11-06"


def test_save_writes_the_given_fields_and_rebuilds_the_pages(make_api):
    h = make_api()
    result = h.api.save(DATE, {"行程": "早上開會", "看到": "一隻貓", "做了": "寫程式", "mood": "😄", "note": "好心情"})
    assert set(result["saved"]) == {"行程", "看到", "做了", "心情"} and result["unreadable"] == []
    day = diary.read_day(h.root, DATE)
    assert (day["行程"], day["看到"], day["做了"], day["mood"], day["note"]) == ("早上開會", "一隻貓", "寫程式", "😄", "好心情")
    assert (diary.day_folder(h.root, DATE) / "index.html").exists() and (h.root / "index.html").exists()


def test_save_ignores_unknown_fields_and_bad_types_and_unchanged_text(make_api):
    h = make_api()
    h.api.save(DATE, {"行程": "a"})
    assert h.api.save(DATE, {"行程": "a", "沒這欄": "x", "看到": 5}) == {"saved": [], "unreadable": []}
    assert h.api.save(DATE, "不是 dict") == {"saved": [], "unreadable": []}
    assert not (diary.day_folder(h.root, DATE) / "沒這欄.txt").exists()


def test_save_never_overwrites_a_file_that_is_not_utf8(make_api):
    h = make_api()
    folder = diary.day_folder(h.root, DATE)
    folder.mkdir(parents=True)
    (folder / "行程.txt").write_bytes(b"\xff\xfe\x00bad")
    result = h.api.save(DATE, {"行程": "想蓋掉"})
    assert result["saved"] == [] and len(result["unreadable"]) == 1 and (folder / "行程.txt").read_bytes() == b"\xff\xfe\x00bad"


def test_save_keeps_the_old_text_in_history(make_api):
    h = make_api()
    h.api.save(DATE, {"行程": "第一版"})
    h.api.save(DATE, {"行程": "第二版"})
    history = diary.day_folder(h.root, DATE) / diary.HISTORY
    assert [p.read_text(encoding="utf-8") for p in history.glob("行程-*.txt")] == ["第一版"]


def test_set_public_toggles_the_marker_and_rebuilds(make_api):
    h = make_api()
    h.api.save(DATE, {"行程": "x"})
    assert h.api.set_public(DATE, True) == {"public": True} and diary.read_day(h.root, DATE)["public"] is True
    assert h.api.set_public(DATE, 0) == {"public": False}


def test_month_year_day_basics_without_line(make_api):
    h = make_api()
    h.api.save(DATE, {"行程": "第一行\n第二行", "mood": "🙂", "note": ""})
    month, year, day = h.api.month("2026-11"), h.api.year("2026"), h.api.day(DATE)
    assert month["today"] == "2026-11-08" and month["days"]["06"]["first"] == "第一行" and month["days"]["06"]["mood"] == "🙂"
    assert year["months"] == {"11": {"06": "🙂"}} and day["行程"] == "第一行\n第二行" and day["images"] == [] and day["public"] is False


def test_bad_dates_become_an_error_sentence_not_an_exception(make_api):
    h = make_api()
    for call in (lambda: h.api.month("2026-13"), lambda: h.api.year("26"), lambda: h.api.day("2026-02-30"),
                 lambda: h.api.save("x", {}), lambda: h.api.set_public("2026-1-1", True), lambda: h.api.open_page("day", "x"),
                 lambda: h.api.open_page("nonsense", "")):
        assert "日期格式不對" in call()["error"]


def test_open_page_builds_the_local_page_and_hands_it_to_app_open(make_api):
    h = make_api()
    h.api.save(DATE, {"行程": "x"})
    for kind, key in (("day", DATE), ("month", "2026-11"), ("year", "2026"), ("index", "")):
        assert h.api.open_page(kind, key) == {}
        assert h.app.opened[-1].name == "index.html" and h.app.opened[-1].exists()


def test_publish_with_nothing_public_and_with_a_public_day(make_api):
    h = make_api()
    assert "還沒有打開" in h.api.publish()["error"] and not (h.root / "發佈").exists()
    h.api.save(DATE, {"行程": "公開的行程"})
    h.api.set_public(DATE, True)
    result = h.api.publish()
    assert result["days"] == 1 and result["problems"] == [] and (h.root / "發佈" / "index.html").exists()
    assert h.app.opened[-1] == h.root / "發佈"
    h.api.set_public(DATE, False)
    assert "已經拿掉" in h.api.publish()["note"] and not (h.root / "發佈").exists()


def test_settings_change_folder_and_reveal_folder(make_api, tmp_path):
    h = make_api()
    assert h.api.settings() == {"folder": str(h.root), "public_days": 0}
    elsewhere = tmp_path / "別的資料夾"
    h.app.chosen_folder = None
    assert h.api.change_folder()["folder"] == str(h.root)                      # 按了取消：不變
    h.app.chosen_folder = elsewhere
    assert h.api.change_folder()["folder"] == str(elsewhere.resolve())
    assert json.loads(h.settings.read_text(encoding="utf-8"))["資料夾"] == str(elsewhere)
    h.api.reveal_folder()
    assert elsewhere.is_dir() and h.app.opened[-1] == elsewhere.resolve()


def test_change_folder_keeps_the_line_settings(make_api, tmp_path):
    h = make_api(url="https://line.example.test/j/" + "a" * 40 + ".json")
    h.api.line_set_auto(True)
    h.app.chosen_folder = tmp_path / "新資料夾"
    h.api.change_folder()
    line = json.loads(h.settings.read_text(encoding="utf-8"))["LINE"]
    assert line["url"].startswith("https://") and line["auto_copy"] is True


def test_rebuild_counts_the_pages(make_api):
    h = make_api()
    assert h.api.rebuild() == {"pages": 1}                                       # 一天都沒有：只有綜合
    h.api.save(DATE, {"行程": "x"})
    assert h.api.rebuild()["pages"] >= 4


def test_add_image_rejects_what_is_not_an_image_and_remove_image_ignores_unknown_names(make_api):
    h = make_api()
    assert "error" in h.api.add_image(DATE, "a.jpg", "!!不是 base64")
    assert h.api.remove_image(DATE, "沒有這張.jpg") == {"images": []}


CANNOT_WRITE = {
    "save": ("diary.save_day", lambda api: api.save(DATE, {"行程": "x"})),
    "set_public": ("diary.set_public", lambda api: api.set_public(DATE, True)),
    "rebuild": ("pages.rebuild_all", lambda api: api.rebuild()),
    "publish": ("pages.publish", lambda api: api.publish()),
    "change_folder": ("settings.write_private", lambda api: api.change_folder()),
}


@pytest.mark.parametrize("name", list(CANNOT_WRITE))
def test_a_folder_that_cannot_be_written_is_a_sentence_not_a_traceback(make_api, monkeypatch, tmp_path, name):
    h = make_api()
    if name == "publish":
        diary.save_day(h.root, DATE, {"行程": "x"}, 20)
        diary.set_public(h.root, DATE, True)
    h.app.chosen_folder = tmp_path / "x"

    def broken(*args, **kwargs):
        raise OSError(13, "Permission denied", str(h.root))

    target, call = CANNOT_WRITE[name]
    monkeypatch.setattr(target, broken)
    result = call(h.api)
    assert "error" in result and "Permission denied" in result["error"] and str(h.root) not in json.dumps(result)
