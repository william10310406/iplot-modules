import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path

import build
import pytest
import receive
import registry
from conftest import DEFAULT_ATTACHMENT, FIXTURES, FakeApi, fake_fetch, issue, load_iplot
from gh import ApiError, NotFound
from iplot_rules import read_listing

TOOLS = Path(__file__).resolve().parents[1] / "tools"
VENDOR = Path(__file__).parent / "vendor" / "workshop_051.py"
IPLOT_PY = '"""整理桌面上的檔案。\n\n第二段不算。"""\nICON = "🧹"\n\ndef run(app):\n    pass\n'
NOTICE = "這份清單沒有人審查：裝之前先看過程式碼。"


def _load_051():
    spec = importlib.util.spec_from_file_location("workshop_051", VENDOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules["workshop_051"] = module
    spec.loader.exec_module(module)
    return module


workshop_051 = _load_051()


@pytest.fixture(autouse=True)
def no_github_env(monkeypatch):
    """測試不連網、不寫進 CI 的 summary：這三個變數一律拿掉，要的測試自己設。"""
    for name in ("GH_TOKEN", "GITHUB_REPOSITORY", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(name, raising=False)


def entry(name, version="0.0.1", owner_id=111, owner="someone", **extra) -> dict:
    return {"name": name, "owner_id": owner_id, "owner": owner, "version": version, "notes": "第一版",
            "issue": 1, "updated": "2026-10-21", **extra}


def make_repo(tmp_path, entries=(), modules=None, notice=NOTICE) -> Path:
    """tmp/repo：registry.json（entries 是 registry 的值）、notice.txt、modules/<名稱>/<檔>。
    modules 沒給就替每一筆有 version 的 entry 放一個只有 iplot.py 的資料夾。"""
    root = tmp_path / "repo"
    root.mkdir()
    registry.write_json(root / "registry.json", {registry.key(e["name"]): e for e in entries})
    if notice is not None:
        (root / "notice.txt").write_text(notice, encoding="utf-8")
    if modules is None:
        modules = {e["name"]: {"iplot.py": IPLOT_PY} for e in entries if "version" in e}
    for name, files in modules.items():
        for rel, data in files.items():
            path = root / "modules" / name / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, bytes):
                path.write_bytes(data)
            else:
                path.write_text(data, encoding="utf-8")
    return root


def run(root, site, api=None) -> int:
    return build.main([str(site), "--base-url", site.as_uri()], root=root, api=api)


def index_of(site) -> dict:
    return json.loads((site / "index.json").read_text(encoding="utf-8"))


def built(tmp_path, entries=(), modules=None, api=None, **kwargs):
    root = make_repo(tmp_path, entries, modules, **kwargs)
    site = tmp_path / "site"
    assert run(root, site, api) == 0
    return site, index_of(site)


def install(tmp_path, upload) -> str:
    modules_dir = tmp_path / "installed"
    modules_dir.mkdir(exist_ok=True)
    return workshop_051.install(upload, modules_dir)


def test_zip_shape_matches_workshop_install(tmp_path):
    site, index = built(tmp_path, [entry("整理桌面")],
                        {"整理桌面": {"iplot.py": IPLOT_PY, "資料/說明.txt": "說明", ".DS_Store": b"x",
                                      ".history/old.py": "舊的"}})
    [upload] = index["uploads"]
    with zipfile.ZipFile(site / "模組" / "整理桌面.zip") as z:
        names = z.namelist()
    assert names and all(n.startswith("整理桌面/") for n in names)
    assert names == ["整理桌面/iplot.py", "整理桌面/資料/說明.txt"]
    assert install(tmp_path, upload) == "installed"


def test_same_content_same_sha256(tmp_path):
    folder = tmp_path / "整理桌面"
    (folder / "sub").mkdir(parents=True)
    (folder / "iplot.py").write_text(IPLOT_PY, encoding="utf-8")
    (folder / "sub" / "a.txt").write_text("內容", encoding="utf-8")
    first = build.pack(folder, "整理桌面", tmp_path / "one")
    for path in (folder / "iplot.py", folder / "sub" / "a.txt"):
        os.utime(path, (1_500_000_000, 1_500_000_000))
    second = build.pack(folder, "整理桌面", tmp_path / "two")
    assert first == tmp_path / "one" / "整理桌面.zip"
    assert hashlib.sha256(first.read_bytes()).hexdigest() == hashlib.sha256(second.read_bytes()).hexdigest()


def test_index_has_empty_modules_and_reads_with_read_listing(tmp_path):
    site, index = built(tmp_path, [entry("整理桌面")])
    assert index["modules"] == []
    uploads, notice = read_listing(index)
    assert [u["name"] for u in uploads] == ["整理桌面"]
    assert notice == NOTICE
    assert set(index["uploads"][0]) == {"name", "version", "zip_url", "sha256", "description", "icon", "notes",
                                        "author"}


def test_old_workshop_sees_an_empty_list(tmp_path):
    site, _ = built(tmp_path, [entry("整理桌面")])
    assert workshop_051.read_index((site / "index.json").as_uri()) == []


def test_new_workshop_next_door_reads_the_index(tmp_path, iplot_next_door):
    workshop = load_iplot("modules/工作坊/workshop.py", "iplot_workshop_next")
    if not hasattr(workshop, "read_listing"):
        pytest.skip("iPLoT 那一段還沒做 read_listing")
    site, _ = built(tmp_path, [entry("整理桌面")])
    uploads, notice = workshop.read_listing((site / "index.json").as_uri())
    assert [u["name"] for u in uploads] == ["整理桌面"]
    assert uploads[0]["author"] == "someone"
    assert notice == NOTICE


def test_index_html_escapes_everything_and_has_no_script(tmp_path):
    iplot = '"""<script>alert(1)</script>"""\n'
    api = FakeApi(users={111: "a&b"})
    site, _ = built(tmp_path, [entry("整理桌面", notes="<img src=x onerror=y>", warning="<b>")],
                    {"整理桌面": {"iplot.py": iplot}}, api=api)
    page = (site / "index.html").read_text(encoding="utf-8")
    lowered = page.lower()
    assert "<script" not in lowered
    assert "<img" not in lowered
    assert "<b>" not in lowered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "&lt;img src=x onerror=y&gt;" in page
    assert "&lt;b&gt;" in page
    assert "@a&amp;b" in page
    assert "iPLoT 工作坊" in page
    assert build.FORM_URL.replace("&", "&amp;") in page or build.FORM_URL in page


def test_seed_like_registry_builds_and_reads(tmp_path):
    seed = [{"name": n, "reserved": True} for n in ("作業系統", "更新", "工作坊")]
    seed.append({"name": "打開核心原始碼", "owner_id": 1, "owner": "研究助理"})  # 種子：還沒有 version
    root = make_repo(tmp_path, seed, modules={})
    site = tmp_path / "site"
    assert run(root, site) == 0
    index = index_of(site)
    assert index["uploads"] == []
    assert read_listing(index) == ([], NOTICE)


def test_one_bad_entry_is_skipped_and_the_others_published(tmp_path, monkeypatch, capsys):
    good = entry("整理桌面")
    bad = [entry("不在"), entry("沒有"), entry("大寫"), entry("太大")]
    modules = {"整理桌面": {"iplot.py": IPLOT_PY}, "沒有": {"說明.txt": "x"}, "大寫": {"IPLOT.py": IPLOT_PY},
               "太大": {"iplot.py": IPLOT_PY}}
    root = make_repo(tmp_path, [good, *bad], modules)
    real = build.read_meta

    def read_meta(file):
        if file.parent.name == "太大":
            raise MemoryError
        return real(file)

    monkeypatch.setattr(build, "read_meta", read_meta)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    site = tmp_path / "site"
    assert run(root, site) == 0
    assert [u["name"] for u in index_of(site)["uploads"]] == ["整理桌面"]
    written = summary.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    for name in ("不在", "沒有", "大寫", "太大"):
        assert written.count(f"跳過「{name}」：") == 1
        assert out.count(f"跳過「{name}」：") == 1
    assert "跳過「整理桌面」" not in written


@pytest.mark.parametrize("where", ["icon", "notes"])
def test_lone_surrogate_entry_is_skipped_and_the_others_published(tmp_path, monkeypatch, where):
    """機器人還沒擋代理字元時放進來的那一筆：只跳過它，index.json 照樣寫得出來，其他照發。"""
    bad_iplot = '"""說明"""\nICON = "\\ud800"\n' if where == "icon" else IPLOT_PY  # 檔裡是 ASCII 的反斜線跳脫
    bad = entry("壞", notes="\ud800" if where == "notes" else "第一版")
    root = make_repo(tmp_path, modules={"壞": {"iplot.py": bad_iplot}, "好": {"iplot.py": IPLOT_PY}})
    data = {registry.key(e["name"]): e for e in (bad, entry("好"))}
    (root / "registry.json").write_text(json.dumps(data, indent=2) + "\n", encoding="ascii")  # 代理字元只能寫成 \ud800
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    site = tmp_path / "site"
    assert run(root, site) == 0
    assert [u["name"] for u in index_of(site)["uploads"]] == ["好"]
    lines = summary.read_text(encoding="utf-8").splitlines()
    skipped = [line for line in lines if line.startswith("跳過「壞」")]
    assert skipped == ["跳過「壞」：有不成對的代理字元，不能寫進 index.json"]
    assert not (site / "模組" / "壞.zip").exists()
    assert (site / "模組" / "好.zip").is_file()
    (site / "index.json").read_bytes().decode("utf-8")
    (site / "index.html").read_bytes().decode("utf-8")


def test_unregistered_folder_is_not_published(tmp_path):
    site, index = built(tmp_path, [entry("整理桌面")],
                        {"整理桌面": {"iplot.py": IPLOT_PY}, "沒登記": {"iplot.py": IPLOT_PY}})
    assert [u["name"] for u in index["uploads"]] == ["整理桌面"]
    assert not (site / "模組" / "沒登記.zip").exists()


def test_reserved_removed_and_versionless_entries_are_not_published(tmp_path):
    entries = [entry("整理桌面"), entry("保留的", reserved=True), entry("下架的", removed=True),
               {"name": "沒版本", "owner_id": 111, "owner": "someone"}]
    modules = {e["name"]: {"iplot.py": IPLOT_PY} for e in entries}
    site, index = built(tmp_path, entries, modules)
    assert [u["name"] for u in index["uploads"]] == ["整理桌面"]
    assert sorted(p.name for p in (site / "模組").iterdir()) == ["整理桌面.zip"]


@pytest.mark.parametrize("notice", [None, "", "  \n"])
def test_notice_is_required(tmp_path, notice):
    root = make_repo(tmp_path, [entry("整理桌面")], notice=notice)
    site = tmp_path / "site"
    assert run(root, site) == 1
    assert not (site / "index.json").exists()


def test_notice_is_copied_word_for_word(tmp_path):
    text = "  第一行：沒有人審查。\n第二行 <也一樣>。\n\n"
    _, index = built(tmp_path, [entry("整理桌面")], notice=text)
    assert index["notice"] == "第一行：沒有人審查。\n第二行 <也一樣>。"


def test_module_named_notice_does_not_change_notice(tmp_path):
    _, index = built(tmp_path, [entry("notice"), entry("整理桌面")])
    assert index["notice"] == NOTICE
    assert sorted(u["name"] for u in index["uploads"]) == ["notice", "整理桌面"]


def test_warning_is_copied_only_when_a_string(tmp_path):
    entries = [entry("有", warning="被檢舉了"), entry("數字", warning=5), entry("空的", warning=""),
               entry("空值", warning=None)]
    _, index = built(tmp_path, entries)
    uploads = {u["name"]: u for u in index["uploads"]}
    assert uploads["有"]["warning"] == "被檢舉了"
    for name in ("數字", "空的", "空值"):
        assert "warning" not in uploads[name]


def test_author_is_the_current_login_with_fallbacks(tmp_path):
    api = FakeApi(users={111: "newname", 222: ApiError(502), 333: NotFound(404, "Not Found")})
    entries = [entry("甲", owner_id=111, owner="oldname"), entry("乙", owner_id=222, owner="regowner"),
               entry("丙", owner_id=333, owner="gone"), entry("丁", owner_id=111, owner="oldname")]
    _, index = built(tmp_path, entries, api=api)
    authors = {u["name"]: u["author"] for u in index["uploads"]}
    assert authors == {"甲": "newname", "乙": "regowner", "丙": "帳號已刪除", "丁": "newname"}
    assert api.requests.count(("GET", "/user/111")) == 1


def test_index_over_2mb_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "MAX_INDEX", 100)
    root = make_repo(tmp_path, [entry("整理桌面")])
    assert run(root, tmp_path / "site") == 1


