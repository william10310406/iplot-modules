"""iPLoT 的規則的抄本：機器人要跟 iPLoT 判斷得一模一樣的那幾樣。iPLoT 的 repo 是 private，這裡 import 不到，只能抄。

抄自 iPLoT d5b149b（核心 0.5.1；分支 m7-upload）：
- core/create.py：FORBIDDEN_CHARS、RESERVED、_bad_name（這裡叫 bad_name）
- core/text.py：T["bad_name"]（這裡叫 BAD_NAME_TEXT）、T["syntax_error"]（這裡叫 SYNTAX_ERROR）
- core/types.py：Meta
- core/meta.py：read_meta（T["syntax_error"] 換成 SYNTAX_ERROR）
- tools/publish.py：changelog_notes、latest、_url（這裡叫 url）
- modules/工作坊/workshop.py：SKIP、NEEDED、_newer（這裡叫 newer）、read_listing（照 M7 工作單的約定：iPLoT 那邊讀網址，
  這裡讀已經解開的 JSON）、install 對 zip 的形狀檢查（這裡叫 install_shape）

改了 iPLoT 的這幾處，這裡要一起改（docs/07 第 11 節）；兩邊的 tests/test_rules_table.py 是同一張表，
tests/test_iplot_rules.py 的 test_copies_agree_with_iplot_next_door 拿隔壁的 iPLoT 直接比。
照抄的地方逐字抄，不順手改寫。
"""

import ast
import re
import urllib.parse
import zipfile
from dataclasses import dataclass
from itertools import takewhile
from pathlib import Path

# ---- core/create.py ----
FORBIDDEN_CHARS = set('/\\:*?"<>|')
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10))}

# ---- core/text.py ----
BAD_NAME_TEXT = ("名稱不能是空白、以 . 開頭、結尾是 . 或空白、含 / \\ : * ? \" < > |，"
                 "也不能是 CON、NUL 這類 Windows 保留字（模組要能複製到任何系統）")
SYNTAX_ERROR = "第 {line} 行：{message}"

# ---- modules/工作坊/workshop.py ----
SKIP = {".history", ".origin", ".unconfirmed", "__pycache__", ".ds_store"}
NEEDED = ("name", "version", "zip_url", "sha256")  # 索引的每一筆至少要有這幾項


def bad_name(name: str) -> bool:
    """三個平台擋同一套：模組以後會被複製到別的電腦（D54）。"""
    return (not name.strip() or name.startswith(".") or name != name.rstrip(". ")
            or any(c in FORBIDDEN_CHARS or ord(c) < 32 for c in name)
            or name.split(".")[0].upper() in RESERVED)


# ---- core/types.py ----
@dataclass(frozen=True)
class Meta:
    """不執行地從 iplot.py 讀出來的資訊。"""

    title: str | None
    description: str
    has_run: bool
    accepts_files: bool
    error: str | None
    icon: str | None = None


# ---- core/meta.py ----
def read_meta(file: Path) -> Meta:
    """解析 file，取 docstring 第一段、TITLE、ICON、有沒有 run 與 on_files；壞掉的檔案把錯誤放進 error。"""
    try:
        tree = ast.parse(file.read_text(encoding="utf-8-sig"), str(file))
    except SyntaxError as exc:
        if exc.lineno is None:
            return Meta(None, "", False, False, str(exc))
        return Meta(None, "", False, False, SYNTAX_ERROR.format(line=exc.lineno, message=exc.msg))
    except (ValueError, OSError) as exc:  # 解碼失敗、3.10 的 NUL 位元組、讀不到
        return Meta(None, "", False, False, str(exc))
    consts, funcs = {}, set()  # 頂層的 TITLE = "…"、ICON = "…"：只認字串常數
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            funcs.add(node.name)
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ("TITLE", "ICON")
              and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            consts[node.targets[0].id] = node.value.value
    doc = ast.get_docstring(tree) or ""
    description = "\n".join(takewhile(str.strip, doc.splitlines()))
    return Meta(consts.get("TITLE"), description, "run" in funcs, "on_files" in funcs, None,
                consts.get("ICON"))


