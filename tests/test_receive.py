import hashlib
import itertools
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import receive
import registry
import source
import zipcheck
from conftest import (
    FIXTURES,
    FakeApi,
    big5_zip,
    fake_fetch,
    form_body,
    git,
    issue,
    make_zip,
    patch_zip,
    push_from_elsewhere,
)
from gh import ApiError, RateLimited
from say import MARK_RETRY, SAY, code, refuse, short_reply

GHOST_ID = 10137  # Task 0 探針：GET /users/ghost 的 id
NOW = datetime(2026, 10, 21, 3, 4, 5, tzinfo=UTC)
COUNTER = itertools.count()
IPLOT_PY = '"""說明"""\n'
PUBLISHED = {"labels": ["上傳", "已發佈"], "state": "closed", "state_reason": "completed"}
REFUSED = {"labels": ["上傳", "沒收"], "state": "closed", "state_reason": "not_planned"}


def att(n: int) -> str:
    return f"https://github.com/user-attachments/files/{1000 + n}/default.zip"


def up(n: int, **kwargs) -> dict:
    """第 n 號：表單裡附 att(n)。"""
    kwargs.setdefault("body", form_body(att(n)))
    return issue(n, **kwargs)


def module_zip(tmp_path, name="整理桌面", iplot: str | bytes = IPLOT_PY, **extra) -> Path:
    entries = {f"{name}/iplot.py": iplot, **{f"{name}/{k}": v for k, v in extra.items()}}
    return make_zip(tmp_path / f"z{next(COUNTER)}.zip", entries)


def run(repo, api, zips, python310, **kwargs):
    kwargs.setdefault("fetch", fake_fetch(zips))
    return receive.main([], api=api, root=repo, python310=python310, now=lambda: NOW, **kwargs)


def origin_main(repo) -> str:
    return git(repo.parent / "origin.git", "rev-parse", "main").strip()


def subjects(repo) -> list[str]:
    return git(repo, "log", "--reverse", "--format=%s").splitlines()


def received(repo) -> dict:
    return registry.read_json_strict(repo / "received.json")


def seed(repo, data: dict) -> None:
    registry.write_json(repo / "registry.json", data)
    git(repo, "add", "registry.json")
    git(repo, "-c", "user.name=測試", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "registry")
    git(repo, "push", "-q", "origin", "HEAD:main")


def state(api, n) -> str:
    return next(i for i in api.issues if i["number"] == n)["state"]


def test_finder_zip_end_to_end(repo, python310):
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): FIXTURES / "finder-整理桌面.zip"}, python310) == 0
    folder = repo / "modules" / "整理桌面"
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    assert files == ["iplot.py", "小工具.py", "資料/說明.txt"]
    for gone in ("捷徑", ".history", ".DS_Store"):
        assert not (folder / gone).exists()
    assert git(repo, "rev-parse", "HEAD").strip() == origin_main(repo)
    assert "#1）" in subjects(repo)[-1]
    reply = api.comments[1][0]
    assert code("整理桌面") in reply and "3 個檔" in reply and "__MACOSX/" in reply
    assert api.patches == [(1, PUBLISHED)]


def test_several_uploads_oldest_first(repo, python310, tmp_path):
    api = FakeApi([up(5), up(3)])
    zips = {att(5): module_zip(tmp_path, "五"), att(3): module_zip(tmp_path, "三")}
    assert run(repo, api, zips, python310) == 0
    assert [s for s in subjects(repo) if s.startswith("上傳")] == ["上傳：三 0.0.1（@someone，#3）",
                                                                 "上傳：五 0.0.1（@someone，#5）"]


def test_two_accounts_same_new_name_older_wins(repo, python310, tmp_path):
    api = FakeApi([up(3, login="someone", user_id=111), up(4, login="other", user_id=222)])
    zips = {att(3): module_zip(tmp_path), att(4): module_zip(tmp_path)}
    assert run(repo, api, zips, python310) == 0
    assert api.patches == [(3, PUBLISHED), (4, REFUSED)]
    assert api.comments[4] == [refuse("taken", name="整理桌面", owner="someone").text]
    assert code("someone") in api.comments[4][0]


