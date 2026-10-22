"""build：照 registry.json 打網站（設計第 5.6 節）。

只發有 version、沒有 reserved、沒有 removed、modules/<名稱>/ 在、裡面有 iplot.py 的那幾筆；registry 沒登記的資料夾不發。
一筆一筆各自 try：讀不了、打不了的那一筆跳過、寫進 summary，其他照發。zip 的時間、權限固定：內容一樣，sha256 就一樣。
說明與 ICON 從 modules/<名稱>/iplot.py 重新讀、重新截（registry.json 不存它們）。寫完自己驗一次，不過就失敗、不部署。
上傳的東西只讀不執行。跑法：python -I tools/build.py site（GH_TOKEN、GITHUB_REPOSITORY 有就查現在的帳號名）。
"""

import argparse
import hashlib
import html
import json
import os
import sys
import unicodedata
import urllib.parse
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gh  # noqa: E402
import registry  # noqa: E402
from iplot_rules import SKIP, install_shape, read_listing, read_meta, url  # noqa: E402
from say import clip  # noqa: E402
from source import MAX_DESCRIPTION, MAX_ICON  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://william10310406.github.io/iplot-modules"
FORM_URL = "https://github.com/william10310406/iplot-modules/issues/new?template=" + urllib.parse.quote("上傳模組.yml")
MODULES = "模組"
MAX_INDEX = 2 * 1024 * 1024
EPOCH = (1980, 1, 1, 0, 0, 0)
DELETED = "帳號已刪除"
CHUNK = 64 * 1024

PAGE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>iPLoT 工作坊</title>
<style>
:root {{ color-scheme: light dark; --bg: #ffffff; --fg: #1c1d21; --muted: #6b7080; --line: #dfe2e9; --accent: #3d6ee0;
  --warn: #c62828; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #242529; --fg: #ebecf0; --muted: #9a9fae; --line: #34363f; --accent: #7398f4; --warn: #ef6b6b; }}
}}
body {{ margin: 0 auto; max-width: 760px; padding: 20px 16px 40px; background: var(--bg); color: var(--fg);
  font: 15px/1.6 -apple-system, BlinkMacSystemFont, "PingFang TC", "Microsoft JhengHei", "Segoe UI", sans-serif; }}