# ---- tools/publish.py ----
def changelog_notes(changelog: Path, version: str) -> str:
    """CHANGELOG.md 裡「## [version]」那一節的第一段（摘要）；找不到那一版回空字串。
    它會整段顯示在「要更新嗎」的對話框裡，所以只取摘要，不是整節。"""
    lines, found = [], False
    for line in changelog.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("## ["):
            if found:
                break
            found = line.startswith(f"## [{version}]")
        elif found:
            if not line.strip() and lines:
                break
            if line.strip():
                lines.append(line)
    return "\n".join(lines)


def latest(changelog: Path) -> tuple[str | None, str]:
    """CHANGELOG.md 最上面那一節（[Unreleased] 不算）的（版本號, 第一段）；沒有這個檔回 (None, "")。
    有這個檔、卻讀不出最上面那一版（不是 UTF-8、沒有任何一節、版本號不是 1.2.0 這種寫法）丟 ValueError（一句話）：
    不悄悄跳過那一節去發佈舊的，也不悄悄改用 --version。"""
    if not changelog.is_file():
        return None, ""
    try:
        text = changelog.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("不是 UTF-8 的文字檔") from None
    heads = [h for h in re.findall(r"^## \[([^\]]*)\]", text, re.M) if h.strip().casefold() != "unreleased"]
    if not heads:
        raise ValueError("裡面沒有「## [1.0.0] - 日期」這樣的一節")
    if not re.fullmatch(r"\d+(\.\d+)*", heads[0]):
        raise ValueError(f"最上面那一節的版本「{heads[0]}」不是 1.2.0 這種只有數字與點的寫法（工作坊比不了別的寫法）")
    return heads[0], changelog_notes(changelog, heads[0])


def url(base: str, *parts: str) -> str:
    """base 加上幾段路徑；中文與空白寫成 %XX（https 的網址只能是 ASCII），file:// 也照樣打得開。"""
    return "/".join([urllib.parse.quote(base.rstrip("/"), safe=":/%"), *(urllib.parse.quote(p) for p in parts)])


# ---- modules/工作坊/workshop.py ----
def newer(current, latest):
    try:
        return tuple(int(p) for p in str(latest).split(".")) > tuple(int(p) for p in str(current).split("."))
    except ValueError:
        return False


def read_listing(data: object) -> tuple[list[dict], str]:
    """index.json 解開之後的 data → (清單, notice)。有 uploads 就讀它（空清單也不退回 modules），沒有才讀 modules；
    版本一律當字串、同名的只留第一筆；notice 不是字串就是 ""。
    格式不對（不是 dict、讀到的不是清單、某一筆缺項或型別不對）丟 ValueError。"""
    if not isinstance(data, dict):
        raise ValueError("index.json 的格式不對")
    entries = data["uploads"] if "uploads" in data else data.get("modules")
    if not isinstance(entries, list) or not all(isinstance(e, dict) and all(k in e for k in NEEDED) for e in entries):
        raise ValueError("index.json 的格式不對")
    if not all(isinstance(e[k], str) for e in entries for k in ("name", "zip_url", "sha256")):
        raise ValueError("index.json 裡的名稱、網址、sha256 應該都是文字")
    seen = {}
    for e in entries:
        seen.setdefault(e["name"], {**e, "version": str(e["version"])})
    notice = data.get("notice")
    return list(seen.values()), notice if isinstance(notice, str) else ""


def install_shape(zip_path: Path, name: str) -> str | None:
    """workshop.install 對 zip 的三個檢查；過了回 None，不過回 iPLoT 那一句。
    名稱要是單純的資料夾名；每一條都在 <名稱>/ 底下、沒有 ..；濾掉 SKIP 之後要剛好有 <名稱>/iplot.py。"""
    if not isinstance(name, str) or not name.strip() or name.startswith(".") or set(name) & set("/\\"):
        return "索引裡的模組名稱不是單純的資料夾名"
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
    if any(not i.filename.startswith(name + "/") or ".." in i.filename.split("/") for i in infos):
        return f"zip 的最上層不是「{name}/」"
    files = [i.filename[len(name) + 1:] for i in infos if not i.is_dir()]
    if "iplot.py" not in [rel for rel in files if not any(part.casefold() in SKIP for part in rel.split("/"))]:
        return "包裡沒有 iplot.py"
    return None
