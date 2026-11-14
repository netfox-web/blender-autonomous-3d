"""README legacy-admin-browser command stays identical to the pytest workflow."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pytest.yml"
README = ROOT / "README.md"
JOB = "legacy-admin-browser:"


def _legacy_admin_browser_pytest_runs() -> list[str]:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == JOB)
    job_indent = len(lines[start]) - len(lines[start].lstrip())
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and (len(line) - len(line.lstrip())) <= job_indent:
            break
        body.append(line)
    runs = [line.split("run:", 1)[1].strip() for line in body if line.strip().startswith("run:") and "pytest" in line]
    assert len(runs) == 2, runs
    return runs


def test_readme_legacy_admin_browser_command_matches_workflow() -> None:
    commands = _legacy_admin_browser_pytest_runs()
    readme = README.read_text(encoding="utf-8")
    section = readme.split("**`legacy-admin-browser` job**", 1)[1]
    for command in commands:
        # Local copy (env prefix + command) and the sentence that quotes the workflow run line.
        assert readme.count(command) >= 2
        assert command in section
