import re
from pathlib import Path

import gh

ROOT = Path(__file__).resolve().parents[1]
RECEIVE = ROOT / ".github/workflows/收模組.yml"
TEST = ROOT / ".github/workflows/測試.yml"
WORKFLOWS = [RECEIVE, TEST]
FORM = ROOT / ".github/ISSUE_TEMPLATE/上傳模組.yml"
CONFIG = ROOT / ".github/ISSUE_TEMPLATE/config.yml"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def jobs(path: Path) -> dict[str, list[str]]:
    """jobs: 底下每個兩格縮排的 job，對它的行（只照縮排判斷，不裝 PyYAML）。"""
    found: dict[str, list[str]] = {}
    current = None
    inside = False
    for line in text(path).splitlines():
        if line == "jobs:":
            inside = True
            continue
        if not inside:
            continue
        if line and not line.startswith(" "):
            break
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            current = m.group(1)
            found[current] = []
        elif current is not None:
            found[current].append(line)
    return found


def permissions_of(lines: list[str]) -> set[str]:
    """job 層（四格縮排）permissions: 底下六格縮排的那幾行，或一行 { … }。"""
    out: set[str] = set()
    for i, line in enumerate(lines):
        if line.startswith("    permissions:"):
            rest = line.split(":", 1)[1].strip()
            if rest.startswith("{"):
                out.update(p.strip() for p in rest.strip("{} ").split(",") if p.strip())
                return out
            for sub in lines[i + 1:]:
                if re.match(r"^      \S", sub):
                    out.add(sub.strip())
                else:
                    break
    return out


def test_issue_text_never_reaches_a_workflow():
    for path in WORKFLOWS:
        assert "github.event.issue" not in text(path)


def test_top_level_permissions_are_empty():
    for path in WORKFLOWS:
        assert "permissions: {}" in text(path).splitlines()


def test_every_job_has_its_own_permissions_and_timeout():
    for path in WORKFLOWS:
        found = jobs(path)
        assert found
        for name, lines in found.items():
            assert any(line.startswith("    permissions:") for line in lines), (path.name, name)
            assert any(line.startswith("    timeout-minutes:") for line in lines), (path.name, name)


def test_receive_build_deploy_have_the_least_permissions():
    found = jobs(RECEIVE)
    assert set(found) == {"receive", "build", "deploy"}
    assert permissions_of(found["receive"]) == {"contents: write", "issues: write"}
    assert permissions_of(found["build"]) == {"contents: read"}
    assert permissions_of(found["deploy"]) == {"pages: write", "id-token: write"}


def test_actions_are_github_own_and_pinned_to_a_sha():
    pattern = re.compile(r"^\s*(- )?uses: actions/[a-z-]+@[0-9a-f]{40}( # .+)?$")
    for path in WORKFLOWS:
        uses = [line for line in text(path).splitlines() if re.match(r"^\s*(- )?uses:", line)]
        assert uses
        for line in uses:
            assert pattern.match(line), line


def test_receive_and_build_check_out_main():
    lines = text(RECEIVE).splitlines()
    spots = [i for i, line in enumerate(lines) if "uses: actions/checkout@" in line]
    assert len(spots) == 2
    for i in spots:
        assert lines[i + 1].strip() == "with:"
        assert lines[i + 2].strip() == "ref: main"


def test_build_and_deploy_survive_a_failed_receive():
    found = jobs(RECEIVE)
    assert "    if: ${{ !cancelled() }}" in found["build"]
    assert "    if: ${{ !cancelled() && needs.build.result == 'success' }}" in found["deploy"]
    assert "    needs: receive" in found["build"]
    assert not any("needs.receive" in line for line in found["build"])


def test_concurrency_queues_instead_of_cancelling():
    body = text(RECEIVE)
    assert "  group: modules" in body.splitlines()
    assert "  queue: max" in body.splitlines()
    assert "cancel-in-progress" not in body


def test_triggers():
    body = text(RECEIVE)
    assert "  issues:\n    types: [opened]" in body
    assert "  push:\n    branches: [main]" in body
    assert "  workflow_dispatch:\n" in body
    assert "workflow_dispatch:\n    inputs" not in body
    assert '  schedule:\n    - cron: "17 * * * *"' in body


def test_pr_workflow_is_read_only_and_never_target():
    body = text(TEST)
    assert "on: pull_request\n" in body
    assert "pull_request_target" not in body
    assert "concurrency" not in body
    assert permissions_of(jobs(TEST)["test"]) == {"contents: read"}
    assert "persist-credentials: false" in body


def test_receive_runs_isolated_with_python310_present():
    body = text(RECEIVE)
    assert "python -I tools/receive.py" in body
    assert "python3.10 -c" in body
    assert "            3.10\n            3.12\n" in body


def test_issue_form_matches_the_parser():
    body = text(FORM)
    assert "type: upload" in body
    assert "id: zip" in body
    assert 'accept: ".zip"' in body
    assert "required: true" in body
    assert "labels: [上傳]" in body
    labels = re.findall(r"^\s+label: (.+)$", body, re.M)
    assert labels[:3] == [gh.HEADING_ZIP, gh.HEADING_NOTES, gh.HEADING_AGREE]
    assert re.search(r"^\s+- label: (.+)$", body, re.M).group(1) == gh.AGREE_TEXT


def test_form_warns_about_hidden_files():
    body = text(FORM)
    for word in (".venv", ".history", "⌘⇧."):
        assert word in body


def test_blank_issues_are_disabled():
    assert text(CONFIG).strip() == "blank_issues_enabled: false"
