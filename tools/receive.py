"""機器人的後半：把收下的上傳寫進 repo、逐檔核對 index、commit、push、退回。

git 只從 run_git 叫：list argv、不經 shell、LC_ALL=C、看結束碼。上傳的東西只讀不執行。
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

import registry  # noqa: E402
import zipcheck  # noqa: E402
from zipcheck import File, Unpacked  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BOT_NAME = "iplot-modules 機器人"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
GIT_ENV = {"LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
FILE_MODE = "100644"
MAX_REASON = 500


class GitFailed(Exception):
    def __init__(self, args: Sequence[str], returncode: int, stderr: bytes):
        super().__init__(list(args), returncode, stderr)
        self.args_used = list(args)
        self.returncode = returncode
        self.stderr = stderr


class NotWritable(Exception):
    pass


def run_git(root: Path, *args: str, input: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    done = subprocess.run(["git", *args], cwd=root, env={**os.environ, **GIT_ENV}, input=input, capture_output=True)
    if check and done.returncode != 0:
        raise GitFailed(args, done.returncode, done.stderr)
    return done


@dataclass(frozen=True)
class Upload:
    issue: int
    user_id: int
    login: str
    name: str
    key: str
    version: str
    notes: str
    files: tuple[zipcheck.File, ...]
    attachment_url: str
    zip_sha256: str
    entry: dict | None


def place(root: Path, unpacked: Unpacked) -> None:
    target = root / "modules" / unpacked.name
    if target.exists():
        shutil.rmtree(target)
    for f in unpacked.files:
        dest = target / f.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(unpacked.folder / f.path, dest)


def index_problems(root: Path, name: str, files: Sequence[File], staged: Path) -> list[str]:
    """index 裡 modules/<名稱>/ 底下的每一筆，跟收下的檔一模一樣；不一樣的各一條。"""
    prefix = f"modules/{name}/"
    wanted = {prefix + f.path: staged / f.path for f in files}
    listing = run_git(root, "ls-files", "-s", "-z", "--", prefix).stdout.decode("utf-8")
    actual: dict[str, tuple[str, str]] = {}
    for record in listing.split("\0"):
        if record:
            meta, path = record.split("\t", 1)
            mode, blob, _stage = meta.split(" ")
            actual[path] = (mode, blob)
    expected_blobs: dict[str, str] = {}
    if wanted:
        paths = list(wanted.values())
        out = run_git(root, "hash-object", "--no-filters", "--stdin-paths",
                      input="".join(f"{p}\n" for p in paths).encode("utf-8")).stdout.decode("ascii").split()
        expected_blobs = dict(zip(wanted, out, strict=True))
    problems = []
    for path in sorted(wanted.keys() - actual.keys()):
        problems.append(f"index 少了 {path}")
    for path in sorted(actual):
        mode, blob = actual[path]
        if path not in wanted:
            problems.append(f"index 多了 {path}（模式 {mode}）")
        elif mode != FILE_MODE:
            problems.append(f"{path} 的模式是 {mode}，不是 {FILE_MODE}")
        elif blob != expected_blobs[path]:
            problems.append(f"{path} 的內容跟收下的不一樣")
    return problems


def write_in(root: Path, unpacked: Unpacked, upload: Upload, registry_data: dict, received: dict,
             now: datetime) -> None:
    name = unpacked.name
    place(root, unpacked)
    registry.record(registry_data, name, upload.user_id, upload.login, upload.version, upload.notes, upload.issue,
                    today=now.strftime("%Y-%m-%d"))
    received[str(upload.issue)] = {"name": name, "version": upload.version, "owner_id": upload.user_id,
                                   "at": now.strftime(registry.AT)}
    registry.write_json(root / "registry.json", registry_data)
    registry.write_json(root / "received.json", received)
    try:
        run_git(root, "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", "add", "-f", "--",
                f"modules/{name}", "registry.json", "received.json")
    except GitFailed as exc:
        raise NotWritable(str(exc)) from exc
    problems = index_problems(root, name, unpacked.files, unpacked.folder)
    if problems:
        raise NotWritable("；".join(problems))


def commit_message(upload: Upload) -> str:
    return (f"上傳：{upload.name} {upload.version}（@{upload.login}，#{upload.issue}）\n\n"
            f"Co-authored-by: {upload.login} <{upload.user_id}+{upload.login}@users.noreply.github.com>\n")


def commit(root: Path, upload: Upload) -> None:
    run_git(root, "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}", "commit", "-q", "-F", "-",
            input=commit_message(upload).encode("utf-8"))


@dataclass(frozen=True)
class Pushed:
    kind: Literal["ok", "behind", "blocked", "unreachable"]
    reason: str


def push(root: Path) -> Pushed:
    done = run_git(root, "push", "origin", "HEAD:main", check=False)
    if done.returncode == 0:
        return Pushed("ok", "")
    lines = done.stderr.decode("utf-8", errors="replace").splitlines()
    if any("[remote rejected]" in line for line in lines):
        remote = [line[len("remote:"):].strip() for line in lines if line.startswith("remote:")]
        remote = [r for r in remote if r]
        if remote:
            reason = "／".join(remote)
        else:
            rejected = next(line for line in lines if "[remote rejected]" in line)
            reason = rejected[rejected.rfind("(") + 1:].rstrip(") \t") if "(" in rejected else rejected.strip()
        return Pushed("blocked", reason[:MAX_REASON])
    if any("[rejected]" in line for line in lines):
        return Pushed("behind", next(line for line in lines if "[rejected]" in line).strip())
    tail = [line.strip() for line in lines if line.strip()]
    return Pushed("unreachable", tail[-1] if tail else f"git push 結束碼 {done.returncode}")


def rollback(root: Path, name: str | None) -> None:
    run_git(root, "reset", "-q", "--hard", "origin/main")
    if name is not None:
        run_git(root, "clean", "-ffdxq", "--", f"modules/{name}/")
