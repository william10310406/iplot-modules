import unicodedata
import warnings
import zipfile
import zlib

import pytest
import zipcheck
from conftest import FIXTURES, big5_zip, make_zip, patch_zip
from say import Refusal, code

IPLOT_PY = "x" * 1100  # 第一條一律 m/iplot.py、至少 1 KB（patch_zip 只改第一條）


def good(**extra):
    return {"m/iplot.py": IPLOT_PY, **extra}


def run(tmp_path, entries=None, **kwargs):
    zip_path = make_zip(tmp_path / "u.zip", entries if entries is not None else good(), **kwargs)
    return zipcheck.inspect(zip_path, tmp_path / "staging")


def raw_zip(path, names):
    """逐條寫、允許重複的名字（make_zip 的 dict 做不到）；zipfile 對重複名字的 UserWarning 在這裡收掉。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("m/iplot.py", IPLOT_PY)
            for name in names:
                z.writestr(name, b"" if name.endswith("/") else b"x")
    return path


def test_finder_fixture_really_lacks_the_utf8_flag():
    with zipfile.ZipFile(FIXTURES / "finder-整理桌面.zip") as z:
        infos = z.infolist()
    assert all(i.flag_bits & 0x800 == 0 for i in infos)
    assert not any("一" <= c <= "鿿" for i in infos for c in i.filename)


def test_task0_finder_zip_is_received(tmp_path):
    fixture = FIXTURES / "finder-task0.zip"
    if not fixture.is_file():
        pytest.skip("沒有 finder-task0.zip")
    result = zipcheck.inspect(fixture, tmp_path / "staging")
    assert not isinstance(result, Refusal), result
    assert result.name == "整理桌面"
    paths = [f.path for f in result.files]
    assert "iplot.py" in paths
    assert "說明.txt" in paths


def test_finder_zip_with_an_outer_folder_is_the_wrong_shape(tmp_path):
    result = zipcheck.inspect(FIXTURES / "finder-外層.zip", tmp_path / "staging")
    assert isinstance(result, Refusal)
    assert result.key == "shape"


def test_finder_zip_is_unpacked_with_the_right_chinese_names(tmp_path):
    staging = tmp_path / "staging"
    result = zipcheck.inspect(FIXTURES / "finder-整理桌面.zip", staging)
    assert not isinstance(result, Refusal), result
    assert result.name == "整理桌面"
    assert [f.path for f in result.files] == ["iplot.py", "小工具.py", "資料/說明.txt"]
    assert set(result.skipped) >= {"__MACOSX/", ".DS_Store", ".history/", "Icon\\r", "符號連結"}
    assert not (staging / "整理桌面" / "捷徑").exists()
    assert not (staging / "整理桌面" / ".history").exists()


def test_nfd_finder_zip_becomes_nfc(tmp_path):
    staging = tmp_path / "staging"
    result = zipcheck.inspect(FIXTURES / "finder-nfd.zip", staging)
    assert not isinstance(result, Refusal), result
    nfc = unicodedata.normalize("NFC", "ガイド")
    assert result.name == nfc
    assert [p.name for p in staging.iterdir()] == [nfc]


def test_files_carry_size_and_sha256(tmp_path):
    import hashlib

    result = run(tmp_path, good(**{"m/sub/a.txt": "內容"}))
    assert not isinstance(result, Refusal), result
    assert len(result.files) == 2
    for f in result.files:
        data = (result.folder / f.path).read_bytes()
        assert f.size == len(data)
        assert f.sha256 == hashlib.sha256(data).hexdigest()


def test_not_a_zip(tmp_path):
    path = tmp_path / "u.zip"
    path.write_bytes(b"hello")
    result = zipcheck.inspect(path, tmp_path / "staging")
    assert isinstance(result, Refusal)
    assert result.key == "not_zip"


def test_big5_names_are_refused_as_not_utf8(tmp_path):
    result = zipcheck.inspect(big5_zip(tmp_path / "u.zip"), tmp_path / "staging")
    assert isinstance(result, Refusal)
    assert result.key == "names_not_utf8"


def test_invalid_utf8_with_the_flag_is_refused_as_not_utf8(tmp_path):
    path = make_zip(tmp_path / "u.zip", {"整理桌面/iplot.py": IPLOT_PY})
    raw = path.read_bytes()
    assert raw.count("整".encode()) == 2  # 本地檔頭、中央目錄
    path.write_bytes(raw.replace("整".encode(), b"\xff\xff\xff"))
    result = zipcheck.inspect(path, tmp_path / "staging")
    assert isinstance(result, Refusal)
    assert result.key == "names_not_utf8"


@pytest.mark.parametrize("entries", [
    {"a/iplot.py": "x", "b/iplot.py": "x"},
    {"iplot.py": "x"},
    {"m/readme.txt": "x"},
    {"m/IPLOT.py": "x"},
    {"m/sub/iplot.py": "x"},
])
def test_shape_needs_exactly_one_folder_with_lowercase_iplot(tmp_path, entries):
    result = run(tmp_path, entries)
    assert isinstance(result, Refusal)
    assert result.key == "shape"


@pytest.mark.parametrize("bad", ["m/../x", "/m/iplot.py", "m\\x", "m/a\x01b", "m/a:b", "m/CON", "m/con.txt",
                                 "m/a.", "m/a ", "m//iplot.py", "m/git~1/x", "m/GIT~12/x"])
def test_bad_paths_are_refused(tmp_path, bad):
    path = tmp_path / "u.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("m/iplot.py", IPLOT_PY)
        z.writestr(bad, b"x")
    result = zipcheck.inspect(path, tmp_path / "staging")
    assert isinstance(result, Refusal)
    assert result.key == "bad_path"
    assert code(bad) in result.text
    assert not any(unicodedata.category(c) == "Cc" for c in result.text)


@pytest.mark.parametrize("pair", [("m/a", "m/a/b"), ("m/a/", "m/a"), ("m/A/x", "m/a/y"), ("m/x", "m/X"),
                                  ("m/x", "m/x")])
def test_conflicts_are_refused(tmp_path, pair):
    path = raw_zip(tmp_path / "u.zip", pair)
    staging = tmp_path / "staging"
    result = zipcheck.inspect(path, staging)
    assert isinstance(result, Refusal)
    assert result.key == "bad_path"
    assert not staging.exists() or not any(staging.iterdir())


def test_skipped_names_are_counted_by_group(tmp_path):
    names = ["m/.git/config", "m/.gitignore", "m/.gitattributes", "m/.gitmodules", "m/.github/x", "m/.gitkeep",
             "m/sub/.git", "m/.GIT/x", "m/.venv/a", "m/__pycache__/a.pyc", "m/.Origin", "m/.unconfirmed",
             "m/._x", "__MACOSX/m/._iplot.py"]
    result = run(tmp_path, good(**{n: "x" for n in names}))
    assert not isinstance(result, Refusal), result
    assert [f.path for f in result.files] == ["iplot.py"]
    assert result.skipped == {".git*": 8, ".venv/": 1, "__pycache__/": 1, ".origin": 1, ".unconfirmed": 1,
                              "._*": 1, "__MACOSX/": 1}


def test_symlink_is_skipped_not_followed(tmp_path):
    result = run(tmp_path, symlinks={"m/捷徑": "/etc/passwd"})
    assert not isinstance(result, Refusal), result
    assert result.skipped["符號連結"] == 1
    assert not (result.folder / "捷徑").exists()
    assert [f.path for f in result.files] == ["iplot.py"]


def test_icon_cr_is_skipped(tmp_path):
    result = run(tmp_path, good(**{"m/Icon\r": ""}))
    assert not isinstance(result, Refusal), result
    assert result.skipped == {"Icon\\r": 1}
    assert [f.path for f in result.files] == ["iplot.py"]


def _forbid_open(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("不該讀任何內容")

    monkeypatch.setattr(zipfile.ZipFile, "open", boom)


def test_entry_count_over_20000_is_refused_before_reading(tmp_path, monkeypatch):
    entries = good(**{f"m/f{i}": "" for i in range(zipcheck.MAX_ENTRIES)})  # 20001 條
    zip_path = make_zip(tmp_path / "u.zip", entries)
    _forbid_open(monkeypatch)
    result = zipcheck.inspect(zip_path, tmp_path / "staging")
    assert isinstance(result, Refusal)
    assert result.key == "too_many_entries"


def test_venv_entries_do_not_count_toward_2000(tmp_path):
    entries = good(**{f"m/.venv/f{i}": "" for i in range(3000)}, **{"m/a.txt": "a", "m/b.txt": "b"})
    result = run(tmp_path, entries)
    assert not isinstance(result, Refusal), result
    assert len(result.files) == 3


def test_2001_files_are_refused(tmp_path):
    result = run(tmp_path, good(**{f"m/f{i}": "" for i in range(zipcheck.MAX_FILES)}))
    assert isinstance(result, Refusal)
    assert result.key == "too_many_files"


def test_declared_total_over_100mb_is_refused_before_reading(tmp_path, monkeypatch):
    zip_path = patch_zip(make_zip(tmp_path / "u.zip", good()), size_delta=zipcheck.MAX_UNPACKED)
    _forbid_open(monkeypatch)
    result = zipcheck.inspect(zip_path, tmp_path / "staging")
    assert isinstance(result, Refusal)
    assert result.key == "too_large"


def test_size_lie_is_broken(tmp_path):
    zip_path = patch_zip(make_zip(tmp_path / "u.zip", good()), size_delta=1000)
    result = zipcheck.inspect(zip_path, tmp_path / "staging")
    assert isinstance(result, Refusal)
    assert result.key == "broken"
    assert "宣告的大小跟內容不一樣" in result.text


@pytest.mark.parametrize("patch, exc", [(dict(encrypted=True), RuntimeError), (dict(method=9), NotImplementedError),
                                        (dict(first_data_byte=0xFF), zlib.error),
                                        (dict(size_delta=-10), zipfile.BadZipFile)])
def test_known_breakages_raise_for_receive_to_map(tmp_path, patch, exc):
    zip_path = patch_zip(make_zip(tmp_path / "u.zip", good()), **patch)
    with pytest.raises(exc):
        zipcheck.inspect(zip_path, tmp_path / "staging")


def test_never_reads_a_whole_entry_at_once(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("不該用 read / extractall")

    monkeypatch.setattr(zipfile.ZipFile, "read", boom)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", boom)
    result = run(tmp_path)
    assert not isinstance(result, Refusal), result