def broken_zip(tmp_path, kind):
    if kind == "bad_utf8_names":
        return big5_zip(tmp_path / "big5.zip")
    if kind == "deep_iplot":
        return module_zip(tmp_path, "壞", "x = " + "not " * 100_000 + "1")
    path = make_zip(tmp_path / "bad.zip", {"壞/iplot.py": "x" * 1100})
    if kind == "encrypted":
        return patch_zip(path, encrypted=True)
    if kind == "deflate64":
        return patch_zip(path, method=9)
    return patch_zip(path, first_data_byte=0xFF)


BROKEN_TEXT = {
    "encrypted": refuse("broken", kind="RuntimeError").text,
    "deflate64": refuse("broken", kind="NotImplementedError").text,
    "bad_utf8_names": SAY["names_not_utf8"],
    "broken_deflate": refuse("broken", kind="zlib.error").text,
    "deep_iplot": SAY["too_complex"],
}


@pytest.mark.parametrize("broken", ["encrypted", "deflate64", "bad_utf8_names", "broken_deflate", "deep_iplot"])
def test_broken_first_does_not_block_the_next(repo, broken, python310, tmp_path):
    api = FakeApi([up(1), up(2)])
    zips = {att(1): broken_zip(tmp_path, broken), att(2): module_zip(tmp_path, "好")}
    assert run(repo, api, zips, python310) == 0
    assert api.comments[1] == [BROKEN_TEXT[broken]]
    assert api.patches == [(1, REFUSED), (2, PUBLISHED)]
    assert state(api, 1) == "closed"
    assert "1" not in received(repo) and "2" in received(repo)
    assert not any("#1）" in s for s in subjects(repo))
    assert sorted(p.name for p in (repo / "modules").iterdir()) == ["好"]
    assert git(repo, "status", "--porcelain") == ""


def stuck_once(repo, python310, tmp_path, monkeypatch) -> FakeApi:
    def explode(*args, **kwargs):
        raise KeyError("意外")

    monkeypatch.setattr(zipcheck, "inspect", explode)
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 0
    assert api.comments[1] == [SAY["stuck"]]
    assert api.patches == [(1, {"labels": ["卡住"]})]
    assert state(api, 1) == "open"
    assert git(repo, "status", "--porcelain") == ""
    return api


def test_unexpected_exception_marks_stuck(repo, python310, tmp_path, monkeypatch):
    stuck_once(repo, python310, tmp_path, monkeypatch)


def test_stuck_is_not_retried(repo, python310, tmp_path, monkeypatch):
    api = stuck_once(repo, python310, tmp_path, monkeypatch)
    monkeypatch.undo()
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 0
    assert api.comments[1] == [SAY["stuck"]]
    assert len(api.patches) == 1


def test_disk_error_while_writing_in_says_not_writable(repo, python310, tmp_path, monkeypatch):
    real_place = receive.place

    def place(root, unpacked):
        if unpacked.name == "一":
            raise OSError(28, "No space left on device")
        return real_place(root, unpacked)

    monkeypatch.setattr(receive, "place", place)
    api = FakeApi([up(1), up(2)])
    zips = {att(1): module_zip(tmp_path, "一"), att(2): module_zip(tmp_path, "二")}
    assert run(repo, api, zips, python310) == 0
    assert api.comments[1] == [refuse("not_writable").text]
    assert api.patches == [(1, REFUSED), (2, PUBLISHED)]
    assert state(api, 1) == "closed"
    assert "1" not in received(repo) and "2" in received(repo)
    assert not (repo / "modules" / "一").exists()
    assert not any("#1）" in s for s in subjects(repo))
    assert git(repo, "status", "--porcelain") == ""


def test_behind_stops_without_reply(repo, python310, tmp_path, monkeypatch):
    real = receive.push
    before = git(repo, "rev-parse", "HEAD").strip()

    def push_after_someone_else(root):
        push_from_elsewhere(root, lambda other: (other / "notice.txt").write_text("新\n", encoding="utf-8"))
        return real(root)

    monkeypatch.setattr(receive, "push", push_after_someone_else)
    api = FakeApi([up(1), up(2)])
    fetch = fake_fetch({att(1): module_zip(tmp_path, "一"), att(2): module_zip(tmp_path, "二")})
    assert run(repo, api, {}, python310, fetch=fetch) == 0
    assert api.comments == {} and api.patches == []
    head = git(repo, "rev-parse", "HEAD").strip()
    assert head == git(repo, "rev-parse", "origin/main").strip() == before
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / "modules" / "一").exists()
    assert fetch.calls == [att(1)]