def test_build_clips_description_and_icon_again(tmp_path):
    iplot = f'"""{"說" * 600}"""\nICON = "{"圖" * 20}"\n'
    _, index = built(tmp_path, [entry("整理桌面")], {"整理桌面": {"iplot.py": iplot}})
    [upload] = index["uploads"]
    assert len(upload["description"]) == 500
    assert len(upload["icon"]) == 16


def test_index_uses_the_clipped_notes(tmp_path):
    site, index = built(tmp_path, [entry("整理桌面", notes="改" * 1000)])
    assert index["uploads"][0]["notes"] == "改" * 1000
    assert len((site / "index.json").read_bytes()) < build.MAX_INDEX // 100


@pytest.mark.parametrize("name", ["C#工具", "a%20b"])
def test_names_with_hash_and_percent_install(tmp_path, name):
    site, index = built(tmp_path, [entry(name)])
    [upload] = index["uploads"]
    assert install(tmp_path, upload) == "installed"
    assert (tmp_path / "installed" / name / "iplot.py").is_file()


def test_nfd_upload_installs_after_build(tmp_path, repo, python310):
    api = FakeApi(issues=[issue(1)])
    fetch = fake_fetch({DEFAULT_ATTACHMENT: FIXTURES / "finder-nfd.zip"})
    assert receive.main([], api=api, root=repo, python310=python310, fetch=fetch) == 0
    nfc = unicodedata.normalize("NFC", "ガイド")
    site = tmp_path / "site"
    assert run(repo, site) == 0
    [upload] = index_of(site)["uploads"]
    assert upload["name"] == nfc
    assert install(tmp_path, upload) == "installed"
    assert [p.name for p in (tmp_path / "installed").iterdir()] == [nfc]


