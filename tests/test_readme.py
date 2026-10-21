import re
from pathlib import Path

import build
import gh
import registry
import say
import source
import zipcheck

README = Path(__file__).resolve().parents[1] / "README.md"
PUNCT = "「」（）：，。、；.／ "


def text() -> str:
    return README.read_text(encoding="utf-8")


def section(title: str) -> str:
    body = text()
    start = body.index(f"## {title}")
    nxt = re.search(r"^## ", body[start + 3:], re.MULTILINE)
    return body[start:start + 3 + nxt.start()] if nxt else body[start:]


def mib(n: int) -> int:
    return n // (1024 * 1024)


def test_readme_says_there_is_no_review():
    assert "沒有人審查" in text()


def test_readme_numbers_match_the_constants():
    body = text()
    wanted = [
        f"{mib(gh.MAX_ZIP)} MB", f"{mib(zipcheck.MAX_UNPACKED)} MB", f"{zipcheck.MAX_FILES} 個檔",
        f"{zipcheck.MAX_ENTRIES}", f"{mib(source.MAX_IPLOT)} MB", f"{source.MAX_DESCRIPTION} 字",
        f"{registry.MAX_NOTES} 字", f"{source.MAX_ICON} 字", f"{registry.MAX_PER_DAY} 份",
        f"{registry.MAX_NAMES} 個名字", f"{mib(registry.MAX_MODULES)} MB",
    ]
    missing = [w for w in wanted if w not in body]
    assert not missing, missing


def fragment(sentence: str) -> str:
    pieces = [p.strip(PUNCT) for p in re.split(r"\{[^}]*\}", sentence)]
    return next(p for p in pieces if len(p) >= 2)


def test_readme_lists_every_refusal():
    refusals = section("沒收的原因").replace("\\|", "|")  # 表格裡的 | 要跳脫
    missing = [key for key, sentence in say.SAY.items()
               if key != "held" and fragment(sentence) not in refusals]
    assert not missing, missing


def test_readme_says_how_to_take_a_module_down():
    body = text()
    for word in ("removed", "owner_id", "warning", "notice.txt"):
        assert word in body


def test_readme_links_the_form():
    body = text()
    assert build.FORM_URL in body or "issues/new?template=" in body


def test_readme_has_no_personal_paths():
    body = text()
    assert "/Users/" not in body
    assert "/private/tmp" not in body
