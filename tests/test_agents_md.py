"""iPLoT 的規則放上工作坊（iPLoT D160，2026-11-23 William：別人遵不遵守是他們的事，但規矩要上傳）：
AGENTS.md 的「寫模組」一節、tools/check_deps.py、tools/deps_allow.json 都逐字抄自 iPLoT；
收件時跑同一支依賴檢查，維護者的模組有新違規就退回，別人的照收、在回覆裡警告。"""
from pathlib import Path

import check_deps
import receive
from say import refuse
from test_license import RA_ID, refused, upload

ROOT = Path(__file__).resolve().parents[1]
BAD = '"""示範。"""\nfrom core import scan\n\n\ndef run(app):\n    app.log(scan)\n'
PROBLEM = "import 了核心的內部（R2，iplot.py：core.scan）"


def section(text: str) -> str:
    return text[text.index("## 一、寫模組"):text.index("## ", text.index("## 一、寫模組") + 3)]


def test_copies_agree_with_iplot_next_door(iplot_next_door):
    for name in ("tools/check_deps.py", "tools/deps_allow.json"):
        assert (ROOT / name).read_bytes() == (iplot_next_door / name).read_bytes(), name
    ours = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert section(ours) == section((iplot_next_door / "AGENTS.md").read_text(encoding="utf-8"))


def test_the_other_assistants_files_only_point_to_agents_md():
    for name in ("CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "AGENTS.md" in text and len(text) < 200, name


def test_dependency_problems_are_one_sentence_each(tmp_path):
    folder = tmp_path / "整理桌面"
    folder.mkdir()
    (folder / "iplot.py").write_text(BAD, encoding="utf-8")
    assert receive.dependency_problems(folder, {}) == [PROBLEM]
    (folder / "iplot.py").write_text('"""示範。"""\n\n\ndef run(app):\n    app.log("好")\n', encoding="utf-8")
    assert receive.dependency_problems(folder, {}) == []


def test_the_maintainers_module_is_refused(repo, python310, tmp_path):
    refused(repo, python310, tmp_path, 1, refuse("deps", problems=PROBLEM).text, login="william10310406",
            user_id=RA_ID, iplot=BAD)


def test_someone_elses_module_is_received_with_a_warning(repo, python310, tmp_path):
    api, _ = upload(repo, python310, tmp_path, 1, iplot=BAD)
    assert receive.DEPS_REMARK.format(problems=PROBLEM) in api.comments[1][0]


def test_check_deps_reads_this_repos_modules_for_names():
    assert check_deps.ROOT == ROOT and (ROOT / "modules").is_dir()
