"""測試共用的東西：隔壁的 iPLoT clone、載入 iPLoT 的檔、把開發者自己的 git 設定隔開。"""

import copy
import hashlib
import importlib.util
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import threading
import zipfile
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

IPLOT = Path(__file__).resolve().parents[2] / "iplot"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def iplot_next_door():
    """隔壁有 iPLoT 的 clone 就回它的路徑，沒有就 skip（對照的測試只在本機有兩個 repo 時跑）。"""
    if not (IPLOT / "core" / "create.py").is_file():
        pytest.skip("隔壁沒有 iPLoT 的 clone")
    return IPLOT


def load_iplot(relpath: str, name: str):
    """載入 iPLoT 的一個檔（例如 load_iplot("core/create.py", "core.create")），回那個模組。
    載入時暫時把 IPLOT 放進 sys.path、不寫 __pycache__；結束時拿掉 sys.path 加的、
    這一次載入的 name 與 core、core.* ——tools/publish.py 一載入就 from core.meta import read_meta。"""
    path_before = list(sys.path)
    modules_before = set(sys.modules)
    bytecode_before = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(IPLOT))
    try:
        spec = importlib.util.spec_from_file_location(name, IPLOT / relpath)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # dataclass 要在 sys.modules 找得到自己的模組
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = path_before
        sys.dont_write_bytecode = bytecode_before
        for loaded in set(sys.modules) - modules_before:
            if loaded == name or loaded == "core" or loaded.startswith("core."):
                del sys.modules[loaded]


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    """git 只看一個空的全域設定、不看系統的：開發者自己的 git 設定不混進測試。"""
    config = tmp_path / "gitconfig"
    config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def make_zip(path: Path, entries: dict[str, bytes | str | None], *, symlinks: dict[str, str] | None = None,
             method: int = zipfile.ZIP_DEFLATED) -> Path:
    """用 zipfile 造 zip；值是 None 的是目錄條目（名字結尾 /）。
    注意：這樣造的非 ASCII 檔名會自動標 UTF-8（0x800），跟 Finder 壓的不一樣；要 Finder 那種用 tests/fixtures。"""
    with zipfile.ZipFile(path, "w", compression=method) as z:
        for name, data in entries.items():
            if data is None:
                z.writestr(name if name.endswith("/") else name + "/", b"")
            else:
                z.writestr(name, data)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o755) << 16
            z.writestr(info, target)
    return path


def patch_zip(path: Path, *, encrypted: bool = False, method: int | None = None, size_delta: int = 0,
              first_data_byte: int | None = None) -> Path:
    """只改第一條的位元組，造出壞 zip。偏移：本地檔頭 6（旗標）、8（壓縮法）、22（原始大小）；
    中央目錄 8、10、24；資料從本地偏移 30 + 檔名長 + extra 長 開始。size_delta 兩處一起加。"""
    data = bytearray(path.read_bytes())
    eocd = data.rfind(b"PK\x05\x06")
    cd = struct.unpack_from("<I", data, eocd + 16)[0]
    assert data[0:4] == b"PK\x03\x04" and data[cd:cd + 4] == b"PK\x01\x02"
    for base, flag, comp, size in ((0, 6, 8, 22), (cd, 8, 10, 24)):
        if encrypted:
            data[base + flag] |= 1
        if method is not None:
            struct.pack_into("<H", data, base + comp, method)
        if size_delta:
            old = struct.unpack_from("<I", data, base + size)[0]
            struct.pack_into("<I", data, base + size, old + size_delta)
    if first_data_byte is not None:
        name_len, extra_len = struct.unpack_from("<HH", data, 26)
        data[30 + name_len + extra_len] = first_data_byte
    path.write_bytes(bytes(data))
    return path


def big5_zip(path: Path, name: str = "整理桌面") -> Path:
    """檔名是 Big5、沒標 UTF-8 旗標的 zip：zipfile 寫非 ASCII 一律標 UTF-8，
    所以先寫同長度的 ASCII 名字，再把位元組換成 Big5。"""
    raw = name.encode("big5")
    placeholder = b"Q" * len(raw)
    make_zip(path, {f"{placeholder.decode()}/iplot.py": "x" * 1100})
    path.write_bytes(path.read_bytes().replace(placeholder + b"/iplot.py", raw + b"/iplot.py"))
    return path


