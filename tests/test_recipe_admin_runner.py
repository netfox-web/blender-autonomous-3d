import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/run_recipe_admin_e2e.py"
spec = importlib.util.spec_from_file_location("recipe_admin_e2e", PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_live_http_workbench_and_restart(monkeypatch):
    monkeypatch.setattr(runner, "inspect_repo_lineage", lambda root: {"evidenceCodeCommit": "code"})
    report = runner.run("code")
    assert report["ok"] and len(report["checks"]) == 5
    assert report["executionMode"] == "LIVE_LOCAL_HTTP"
    assert not report["realBlenderAcceptance"]


def test_wrong_commit_stops_before_server(monkeypatch):
    monkeypatch.setattr(runner, "inspect_repo_lineage", lambda root: {"evidenceCodeCommit": "different"})
    with pytest.raises(ValueError, match="differs from HEAD"):
        runner.run("code")
