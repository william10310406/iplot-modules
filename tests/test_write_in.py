import itertools
import subprocess
from datetime import UTC, datetime

import pytest
import receive
import registry
import zipcheck
from conftest import git, make_zip, push_from_elsewhere
from receive import NotWritable, Pushed, Upload

NOW = datetime(2026, 10, 21, 3, 4, 5, tzinfo=UTC)
COUNTER = itertools.count()


def unpack(tmp_path, entries, name="整理桌面"):
    zip_path = make_zip(tmp_path / f"u{next(COUNTER)}.zip", {f"{name}/{k}": v for k, v in entries.items()})
    unpacked = zipcheck.inspect(zip_path, tmp_path / f"staging{next(COUNTER)}")
    assert isinstance(unpacked, zipcheck.Unpacked)
    return unpacked


def upload_for(unpacked, version="0.0.1", issue=12):
    return Upload(issue=issue, user_id=222, login="someone", name=unpacked.name, key=registry.key(unpacked.name),
                  version=version, notes="說明", files=unpacked.files, attachment_url="https://example.invalid/a.zip",
                  zip_sha256="0" * 64, entry=None)


def load(root):
    return (registry.read_json_strict(root / "registry.json"), registry.read_json_strict(root / "received.json"))


def land(repo, tmp_path, entries, version="0.0.1", name="整理桌面"):
    """收下一份：write_in 加 commit。回 (unpacked, upload)。"""
    unpacked = unpack(tmp_path, entries, name)
    upload = upload_for(unpacked, version)
    reg, rec = load(repo)
    receive.write_in(repo, unpacked, upload, reg, rec, NOW)
    receive.commit(repo, upload)
    return unpacked, upload


def tracked(repo, name="整理桌面"):
    return git(repo, "ls-files", "-z", f"modules/{name}").split("\0")[:-1]


def test_write_in_commits_exactly_the_received_files(repo, tmp_path):
    land(repo, tmp_path, {"iplot.py": "x" * 1100, "sub/a.txt": "a"})
    assert tracked(repo) == ["modules/整理桌面/iplot.py", "modules/整理桌面/sub/a.txt"]
    stat = git(repo, "-c", "core.quotepath=off", "show", "--stat", "--format=", "HEAD")
    assert "modules/整理桌面/" in stat and "registry.json" in stat and "received.json" in stat


def test_update_removes_files_the_new_version_dropped(repo, tmp_path):
    land(repo, tmp_path, {"iplot.py": "x" * 1100, "a.py": "1", "b.py": "2"})
    unpacked, _ = land(repo, tmp_path, {"iplot.py": "x" * 1100, "a.py": "1"}, version="0.0.2")
    assert tracked(repo) == ["modules/整理桌面/a.py", "modules/整理桌面/iplot.py"]
    assert not (repo / "modules" / "整理桌面" / "b.py").exists()
    assert receive.index_problems(repo, "整理桌面", unpacked.files, unpacked.folder.parent / "整理桌面") == []


def test_root_gitignore_does_not_drop_uploaded_files(repo, tmp_path):
    land(repo, tmp_path, {"iplot.py": "x" * 1100, "debug.log": "log"})
    assert "modules/整理桌面/debug.log" in tracked(repo)


def test_autocrlf_in_config_does_not_change_bytes(repo, tmp_path):
    git(repo, "config", "core.autocrlf", "true")
    crlf, png = b"a = 1\r\nb = 2\r\n" + b"x" * 1100, b"\x89PNG\r\n\x1a\n\x00\r\n"
    land(repo, tmp_path, {"iplot.py": crlf, "pic.png": png})
    for rel, data in (("iplot.py", crlf), ("pic.png", png)):
        shown = subprocess.run(["git", "show", f"HEAD:modules/整理桌面/{rel}"], cwd=repo, capture_output=True,
                               check=True).stdout
        assert shown == data


def test_skipped_git_files_never_reach_the_index(repo, tmp_path):
    entries = {"iplot.py": "x" * 1100, ".gitignore": "*", ".gitattributes": "* text eol=crlf working-tree-encoding=UTF-16",
               "sub/.git": "gitdir: /elsewhere", "sub/x.py": "y"}
    land(repo, tmp_path, entries, name="m")
    assert tracked(repo, "m") == ["modules/m/iplot.py", "modules/m/sub/x.py"]
    modes = {line.split()[0] for line in git(repo, "ls-files", "-s", "modules/m").splitlines()}
    assert modes == {"100644"}


def test_index_problems_catches_a_gitlink(repo, tmp_path):
    unpacked = unpack(tmp_path, {"iplot.py": "x" * 1100}, "m")
    reg, rec = load(repo)
    receive.write_in(repo, unpacked, upload_for(unpacked), reg, rec, NOW)
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{'a' * 40},modules/m/sub")
    problems = receive.index_problems(repo, "m", unpacked.files, unpacked.folder)
    assert len(problems) == 1 and "160000" in problems[0]


def test_index_problems_catches_a_changed_blob(repo, tmp_path):
    unpacked = unpack(tmp_path, {"iplot.py": "x" * 1100}, "m")
    reg, rec = load(repo)
    receive.write_in(repo, unpacked, upload_for(unpacked), reg, rec, NOW)
    (unpacked.folder / "iplot.py").write_text("changed", encoding="utf-8")
    problems = receive.index_problems(repo, "m", unpacked.files, unpacked.folder)
    assert len(problems) == 1 and "modules/m/iplot.py" in problems[0]