DEFAULT_ATTACHMENT = "https://github.com/user-attachments/files/33695492/default.zip"


def form_body(url: str | None = DEFAULT_ATTACHMENT, *, more_urls=(), notes: str = "_No response_",
              agreed: bool = True) -> str:
    """照 tests/fixtures/issue-body.md 的樣子組表單送出之後的內文：附件是一行 [原檔名](網址)，沒傳是 _No response_。"""
    from gh import AGREE_TEXT

    links = [f"[整理桌面.zip]({u})" for u in ([url] if url else []) + list(more_urls)]
    box = "x" if agreed else " "
    return (f"### 模組的 zip\n\n{chr(10).join(links) if links else '_No response_'}\n\n"
            f"### 這一版改了什麼（選填）\n\n{notes}\n\n"
            f"### 確認\n\n- [{box}] {AGREE_TEXT}")


class Server:
    """一台跑在 127.0.0.1 的小 HTTP 伺服器；host 只是網址裡寫的名字（第二台用 localhost）。"""

    def __init__(self, routes: dict[str, Callable[[BaseHTTPRequestHandler], None]], host: str):
        self.host = host
        self.seen: list[tuple[str, dict[str, str]]] = []
        seen = self.seen

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, dict(self.headers)))
                route = routes.get(self.path.split("?")[0])
                try:
                    if route is None:
                        self.send_error(404)
                    else:
                        route(self)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # 下載的那一端先斷線了

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05},
                                       daemon=True)
        self.thread.start()

    def url(self, path: str = "/") -> str:
        return f"http://{self.host}:{self.httpd.server_address[1]}{path}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()


@pytest.fixture
def http_server(monkeypatch):
    """工廠 make(routes, host="127.0.0.1")：routes 是 {路徑: 收 handler 的函式}；測試結束全部關掉。"""
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")
    servers: list[Server] = []

    def make(routes, host="127.0.0.1") -> Server:
        servers.append(Server(routes, host))
        return servers[-1]

    yield make
    for server in servers:
        server.close()


TEST_ID = ("-c", "user.name=測試", "-c", "user.email=t@example.invalid")


def git(cwd: Path, *args: str) -> str:
    """測試裡跑 git（只在暫存資料夾裡）；結束碼不是 0 就丟例外，回 stdout。"""
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          check=True, env={**os.environ, "LC_ALL": "C"})
    return done.stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    """tmp/origin.git（bare）＋ clone 成 tmp/work；work 已經 commit、push 一次。回 work。"""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(work))
    git(work, "symbolic-ref", "HEAD", "refs/heads/main")
    git(work, "config", "core.ignorecase", "false")
    (work / "registry.json").write_text("{}\n", encoding="utf-8")
    (work / "received.json").write_text("{}\n", encoding="utf-8")
    (work / "notice.txt").write_text("歡迎\n", encoding="utf-8")
    (work / ".gitignore").write_text("*.log\n", encoding="utf-8")
    git(work, "add", "-A")
    git(work, *TEST_ID, "commit", "-q", "-m", "種子")
    git(work, "push", "-q", "origin", "HEAD:main")
    return work


def push_from_elsewhere(repo: Path, change: Callable[[Path], None]) -> None:
    """另外 clone 一份、做 change、commit、push：模擬研究助理剛好 push。"""
    other = repo.parent / "elsewhere"
    while other.exists():
        other = other.with_name(other.name + "x")
    git(repo.parent, "clone", "-q", str(repo.parent / "origin.git"), str(other))
    change(other)
    git(other, "add", "-A")
    git(other, *TEST_ID, "commit", "-q", "-m", "別處的 commit")
    git(other, "push", "-q", "origin", "HEAD:main")


