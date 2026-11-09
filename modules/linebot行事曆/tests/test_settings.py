"""設定.json：讀寫時保留不認得的鍵、權限 0600、先寫暫存檔再換（docs/01_設計.md 第 4.4 節，L05）。"""

import json
import os
import stat

import pytest

import diary
import settings


def test_read_of_missing_corrupt_or_non_object_files_is_empty(settings_file):
    assert settings.read(settings_file) == {}
    settings_file.write_text("{不是 json", encoding="utf-8")
    assert settings.read(settings_file) == {}
    settings_file.write_text("[1, 2]", encoding="utf-8")
    assert settings.read(settings_file) == {}
    settings_file.write_bytes(b"\xff\xfe\x00bad")
    assert settings.read(settings_file) == {}


def test_update_keeps_unknown_keys_at_every_level(settings_file):
    settings_file.write_text(json.dumps({"資料夾": "/a", "未來的鍵": [1, 2], "LINE": {"url": "u", "write_key": "k"}}), encoding="utf-8")

    def change(data):
        data["LINE"]["auto_copy"] = True

    result = settings.update(settings_file, change)
    on_disk = json.loads(settings_file.read_text(encoding="utf-8"))
    assert on_disk == result
    assert on_disk["未來的鍵"] == [1, 2]
    assert on_disk["資料夾"] == "/a"
    assert on_disk["LINE"] == {"url": "u", "write_key": "k", "auto_copy": True}


def test_corrupt_file_reads_as_empty_and_update_replaces_it(settings_file):
    settings_file.write_text("{壞掉", encoding="utf-8")
    settings.update(settings_file, lambda d: d.update({"資料夾": "/x"}))
    assert json.loads(settings_file.read_text(encoding="utf-8")) == {"資料夾": "/x"}


def test_file_mode_is_0600_even_when_replacing_a_world_readable_file(settings_file):
    settings_file.write_text("{}", encoding="utf-8")
    os.chmod(settings_file, 0o644)
    settings.update(settings_file, lambda d: d.update({"a": 1}))
    assert stat.S_IMODE(settings_file.stat().st_mode) == 0o600


def test_write_is_atomic_when_replace_fails(settings_file, monkeypatch):
    settings_file.write_text(json.dumps({"資料夾": "/old"}), encoding="utf-8")

    def broken(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(settings.os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        settings.update(settings_file, lambda d: d.update({"資料夾": "/new"}))
    assert json.loads(settings_file.read_text(encoding="utf-8")) == {"資料夾": "/old"}
    assert [p.name for p in settings_file.parent.iterdir()] == [settings_file.name]  # 沒有留下暫存檔


def test_write_private_creates_parent_folders_and_writes_text_verbatim(tmp_path):
    target = tmp_path / "a" / "b" / "x.json"
    settings.write_private(target, "內容\n")
    assert target.read_text(encoding="utf-8") == "內容\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_line_section_is_a_dict_or_empty(settings_file):
    assert settings.line(settings_file) == {}
    settings_file.write_text(json.dumps({"LINE": "不是物件"}), encoding="utf-8")
    assert settings.line(settings_file) == {}
    settings_file.write_text(json.dumps({"LINE": {"url": "u"}}), encoding="utf-8")
    assert settings.line(settings_file) == {"url": "u"}


def test_save_root_keeps_the_line_section_and_unknown_keys(settings_file, tmp_path):
    settings_file.write_text(json.dumps({"LINE": {"url": "u", "write_key": "k"}, "未來的鍵": 1}), encoding="utf-8")
    diary.save_root(settings_file, tmp_path / "新的資料夾")
    on_disk = json.loads(settings_file.read_text(encoding="utf-8"))
    assert on_disk["LINE"] == {"url": "u", "write_key": "k"}
    assert on_disk["未來的鍵"] == 1
    assert on_disk["資料夾"] == str(tmp_path / "新的資料夾")


def test_load_root_still_reads_what_save_root_wrote(settings_file, tmp_path):
    diary.save_root(settings_file, tmp_path / "d")
    assert diary.load_root(settings_file, tmp_path / "default") == (tmp_path / "d").resolve()


def test_line_section_helper_creates_or_returns_the_section_in_place():
    data = {"LINE": {"url": "u"}}
    settings.line_section(data)["auto_copy"] = True
    assert data == {"LINE": {"url": "u", "auto_copy": True}}
    for broken in ({}, {"LINE": "x"}, {"LINE": None}):
        settings.line_section(broken)["a"] = 1
        assert broken == {"LINE": {"a": 1}}