def test_owner_changed_before_push_is_judged_by_the_new_registry(repo, python310, tmp_path, monkeypatch):
    seed(repo, {registry.key("整理桌面"): {"name": "整理桌面", "owner_id": 222, "owner": "someone",
                                         "version": "0.0.1", "notes": "", "issue": 1, "updated": "2026-10-01"}})
    real = receive.push

    def handed_over(other):
        data = registry.read_json_strict(other / "registry.json")
        data[registry.key("整理桌面")].update(owner_id=333, owner="boss")
        registry.write_json(other / "registry.json", data)

    def push_after_handover(root):
        push_from_elsewhere(root, handed_over)
        return real(root)

    monkeypatch.setattr(receive, "push", push_after_handover)
    api = FakeApi([up(7)])
    zips = {att(7): module_zip(tmp_path)}
    assert run(repo, api, zips, python310) == 0
    assert api.comments == {} and api.patches == []

    monkeypatch.setattr(receive, "push", real)
    git(repo, "fetch", "-q", "origin")
    git(repo, "reset", "-q", "--hard", "origin/main")
    assert run(repo, api, zips, python310) == 0
    assert api.comments[7] == [refuse("taken", name="整理桌面", owner="boss").text]
    assert api.patches == [(7, REFUSED)]


def test_push_blocked_refuses_and_goes_on(repo, python310, tmp_path):
    hook = repo.parent / "origin.git" / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nwhile read old new ref; do\n"
                    "  if git log -1 --format=%B \"$new\" | grep -q '#1）'; then\n"
                    "    echo 'GH013: Repository rule violations found'\n    exit 1\n  fi\ndone\nexit 0\n",
                    encoding="utf-8")
    hook.chmod(0o755)
    api = FakeApi([up(1), up(2)])
    zips = {att(1): module_zip(tmp_path, "一"), att(2): module_zip(tmp_path, "二")}
    assert run(repo, api, zips, python310) == 0
    assert api.patches == [(1, REFUSED), (2, PUBLISHED)]
    assert "GH013" in api.comments[1][0]
    assert api.comments[1][0].startswith("推不上去（")
    assert "1" not in received(repo) and "2" in received(repo)
    assert not (repo / "modules" / "一").exists()
    assert git(repo, "rev-parse", "HEAD").strip() == origin_main(repo)


def test_unreachable_says_retry_once(repo, python310, tmp_path):
    git(repo, "remote", "set-url", "origin", str(tmp_path / "沒有這個.git"))
    api = FakeApi([up(1)])
    zips = {att(1): module_zip(tmp_path)}
    assert run(repo, api, zips, python310) == 1
    assert run(repo, api, zips, python310) == 1
    assert api.comments[1] == [SAY["retry"] + "\n\n" + MARK_RETRY]
    assert api.patches == [] and state(api, 1) == "open"
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / "modules" / "整理桌面").exists()


def test_reply_failure_after_push_only_finishes_next_time(repo, python310, tmp_path):
    api = FakeApi([up(1)], fail={"comment": [ApiError(502), ApiError(502)]})
    zips = {att(1): module_zip(tmp_path)}
    assert run(repo, api, zips, python310) == 0
    pushed = origin_main(repo)
    assert git(repo, "rev-parse", "HEAD").strip() == pushed
    assert "1" in received(repo)
    assert api.comments == {} and api.patches == [] and state(api, 1) == "open"

    assert run(repo, api, zips, python310) == 0
    assert origin_main(repo) == pushed
    assert api.comments[1] == [short_reply("整理桌面", "0.0.1", None)]
    assert api.patches == [(1, PUBLISHED)]


def test_reply_posted_but_patch_failed_is_not_posted_twice(repo, python310, tmp_path):
    api = FakeApi([up(1)], fail={"patch": [ApiError(502)]})
    zips = {att(1): module_zip(tmp_path)}
    assert run(repo, api, zips, python310) == 0
    assert len(api.comments[1]) == 1 and api.patches == []
    assert run(repo, api, zips, python310) == 0
    assert len(api.comments[1]) == 1
    assert api.patches == [(1, PUBLISHED)]


