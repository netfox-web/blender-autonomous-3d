"""run_prototype_validation_e2e fail-closed. MOCK/unit — not Production Ready."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fox3d.evidence import prepare_evidence_lineage

ROOT = Path(__file__).resolve().parents[1]
SHA = "c" * 40


def _load():
    path = ROOT / "scripts" / "run_prototype_validation_e2e.py"
    spec = importlib.util.spec_from_file_location("run_prototype_validation_e2e", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_prototype_validation_e2e"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _inspect(sha: str, *, clean: bool = True):
    def inspect(root, allow_dirty=False):
        porcelain = "" if clean else " M src/fox3d/prototype.py\n"
        return prepare_evidence_lineage(head_sha=sha, porcelain=porcelain, allow_dirty=allow_dirty)

    return inspect


class _FakePlat:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.mock_blender = True


def _passing(plat):
    return {
        "ok": True,
        "selected": [
            {"selectionId": f"s{i}", "candidateId": f"c{i}", "engineeringHash": f"e{i}", "truthLabel": "FIXTURE"}
            for i in range(4)
        ],
        "units": [
            {"prototypeUnitId": f"u{i}", "candidateId": f"c{i}", "engineeringHash": f"e{i}", "state": "WAITING_VALIDATION", "physicalPrototypeValidated": False}
            for i in range(4)
        ],
        "physicalPrototypeValidated": False,
        "demandLabel": "MOCK",
        "liveMachineControl": False,
        "media": [],
        "board": {"rows": []},
    }


def test_prototype_runner_binds_clean_head(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={"inspect": _inspect(SHA), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "scenario": _passing},
    )
    assert rc == 0
    body = json.loads((docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert body["ok"] is True
    assert body["physicalPrototypeValidated"] is False
    assert body["liveMachineControl"] is False
    assert (docs / "SKU_LAUNCH_READINESS_ACCEPTANCE.md").exists()


def test_prototype_runner_dirty_does_not_overwrite(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").write_text(json.dumps({"ok": True, "keep": True}), encoding="utf-8")
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={"inspect": _inspect(SHA, clean=False), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "scenario": _passing},
    )
    assert rc != 0
    kept = json.loads((docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert kept.get("keep") is True


def test_prototype_runner_mismatch_refuses(tmp_path):
    mod = _load()
    docs = tmp_path / "docs"
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", "d" * 40],
        hooks={"inspect": _inspect(SHA), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "scenario": _passing},
    )
    assert rc != 0
    assert not (docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").exists()


def test_prototype_runner_fixture_physical_fails(tmp_path):
    mod = _load()

    def scenario(plat):
        body = _passing(plat)
        body["physicalPrototypeValidated"] = True
        return body

    docs = tmp_path / "docs"
    rc = mod.main(
        ["--docs-root", str(docs), "--expected-commit", SHA],
        hooks={"inspect": _inspect(SHA), "acceptance_root": tmp_path / "acc", "platform": _FakePlat, "scenario": scenario},
    )
    assert rc != 0
    assert not (docs / "PROTOTYPE_VALIDATION_ACCEPTANCE.json").exists()