def test_index_problems_catches_missing_and_extra(repo, tmp_path):
    unpacked = unpack(tmp_path, {"iplot.py": "x" * 1100, "a.py": "1"}, "m")
    reg, rec = load(repo)
    receive.write_in(repo, unpacked, upload_for(unpacked), reg, rec, NOW)
    git(repo, "rm", "-q", "--cached", "modules/m/a.py")
    git(repo, "update-index", "--add", "--cacheinfo", f"100644,{'b' * 40},modules/m/zzz.py")
    problems = receive.index_problems(repo, "m", unpacked.files, unpacked.folder)
    assert len(problems) == 2
    assert any("a.py" in p for p in problems) and any("zzz.py" in p for p in problems)


def test_git_add_failure_is_not_writable(repo, tmp_path, monkeypatch):
    real = receive.run_git

    def failing(root, *args, **kwargs):
        if "add" in args:
            raise receive.GitFailed(args, 1, b"boom")
        return real(root, *args, **kwargs)

    monkeypatch.setattr(receive, "run_git", failing)
    unpacked = unpack(tmp_path, {"iplot.py": "x" * 1100}, "m")
    reg, rec = load(repo)
    with pytest.raises(NotWritable):
        receive.write_in(repo, unpacked, upload_for(unpacked), reg, rec, NOW)


def test_registry_and_received_are_written_with_the_commit(repo, tmp_path):
    land(repo, tmp_path, {"iplot.py": "x" * 1100})
    reg, rec = load(repo)
    assert rec["12"] == {"name": "整理桌面", "version": "0.0.1", "owner_id": 222, "at": "2026-10-21T03:04:05Z"}
    assert reg[registry.key("整理桌面")]["updated"] == "2026-10-21"
    assert git(repo, "status", "--porcelain") == ""
    assert (repo / "registry.json").read_text(encoding="utf-8").endswith("}\n")


def test_commit_message_and_co_author(repo, tmp_path):
    _, upload = land(repo, tmp_path, {"iplot.py": "x" * 1100})
    expected = "上傳：整理桌面 0.0.1（@someone，#12）\n\nCo-authored-by: someone <222+someone@users.noreply.github.com>\n"
    assert receive.commit_message(upload) == expected
    assert git(repo, "log", "-1", "--format=%B").rstrip("\n") + "\n" == expected
    assert git(repo, "log", "-1", "--format=%an <%ae>") == f"{receive.BOT_NAME} <{receive.BOT_EMAIL}>\n"


def test_push_ok(repo, tmp_path):
    land(repo, tmp_path, {"iplot.py": "x" * 1100})
    assert receive.push(repo).kind == "ok"
    assert git(repo, "rev-parse", "HEAD") == git(repo.parent / "origin.git", "rev-parse", "main")


def test_push_behind(repo, tmp_path):
    land(repo, tmp_path, {"iplot.py": "x" * 1100})
    push_from_elsewhere(repo, lambda other: (other / "notice.txt").write_text("新\n", encoding="utf-8"))
    assert receive.push(repo).kind == "behind"


def test_push_blocked_gives_the_remote_reason(repo, tmp_path):
    hook = repo.parent / "origin.git" / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'GH013: Repository rule violations found'\n"
                    "echo 'Push cannot contain secrets'\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    land(repo, tmp_path, {"iplot.py": "x" * 1100})
    result = receive.push(repo)
    assert result.kind == "blocked"
    assert "GH013" in result.reason and "Push cannot contain secrets" in result.reason
    assert "remote:" not in result.reason and len(result.reason) <= 500


def test_push_unreachable(repo, tmp_path):
    land(repo, tmp_path, {"iplot.py": "x" * 1100})
    git(repo, "remote", "set-url", "origin", str(tmp_path / "沒有這個.git"))
    result = receive.push(repo)
    assert isinstance(result, Pushed) and result.kind == "unreachable" and result.reason


def test_rollback_goes_back_to_the_last_push(repo, tmp_path):
    land(repo, tmp_path, {"iplot.py": "x" * 1100})
    receive.rollback(repo, "整理桌面")
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main")
    assert not (repo / "modules" / "整理桌面").exists()


def test_rollback_removes_untracked_leftovers_of_that_module(repo, tmp_path):
    unpacked = unpack(tmp_path, {"iplot.py": "x" * 1100}, "m")
    reg, rec = load(repo)
    receive.write_in(repo, unpacked, upload_for(unpacked), reg, rec, NOW)
    (repo / "modules" / "m" / "x.log").write_text("ignored", encoding="utf-8")
    receive.rollback(repo, "m")
    assert not (repo / "modules" / "m").exists()


def test_runs_with_ignorecase_false(repo):
    assert git(repo, "config", "core.ignorecase").strip() == "false"


def test_run_git_checks_the_exit_code(repo):
    with pytest.raises(receive.GitFailed) as err:
        receive.run_git(repo, "rev-parse", "--verify", "沒有這個")
    assert err.value.returncode != 0
    assert receive.run_git(repo, "rev-parse", "--verify", "沒有這個", check=False).returncode != 0


def disk_full(*args, **kwargs):
    raise OSError(28, "No space left on device")


def write_in_with(repo, tmp_path):
    unpacked = unpack(tmp_path, {"iplot.py": "x" * 1100})
    reg, rec = load(repo)
    receive.write_in(repo, unpacked, upload_for(unpacked), reg, rec, NOW)


def test_place_oserror_is_not_writable(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(receive, "place", disk_full)
    with pytest.raises(NotWritable):
        write_in_with(repo, tmp_path)


def test_write_json_oserror_is_not_writable(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(receive.registry, "write_json", disk_full)
    with pytest.raises(NotWritable):
        write_in_with(repo, tmp_path)


def test_index_problems_decode_error_is_not_writable(repo, tmp_path, monkeypatch):
    def undecodable(*args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(receive, "index_problems", undecodable)
    with pytest.raises(NotWritable):
        write_in_with(repo, tmp_path)