def test_rate_limit_leaves_the_rest_for_next_time(repo, python310, tmp_path):
    api = FakeApi([up(1), up(2), up(3)], fail={"comment": [RateLimited(120)]})
    zips = {att(1): module_zip(tmp_path, "一"), att(2): module_zip(tmp_path, "二"), att(3): module_zip(tmp_path, "三")}
    assert run(repo, api, zips, python310) == 0
    assert set(received(repo)) == {"1"}
    assert api.comments == {} and api.patches == []
    assert [state(api, n) for n in (1, 2, 3)] == ["open"] * 3

    assert run(repo, api, zips, python310) == 0
    assert api.comments[1] == [short_reply("一", "0.0.1", None)]
    assert api.comments[2][0].startswith("收到了：") and api.comments[3][0].startswith("收到了：")
    assert api.patches == [(1, PUBLISHED), (2, PUBLISHED), (3, PUBLISHED)]
    assert set(received(repo)) == {"1", "2", "3"}
    assert len([s for s in subjects(repo) if s.startswith("上傳")]) == 3


def test_one_upload_writes_twice(repo, python310, tmp_path):
    api = FakeApi([up(1), up(2, body=form_body(None))], labels={"上傳", "已發佈", "沒收", "卡住"})
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 0
    assert api.comments[2] == [SAY["no_zip"]]
    assert api.writes == 4


def test_at_most_30_per_run(repo, python310):
    api = FakeApi([issue(n, body=form_body(None)) for n in range(1, 32)])
    assert run(repo, api, {}, python310) == 0
    assert set(api.comments) == set(range(1, 31))
    assert [n for n, _ in api.patches] == list(range(1, 31))
    assert state(api, 31) == "open"


@pytest.mark.parametrize("user", [{"type": "Organization"}, {"type": "Bot"}, {"login": "ghost"}, {"id": GHOST_ID}])
def test_not_user_and_ghost_are_refused(repo, user, python310, tmp_path):
    one = up(1)
    one["user"].update(user)
    api = FakeApi([one])
    before = (repo / "registry.json").read_bytes()
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 0
    assert api.comments[1] == [SAY["not_user" if "type" in user else "gone"]]
    assert api.patches == [(1, REFUSED)]
    assert (repo / "registry.json").read_bytes() == before


def test_constants():
    assert (receive.MAX_PER_RUN, receive.GHOST_LOGIN, receive.GHOST_ID) == (30, "ghost", GHOST_ID)


def test_kind_of_names_the_class():
    import zipfile
    import zlib

    assert receive.kind_of(RuntimeError()) == "RuntimeError"
    assert receive.kind_of(zlib.error()) == "zlib.error"
    assert receive.kind_of(zipfile.BadZipFile()) == "zipfile.BadZipFile"


def test_own_exceptions_are_not_known_zip_errors():
    for exc in (receive.GitFailed, RateLimited, source.Python310Missing, receive.NotWritable):
        assert not issubclass(exc, receive.KNOWN)


def test_missing_user_is_gone():
    assert receive.who_refusal(None).key == "gone"
    assert receive.who_refusal({"login": "a", "id": 5, "type": "User"}) is None


def test_box_unchecked_after_submit_is_refused(repo, python310, tmp_path):
    api = FakeApi([up(1, body=form_body(att(1), agreed=False))])
    fetch = fake_fetch({att(1): module_zip(tmp_path)})
    assert run(repo, api, {}, python310, fetch=fetch) == 0
    assert api.comments[1] == [SAY["not_agreed"]]
    assert fetch.calls == []


@pytest.mark.parametrize("src, key", [("-" * 100_000, "too_complex"),
                                      (b"# -*- coding: latin-1 -*-\nx = '\xe9'\n", "not_utf8"),
                                      ("x = 1\x00\n", "not_utf8")], ids=["dashes", "latin1", "nul"])
def test_iplot_errors_do_not_block_the_next(repo, src, key, python310, tmp_path):
    api = FakeApi([up(1), up(2)])
    zips = {att(1): module_zip(tmp_path, "壞", src), att(2): module_zip(tmp_path, "好")}
    assert run(repo, api, zips, python310) == 0
    assert api.comments[1] == [SAY[key]]
    assert api.patches == [(1, REFUSED), (2, PUBLISHED)]


def test_lone_surrogate_title_is_refused_and_does_not_block_the_next(repo, python310, tmp_path):
    src = '"""說明"""\nTITLE = "\\ud800 "\n'  # 檔裡是 ASCII 的反斜線跳脫：解析出來的 TITLE 有落單的代理字元
    api = FakeApi([up(1), up(2)])
    zips = {att(1): module_zip(tmp_path, "壞", src), att(2): module_zip(tmp_path, "好")}
    assert run(repo, api, zips, python310) == 0
    assert api.comments[1] == [refuse("title_taken", title="\ud800 ").text]
    assert api.patches == [(1, REFUSED), (2, PUBLISHED)]
    assert sorted(p.name for p in (repo / "modules").iterdir()) == ["好"]