h1 {{ font-size: 22px; margin: 0 0 16px; }}
a {{ color: var(--accent); }}
.notice {{ white-space: pre-line; }}
.box {{ border-top: 1px solid var(--line); padding: 12px 0; }}
.icon {{ font-size: 22px; margin-right: 6px; }}
.muted, .sha {{ color: var(--muted); font-size: 13px; }}
.sha {{ font-family: ui-monospace, Menlo, monospace; overflow-wrap: anywhere; }}
.notes {{ white-space: pre-line; }}
.warn {{ color: var(--warn); }}
</style>
</head>
<body>
<h1>iPLoT 工作坊</h1>
<p class="notice">{notice}</p>
<p>要上傳自己的模組：<a href="{form_url}">用這個表單</a>（要有 GitHub 帳號）</p>
{blocks}
</body>
</html>
"""
BLOCK = """<div class="box">
<p><span class="icon">{icon}</span><strong>{name}</strong> <span class="muted">{version}</span></p>
<p class="muted">上傳者：{author}</p>
<p>{description}</p>
{notes}{warning}<p><a href="{zip_url}">下載 {name}.zip</a></p>
<p class="sha">sha256 {sha256}</p>
</div>"""


def pack(folder: Path, name: str, out_dir: Path) -> Path:
    """folder 裡的一般檔打成 out_dir/<名稱>.zip，每一條在 <名稱>/ 底下；時間、權限固定，照路徑排序，沒有目錄條目。
    不收符號連結；路徑任何一段在 SKIP 的不收。"""
    files: dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk(folder):
        here = Path(dirpath)
        dirnames[:] = [d for d in dirnames if d.casefold() not in SKIP and not (here / d).is_symlink()]
        for filename in filenames:
            path = here / filename
            if filename.casefold() in SKIP or path.is_symlink() or not path.is_file():
                continue
            rel = unicodedata.normalize("NFC", path.relative_to(folder).as_posix())
            if any(part.casefold() in SKIP for part in rel.split("/")):
                continue
            files[rel] = path
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.zip"
    with zipfile.ZipFile(target, "w") as z:
        for rel in sorted(files):
            info = zipfile.ZipInfo(f"{name}/{rel}", date_time=EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            with files[rel].open("rb") as src, z.open(info, "w") as dst:
                while chunk := src.read(CHUNK):
                    dst.write(chunk)
    return target


def publishable(registry_data: dict, root: Path) -> tuple[list[dict], list[str]]:
    """registry 裡可以發的那幾筆，與跳過的句子。保留、下架、沒有 version 的不算錯，不進 summary。"""
    entries, lines = [], []
    for entry in registry_data.values():
        if not isinstance(entry, dict) or "version" not in entry or entry.get("reserved") or entry.get("removed"):
            continue
        name = entry.get("name", "")
        folder = root / "modules" / name
        if not folder.is_dir():
            lines.append(f"跳過「{name}」：modules/{name}/ 不在")
        elif "iplot.py" not in os.listdir(folder):
            lines.append(f"跳過「{name}」：資料夾裡沒有 iplot.py")
        else:
            entries.append(entry)
    return entries, lines


def author_of(api, entry: dict, cache: dict[int, str]) -> str:
    """現在的帳號名；帳號刪了是 DELETED，查不到（逾時、5xx、速率）用 registry 的 owner。同一個 owner_id 只查一次。"""
    owner_id = entry.get("owner_id")
    if api is None or owner_id is None:
        return entry.get("owner", "")
    if owner_id not in cache:
        try:
            cache[owner_id] = gh.login_of(api, owner_id)
        except gh.NotFound:
            cache[owner_id] = DELETED
        except (gh.ApiError, gh.RateLimited):
            cache[owner_id] = entry.get("owner", "")
    return cache[owner_id]


def make_entry(entry: dict, root: Path, out: Path, base_url: str, api, cache) -> dict:
    """打這一筆的 zip，回 index.json 的那一筆。iplot.py 讀不了、要寫進 index.json 的字編不成 UTF-8（落單的代理字元）
    丟 ValueError；兩樣都在打 zip 之前查，跳過的那一筆不留 zip。"""
    name = entry["name"]
    folder = root / "modules" / name
    meta = read_meta(folder / "iplot.py")
    if meta.error is not None:
        raise ValueError(f"iplot.py 讀不了：{meta.error}")
    description = clip(meta.description, MAX_DESCRIPTION)[0]
    icon = clip(meta.icon or "", MAX_ICON)[0]
    notes = entry.get("notes", "")
    author = author_of(api, entry, cache)
    warning = entry.get("warning")
    if not (isinstance(warning, str) and warning):
        warning = None
    shown = [name, entry["version"], description, icon, notes, author, warning]
    try:
        json.dumps(shown, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("有不成對的代理字元，不能寫進 index.json") from None
    zip_path = pack(folder, name, out / MODULES)
    result = {
        "name": name,
        "version": entry["version"],
        "zip_url": url(base_url, MODULES, f"{name}.zip"),
        "sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        "description": description,
        "icon": icon,
        "notes": notes,
        "author": author,
    }
    if warning is not None:
        result["warning"] = warning
    return result


def index_bytes(notice: str, uploads: list[dict]) -> bytes:
    data = {"notice": notice, "modules": [], "uploads": sorted(uploads, key=lambda u: registry.key(u["name"]))}
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def render_html(notice: str, uploads: list[dict]) -> str:
    """index.html：純 HTML 加內嵌的 CSS，沒有 JS、沒有外部資源；每個字都先 html.escape。"""
    e = lambda value: html.escape(str(value), quote=True)  # noqa: E731
    blocks = []
    for u in sorted(uploads, key=lambda u: registry.key(u["name"])):
        author = u["author"] if u["author"] == DELETED else f"@{u['author']}"
        notes = f'<p class="notes">這一版：{e(u["notes"])}</p>\n' if u.get("notes") else ""
        warning = f'<p class="warn">⚠ {e(u["warning"])}</p>\n' if u.get("warning") else ""
        blocks.append(BLOCK.format(icon=e(u["icon"]), name=e(u["name"]), version=e(u["version"]), author=e(author),
                                   description=e(u["description"]), notes=notes, warning=warning,
                                   zip_url=e(u["zip_url"]), sha256=e(u["sha256"])))
    return PAGE.format(notice=e(notice), form_url=e(FORM_URL), blocks="\n".join(blocks))


def site_problems(out: Path, uploads: list[dict]) -> list[str]:
    """寫完之後自己驗一次：index.json 讀得懂、跟 uploads 一樣；每個 zip 在、sha256 對、形狀 workshop.install 收得下。"""
    try:
        data = json.loads((out / "index.json").read_text(encoding="utf-8"))
        listed, notice = read_listing(data)
    except (OSError, ValueError) as exc:
        return [f"index.json 讀不懂：{exc}"]
    problems = []
    if [u["name"] for u in listed] != [u["name"] for u in sorted(uploads, key=lambda u: registry.key(u["name"]))]:
        problems.append("index.json 的名稱跟要發的不一樣")
    if data.get("modules") != []:
        problems.append("index.json 的 modules 不是空的")
    if not notice:
        problems.append("index.json 的 notice 是空的")
    for u in listed:
        zip_path = out / MODULES / f"{u['name']}.zip"
        if not zip_path.is_file():
            problems.append(f"「{u['name']}」的 zip 不在")
            continue
        if hashlib.sha256(zip_path.read_bytes()).hexdigest() != u["sha256"]:
            problems.append(f"「{u['name']}」的 sha256 不對")
        try:
            shape = install_shape(zip_path, u["name"])
        except (OSError, zipfile.BadZipFile) as exc:
            shape = str(exc)
        if shape is not None:
            problems.append(f"「{u['name']}」：{shape}")
    return problems


def summary(lines: list[str]) -> None:
    text = "\n".join(lines)
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def main(argv: list[str] | None = None, *, root: Path = ROOT, api=None) -> int:
    parser = argparse.ArgumentParser(description="照 registry.json 打工作坊的網站")
    parser.add_argument("out", type=Path)
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args(argv)
    out: Path = args.out
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        print(f"{out} 已經在而且不是空的：換一個資料夾", file=sys.stderr)
        return 1
    try:
        notice = (root / "notice.txt").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"notice.txt 讀不到：{exc}", file=sys.stderr)
        return 1
    if not notice:
        print("notice.txt 是空的", file=sys.stderr)
        return 1
    try:
        registry_data = registry.read_json_strict(root / "registry.json")
    except (OSError, ValueError) as exc:
        print(f"registry.json 讀不了：{exc}", file=sys.stderr)
        return 1
    if api is None:
        token, repo = os.environ.get("GH_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
        if token and repo:
            api = gh.Api(token, repo, os.environ.get("GITHUB_API_URL") or gh.API)
    entries, lines = publishable(registry_data, root)
    uploads, cache = [], {}
    for entry in entries:
        try:
            uploads.append(make_entry(entry, root, out, args.base_url, api, cache))
        except Exception as exc:  # noqa: BLE001
            lines.append(f"跳過「{entry.get('name', '')}」：{str(exc) or type(exc).__name__}")
    lines.append(f"發佈 {len(uploads)} 個模組")
    data = index_bytes(notice, uploads)
    if len(data) > MAX_INDEX:
        summary([*lines, f"index.json 有 {len(data)} 位元組，超過 {MAX_INDEX}：不部署"])
        return 1
    try:
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.json").write_bytes(data)
        (out / "index.html").write_text(render_html(notice, uploads), encoding="utf-8")
    except OSError as exc:
        summary([*lines, f"index.json、index.html 寫不出來：{exc}"])
        return 1
    if problems := site_problems(out, uploads):
        summary([*lines, *problems])
        return 1
    summary(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
