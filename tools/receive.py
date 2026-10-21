"""機器人：收用表單上傳的模組（設計第 5.2、5.3 節）。

一份一份收：每一份從下載到 commit 包在自己的 try 裡，壞的不擋別人；push 成功才回覆、貼標籤、關 issue。
git 只從 run_git 叫：list argv、不經 shell、LC_ALL=C、看結束碼。上傳的東西只讀不執行。
跑法：python -I tools/receive.py（要 GH_TOKEN、GITHUB_REPOSITORY；GITHUB_API_URL 有就用）。
"""

import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import zipfile
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh  # noqa: E402
import registry  # noqa: E402
import source  # noqa: E402
import zipcheck  # noqa: E402
from say import MARK_RECEIVED, MARK_RETRY, SAY, Refusal, received_reply, refuse, short_reply  # noqa: E402
from zipcheck import File, Unpacked  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BOT_NAME = "iplot-modules 機器人"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
GIT_ENV = {"LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
FILE_MODE = "100644"
MAX_REASON = 500
MAX_PER_RUN = 30
GHOST_LOGIN = "ghost"
GHOST_ID = 10137  # Task 0 探針：GET /users/ghost 的 id（type 是 User）
# 打開、讀 zip 會丟的已知例外：回「zip 打不開或壞了」。機器人自己的例外（GitFailed、RateLimited、
# Python310Missing、NotWritable）只繼承 Exception，不會被這裡接走；DuplicateKey 是 ValueError，
# 所以讀 registry.json、received.json 一律在每一份的 try 外面。
KNOWN = (zipfile.BadZipFile, RuntimeError, NotImplementedError, zlib.error, EOFError, ValueError,
         UnicodeDecodeError, OSError)


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


def may_publish(upload: Upload) -> tuple[bool, str]:
    """留給審查的位置（設計第 8 節第 1 條）：這一版一律可以。

    要改成「先審再發」不是只改這一個函式，還要：
    ①receive 跳過帶「待審」標籤的 issue（不然每次都重收、重回一句）；
    ②等審查的名字先在 registry.json 記成 {"pending": issue}，同名的回「這個名字有人在等審查」；
    ③核准由有 triage 權限的人貼「可以發佈」，may_publish 看這個標籤。
    """
    return True, ""


def who_refusal(user: dict | None) -> Refusal | None:
    if user is None:
        return refuse("gone")
    if user.get("type") != "User":
        return refuse("not_user")
    if user.get("login") == GHOST_LOGIN or user.get("id") == GHOST_ID:
        return refuse("gone")
    return None


def kind_of(exc: BaseException) -> str:
    cls = type(exc)
    return cls.__qualname__ if cls.__module__ == "builtins" else f"{cls.__module__}.{cls.__qualname__}"


@dataclass(frozen=True)
class Accepted:
    upload: Upload
    unpacked: Unpacked
    remarks: tuple[str, ...]


def examine(issue: dict, form: gh.Form, zip_path: Path, zip_sha256: str, root: Path, registry_data: dict,
            received: dict, now: datetime, python310: str, staging: Path) -> Accepted | Refusal:
    """設計第 5.2 節第 4–9 步，照順序；哪一步不過就回那一句。"""
    unpacked = zipcheck.inspect(zip_path, staging)
    if isinstance(unpacked, Refusal):
        return unpacked
    user_id, login, name = issue["user"]["id"], issue["user"]["login"], unpacked.name
    if refusal := registry.check_name(name, user_id, registry_data):
        return refusal
    if refusal := registry.owner_refusal(name, user_id, registry_data):
        return refusal
    k = registry.key(name)
    if refusal := registry.limit_refusal(user_id, k not in registry_data, sum(f.size for f in unpacked.files),
                                         registry_data, received, registry.modules_size(root), now):
        return refusal
    checked = source.check_source(unpacked.folder, name, user_id, registry_data, python310)
    if isinstance(checked, Refusal):
        return checked
    entry = registry_data.get(k)
    version = registry.version_for(entry, {f.path for f in unpacked.files}, unpacked.folder, form.notes)
    if isinstance(version, Refusal):
        return version
    upload = Upload(issue=issue["number"], user_id=user_id, login=login, name=name, key=k, version=version.version,
                    notes=version.notes, files=unpacked.files, attachment_url=form.attachments[0],
                    zip_sha256=zip_sha256, entry=None if entry is None else dict(entry))
    ok, reason = may_publish(upload)
    if not ok:
        return refuse("held", reason=reason)
    return Accepted(upload, unpacked, checked.remarks + version.remarks)


@dataclass(frozen=True)
class Outcome:
    kind: Literal["published", "refused", "stuck", "behind", "unreachable"]
    reply: str = ""
    upload: Upload | None = None


def handle(issue: dict, root: Path, now: datetime, python310: str, fetch=gh.fetch) -> Outcome:
    """收一份。這裡不呼叫任何 GitHub API；回覆、標籤是 finish 的事。"""
    if refusal := who_refusal(issue.get("user")):
        return Outcome("refused", refusal.text)
    form = gh.parse_body(issue.get("body"))
    if refusal := gh.form_refusal(form):
        return Outcome("refused", refusal.text)
    # 在 try 外面：registry 壞了（DuplicateKey 是 ValueError）不能變成對上傳的人說「zip 打不開」
    registry_data = registry.read_json_strict(root / "registry.json")
    received = registry.read_json_strict(root / "received.json")
    name: str | None = None
    with tempfile.TemporaryDirectory(prefix="iplot-upload-") as tmp_name:
        tmp = Path(tmp_name)
        try:
            zip_path = tmp / "upload.zip"
            zip_sha256 = fetch(form.attachments[0], zip_path)
            result = examine(issue, form, zip_path, zip_sha256, root, registry_data, received, now, python310,
                             tmp / "staging")
            if isinstance(result, Refusal):
                return Outcome("refused", result.text)
            name = result.upload.name
            write_in(root, result.unpacked, result.upload, registry_data, received, now)
            commit(root, result.upload)
        except gh.TooBig:
            return Outcome("refused", refuse("too_big").text)
        except gh.DownloadError as exc:
            return Outcome("refused", refuse("download", reason=exc.reason).text)
        except NotWritable:
            rollback(root, name)
            return Outcome("refused", refuse("not_writable").text)
        except KNOWN as exc:
            rollback(root, name)
            return Outcome("refused", refuse("broken", kind=kind_of(exc)).text)
        except Exception:  # noqa: BLE001 —— 設計第 5.2 節：其他任何例外都是「卡住」，不擋下一份
            traceback.print_exc()
            rollback(root, name)
            return Outcome("stuck", SAY["stuck"])
    upload, unpacked = result.upload, result.unpacked
    pushed = push(root)
    if pushed.kind == "ok":
        reply = received_reply(upload.name, upload.version, [f.path for f in upload.files], unpacked.skipped,
                               result.remarks)
        return Outcome("published", reply, upload)
    rollback(root, upload.name)
    if pushed.kind == "blocked":
        return Outcome("refused", refuse("blocked", reason=pushed.reason).text, upload)
    return Outcome(pushed.kind, "", upload)


def _labels(issue: dict) -> list[str]:
    return [label["name"] for label in issue.get("labels", [])]


def _attempt(what: str, number: int, call) -> bool:
    """寫 GitHub 一次；ApiError 印出來、回 False，接著做下一件。RateLimited 不接。"""
    try:
        call()
    except gh.ApiError as exc:
        print(f"#{number} {what}沒有成功：{exc}", file=sys.stderr)
        return False
    return True


def finish(api, issue: dict, outcome: Outcome) -> None:
    """一份上傳只寫兩次：留言、PATCH（標籤＋狀態）。"""
    number, labels = issue["number"], _labels(issue)
    if outcome.kind == "published":
        upload = outcome.upload
        posted = (_attempt("留言", number, lambda: gh.comment(api, number, outcome.reply))
                  or _attempt("短版留言", number, lambda: gh.comment(
                      api, number, short_reply(upload.name, upload.version, len(upload.files)))))
        if not posted:
            return  # issue 開著：下一次的 finish_received 補留言與 PATCH
        _attempt("關 issue", number, lambda: gh.set_state(api, number, labels + ["已發佈"], "closed", "completed"))
    elif outcome.kind == "refused":
        _attempt("留言", number, lambda: gh.comment(api, number, outcome.reply))
        _attempt("關 issue", number, lambda: gh.set_state(api, number, labels + ["沒收"], "closed", "not_planned"))
    elif outcome.kind == "stuck":
        _attempt("留言", number, lambda: gh.comment(api, number, outcome.reply))
        _attempt("貼標籤", number, lambda: gh.set_state(api, number, [x for x in labels if x != "上傳"] + ["卡住"]))


def finish_received(api, issue: dict, record: dict) -> None:
    """received.json 已經有這個 issue（push 成功了，回覆或 PATCH 沒做成）：只補，不重收、不回「沒收」。"""
    number = issue["number"]

    def reply() -> None:
        if not gh.has_marker(api, number, MARK_RECEIVED):
            gh.comment(api, number, short_reply(record["name"], record["version"], None))

    if not _attempt("補留言", number, reply):
        return
    _attempt("關 issue", number,
             lambda: gh.set_state(api, number, _labels(issue) + ["已發佈"], "closed", "completed"))


def _read_both(root: Path) -> str | None:
    """registry.json、received.json 讀得了就回 None；不行回要印的那一句。"""
    for name in ("registry.json", "received.json"):
        try:
            registry.read_json_strict(root / name)
        except registry.DuplicateKey as exc:
            return f"{name} 有重複的鍵：{exc}"
        except (OSError, ValueError) as exc:
            return f"{name} 讀不了：{exc}"
    return None


def main(argv: list[str] | None = None, *, api=None, root: Path = ROOT, now=None, fetch=gh.fetch,
         python310: str | None = None) -> int:
    python310 = python310 or source.find_python310()
    if python310 is None:
        print("找不到 python3.10：這一道檢查不能跳過", file=sys.stderr)
        return 1
    if problem := _read_both(root):
        print(problem, file=sys.stderr)
        return 1
    if api is None:
        token, repo = os.environ.get("GH_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
        if not token or not repo:
            print("要有 GH_TOKEN 與 GITHUB_REPOSITORY 才能跑", file=sys.stderr)
            return 1
        api = gh.Api(token, repo, os.environ.get("GITHUB_API_URL") or gh.API)
    clock = now or (lambda: datetime.now(UTC))
    try:
        gh.ensure_labels(api)
        for issue in gh.open_uploads(api)[:MAX_PER_RUN]:
            number = issue["number"]
            received = registry.read_json_strict(root / "received.json")
            if str(number) in received:
                finish_received(api, issue, received[str(number)])
                continue
            outcome = handle(issue, root, clock(), python310, fetch)
            if outcome.kind == "behind":
                print(f"#{number}：origin 有新的 commit，這一次停在這裡，下一次用新的 registry 收", file=sys.stderr)
                return 0
            if outcome.kind == "unreachable":
                print(f"#{number}：push 連不上，這一次停在這裡", file=sys.stderr)
                if not gh.has_marker(api, number, MARK_RETRY):
                    gh.comment(api, number, SAY["retry"] + "\n\n" + MARK_RETRY)
                return 1
            finish(api, issue, outcome)
    except gh.RateLimited as exc:
        print(f"GitHub 的速率上限：要等 {exc.wait:g} 秒，剩下的留給下一次", file=sys.stderr)
        return 0
    except registry.DuplicateKey as exc:
        print(f"registry.json 或 received.json 有重複的鍵：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