def test_missing_python310_stops_before_touching_any_issue(repo, monkeypatch):
    monkeypatch.setattr(source, "find_python310", lambda: None)
    api = FakeApi([up(1)])
    assert receive.main([], api=api, root=repo, python310=None, fetch=fake_fetch({}), now=lambda: NOW) == 1
    assert api.requests == []


def test_duplicate_keys_in_registry_stop_the_run(repo, python310, tmp_path):
    (repo / "registry.json").write_text('{"a": {"name": "a"}, "a": {"name": "a"}}\n', encoding="utf-8")
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path)}, python310) == 1
    assert api.requests == []


def test_may_publish_gets_the_whole_upload(repo, python310, tmp_path, monkeypatch):
    entry = {"name": "整理桌面", "owner_id": 222, "owner": "someone", "version": "0.1.0", "notes": "",
             "issue": 1, "updated": "2026-10-01"}
    seed(repo, {registry.key("整理桌面"): entry})
    seen = []

    def held(upload):
        seen.append(upload)
        return False, "這一份要等審查"

    monkeypatch.setattr(receive, "may_publish", held)
    zip_path = module_zip(tmp_path, **{"資料/a.txt": "內容"})
    api = FakeApi([up(7, body=form_body(att(7), notes="改了一點"))])
    assert run(repo, api, {att(7): zip_path}, python310) == 0
    assert api.comments[7] == [refuse("held", reason="這一份要等審查").text]
    assert api.patches == [(7, REFUSED)]
    [upload] = seen
    assert (upload.issue, upload.user_id, upload.login) == (7, 222, "someone")
    assert (upload.name, upload.key, upload.version, upload.notes) == ("整理桌面", registry.key("整理桌面"), "0.1.1",
                                                                       "改了一點")
    expected = {"iplot.py": IPLOT_PY.encode(), "資料/a.txt": "內容".encode()}
    assert [f.path for f in upload.files] == sorted(expected)
    for f in upload.files:
        assert f.size == len(expected[f.path]) and f.sha256 == hashlib.sha256(expected[f.path]).hexdigest()
    assert upload.attachment_url == att(7)
    assert upload.zip_sha256 == hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert upload.entry == entry
    assert "7" not in received(repo)


def test_labels_are_created_once(repo, python310):
    api = FakeApi()
    assert run(repo, api, {}, python310) == 0
    posted = [path for method, path in api.requests if method == "POST"]
    assert posted == [f"/repos/{api.repo}/labels"] * 4
    assert api.labels == {"上傳", "已發佈", "沒收", "卡住"}
    api.requests.clear()
    assert run(repo, api, {}, python310) == 0
    assert [m for m, _ in api.requests if m == "POST"] == []


def test_received_json_is_the_record(repo, python310, tmp_path):
    api = FakeApi([up(9)])
    assert run(repo, api, {att(9): module_zip(tmp_path)}, python310) == 0
    record = received(repo)["9"]
    assert set(record) == {"name", "version", "owner_id", "at"}
    assert (record["name"], record["version"], record["owner_id"]) == ("整理桌面", "0.0.1", 222)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", record["at"]) and record["at"] == "2026-10-21T03:04:05Z"


def test_60mb_changelog_keeps_registry_small(repo, python310, tmp_path):
    changelog = "## [1.0.0] - 2026-10-21\n\n" + "a" * (60 * 1024 * 1024) + "\n"
    api = FakeApi([up(1)])
    assert run(repo, api, {att(1): module_zip(tmp_path, **{"CHANGELOG.md": changelog})}, python310) == 0
    assert api.patches == [(1, PUBLISHED)]
    assert (repo / "registry.json").stat().st_size < 10 * 1024
    data = registry.read_json_strict(repo / "registry.json")
    assert len(data[registry.key("整理桌面")]["notes"]) == 1000


def test_cli_runs_under_python_dash_i(repo):
    env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_REPOSITORY", "GITHUB_API_URL")}
    done = subprocess.run([sys.executable, "-I", str(receive.ROOT / "tools" / "receive.py")], cwd=repo, env=env,
                          capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 1
    assert "ModuleNotFoundError" not in done.stderr