def test_self_check_failure_fails_the_build(tmp_path, monkeypatch):
    def pack(folder, name, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("x/iplot.py", IPLOT_PY)
        return path

    monkeypatch.setattr(build, "pack", pack)
    root = make_repo(tmp_path, [entry("整理桌面")])
    assert run(root, tmp_path / "site") == 1


def test_registry_with_duplicate_keys_fails_the_build(tmp_path):
    root = make_repo(tmp_path, [entry("整理桌面")])
    one = json.dumps(entry("整理桌面"), ensure_ascii=False)
    (root / "registry.json").write_text(f'{{"整理桌面": {one}, "整理桌面": {one}}}\n', encoding="utf-8")
    site = tmp_path / "site"
    assert run(root, site) == 1
    assert not (site / "index.json").exists()


def test_out_that_is_not_empty_is_refused(tmp_path):
    root = make_repo(tmp_path, [entry("整理桌面")])
    site = tmp_path / "site"
    site.mkdir()
    (site / "舊的.txt").write_text("留著", encoding="utf-8")
    assert run(root, site) == 1
    assert (site / "舊的.txt").read_text(encoding="utf-8") == "留著"
    assert not (site / "index.json").exists()


def test_build_runs_under_python_dash_i(tmp_path):
    root = make_repo(tmp_path, [entry("整理桌面")])
    shutil.copytree(TOOLS, root / "tools", ignore=shutil.ignore_patterns("__pycache__"))
    env = {k: v for k, v in os.environ.items()
           if k not in ("GH_TOKEN", "GITHUB_REPOSITORY", "GITHUB_STEP_SUMMARY")}
    done = subprocess.run([sys.executable, "-I", "tools/build.py", "site"], cwd=root, env=env,
                          capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    assert (root / "site" / "index.json").is_file()