class FakeApi:
    """gh.Api 的替身：一樣的 get/post/patch、writes；照路徑回資料，不連網。
    fail 的鍵是 "comment"、"patch"、"user"：碰到就依序丟出清單裡的例外（丟出去的那一次不留下東西）。"""

    def __init__(self, issues=(), labels=(), comments=None, users=None, fail=None, repo="iplot/iplot-modules"):
        self.repo = repo
        self.issues: list[dict] = [copy.deepcopy(i) for i in issues]
        self.labels: set[str] = set(labels)
        self.comments: dict[int, list[str]] = {n: list(c) for n, c in (comments or {}).items()}
        self.patches: list[tuple[int, dict]] = []
        self.users: dict[int, str | BaseException] = dict(users or {})
        self.fail: dict[str, list[BaseException]] = {k: list(v) for k, v in (fail or {}).items()}
        self.requests: list[tuple[str, str]] = []
        self.writes = 0

    def _maybe_fail(self, kind: str) -> None:
        if self.fail.get(kind):
            raise self.fail[kind].pop(0)

    def _issue(self, number: int) -> dict:
        return next(i for i in self.issues if i["number"] == number)

    def get(self, path: str, params: dict | None = None):
        from gh import NotFound

        self.requests.append(("GET", path))
        params = params or {}
        base = f"/repos/{self.repo}"
        if path == f"{base}/labels":
            return [{"name": name} for name in sorted(self.labels)]
        if path == f"{base}/issues":
            state, label = params.get("state", "open"), params.get("labels")
            found = [i for i in self.issues if i.get("state", "open") == state
                     and (label is None or label in {lb["name"] for lb in i.get("labels", [])})]
            return copy.deepcopy(found)
        if m := re.fullmatch(re.escape(base) + r"/issues/(\d+)/comments", path):
            return [{"body": body} for body in self.comments.get(int(m.group(1)), [])]
        if m := re.fullmatch(r"/user/(\d+)", path):
            self._maybe_fail("user")
            login = self.users.get(int(m.group(1)))
            if isinstance(login, BaseException):
                raise login
            if login is None:
                raise NotFound(404, "Not Found")
            return {"login": login, "id": int(m.group(1))}
        raise NotFound(404, path)

    def post(self, path: str, body: dict):
        from gh import NotFound

        self.requests.append(("POST", path))
        self.writes += 1
        base = f"/repos/{self.repo}"
        if path == f"{base}/labels":
            self.labels.add(body["name"])
            return dict(body)
        if m := re.fullmatch(re.escape(base) + r"/issues/(\d+)/comments", path):
            self._maybe_fail("comment")
            self.comments.setdefault(int(m.group(1)), []).append(body["body"])
            return {"body": body["body"]}
        raise NotFound(404, path)

    def patch(self, path: str, body: dict):
        from gh import NotFound

        self.requests.append(("PATCH", path))
        self.writes += 1
        if m := re.fullmatch(re.escape(f"/repos/{self.repo}") + r"/issues/(\d+)", path):
            self._maybe_fail("patch")
            number = int(m.group(1))
            self.patches.append((number, copy.deepcopy(body)))
            target = self._issue(number)
            if "labels" in body:
                target["labels"] = [{"name": name} for name in body["labels"]]
            if "state" in body:
                target["state"] = body["state"]
            return copy.deepcopy(target)
        raise NotFound(404, path)


def issue(number: int, *, login="someone", user_id=222, type="User", body=None, labels=("上傳",)) -> dict:
    """API 回的一筆 issue（只有機器人用到的欄位）；body 預設 form_body()。"""
    return {"number": number, "state": "open", "user": {"login": login, "id": user_id, "type": type},
            "body": form_body() if body is None else body, "labels": [{"name": name} for name in labels]}


def fake_fetch(zips: dict[str, Path]):
    """跟 gh.fetch 同簽名：把網址對應的 zip 複製到 dest、回 sha256；網址不在就 DownloadError("HTTP 404")。
    叫過的網址記在回傳函式的 calls。"""
    from gh import DownloadError

    def fetch(url: str, dest: Path, **_kwargs) -> str:
        fetch.calls.append(url)
        if url not in zips:
            raise DownloadError("HTTP 404")
        shutil.copyfile(zips[url], dest)
        return hashlib.sha256(dest.read_bytes()).hexdigest()

    fetch.calls = []
    return fetch


@pytest.fixture
def python310(monkeypatch) -> str:
    """有 python3.10 就給它；沒有就讓 source.syntax_310 一律說可以，給一個假的路徑。"""
    found = shutil.which("python3.10")
    if found:
        return found
    import source

    monkeypatch.setattr(source, "syntax_310", lambda *args, **kwargs: None)
    return "/fake/python3.10"
