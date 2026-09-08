"""Fail-closed REAL acceptance gate regressions. MOCK/unit — not Production Ready."""

from __future__ import annotations

import json

import pytest

from fox3d.acceptance_gate import (
    CANONICAL_REAL_FILES,
    aggregate_canonical_consistency,
    read_canonical_truth_set,
    required_real_acceptance_ok,
    write_canonical_if_ok,
)
from fox3d.evidence import DirtyTreeError, evidence_bundle, prepare_evidence_lineage, verify_bundle
from fox3d.ids import sha256_bytes


SHA = "d7a3075a2b0e621d748de949c0b7244bf5825c55"


def _preview(tmp_path, *, i: int, sha: str = SHA, commit: str | None = None, used_mock: bool = False, real_blender: bool = True, corrupt_hash: bool = False):
    art = tmp_path / f"p{i}.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
    digest = sha256_bytes(art.read_bytes())
    job = {
        "jobId": f"j{i}",
        "usedMock": used_mock,
        "realBlender": real_blender,
        "status": "completed",
        "outputHash": digest,
        "outputSize": art.stat().st_size,
        "blenderVersion": "5.2.1",
    }
    bun = evidence_bundle(commit_sha=commit or sha, job=job, artifact_path=art, engineering_hash="e", bom_hash="b")
    if corrupt_hash:
        bun["artifactHash"] = "0" * 64
    ver = verify_bundle(bun, require_real=True, expected_commit_sha=sha)
    label = "REAL" if ver["ok"] and not used_mock and real_blender else "PARTIAL"
    return {"label": label, "verify": ver, "bundle": bun, "usedMock": used_mock, "realBlender": real_blender}


def _lineage(clean: bool = True, allow_dirty: bool = False):
    porcelain = "" if clean else " M src/fox3d/evidence.py\n"
    return prepare_evidence_lineage(head_sha=SHA, porcelain=porcelain, allow_dirty=allow_dirty)


def _gate(previews, **kwargs):
    base = dict(
        lineage=_lineage(True),
        blender_real=True,
        optix_real=True,
        previews=previews,
        export_state="APPROVED_FOR_EXPORT",
        stale=True,
        live_cnc_blocked=True,
        live_laser_blocked=True,
        expected_commit=SHA,
    )
    base.update(kwargs)
    return required_real_acceptance_ok(**base)


def test_five_valid_real_bundles_pass(tmp_path):
    previews = [_preview(tmp_path, i=i) for i in range(5)]
    result = _gate(previews)
    assert result["ok"] is True
    sentinel = tmp_path / "PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE.json"
    sentinel.write_text("KEEP", encoding="utf-8")
    written = write_canonical_if_ok(tmp_path, {"PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE": {"ok": True}}, ok=True)
    assert written
    assert json.loads(sentinel.read_text(encoding="utf-8"))["ok"] is True


def test_stale_commit_fails_and_does_not_write(tmp_path):
    previews = [_preview(tmp_path, i=i, commit="b9e7861be28c6f94a1bc7c985c77877b98b70720") for i in range(5)]
    result = _gate(previews)
    assert result["ok"] is False
    assert any("commit_mismatch" in f or "verify_fail" in f or "not_real" in f for f in result["failures"])
    sentinel = tmp_path / "PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE.json"
    sentinel.write_text("KEEP", encoding="utf-8")
    written = write_canonical_if_ok(tmp_path, {"PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE": {"ok": True}}, ok=result["ok"])
    assert written == []
    assert sentinel.read_text(encoding="utf-8") == "KEEP"


def test_hash_mismatch_fails_and_does_not_write(tmp_path):
    previews = [_preview(tmp_path, i=i, corrupt_hash=(i == 2)) for i in range(5)]
    result = _gate(previews)
    assert result["ok"] is False
    assert any("verify_fail" in f or "not_real" in f for f in result["failures"])
    sentinel = tmp_path / "RELEASE_GATE_REAL_ACCEPTANCE.json"
    sentinel.write_text("KEEP", encoding="utf-8")
    assert write_canonical_if_ok(tmp_path, {"RELEASE_GATE_REAL_ACCEPTANCE": {}}, ok=result["ok"]) == []
    assert sentinel.read_text(encoding="utf-8") == "KEEP"


def test_used_mock_or_not_real_blender_fails(tmp_path):
    previews = [_preview(tmp_path, i=i, used_mock=(i == 1)) for i in range(5)]
    result = _gate(previews)
    assert result["ok"] is False
    previews2 = [_preview(tmp_path, i=i, real_blender=(i != 3)) for i in range(5)]
    result2 = _gate(previews2)
    assert result2["ok"] is False


def test_four_of_five_previews_fails(tmp_path):
    previews = [_preview(tmp_path, i=i) for i in range(4)]
    result = _gate(previews)
    assert result["ok"] is False
    assert any(f.startswith("preview_count_") for f in result["failures"])


def test_dirty_tree_without_override_raises():
    with pytest.raises(DirtyTreeError):
        prepare_evidence_lineage(head_sha=SHA, porcelain=" M x.py\n", allow_dirty=False)


def test_allow_dirty_unverified_nonzero_no_canonical_write(tmp_path):
    lineage = _lineage(clean=False, allow_dirty=True)
    assert lineage["label"] == "UNVERIFIED"
    previews = [_preview(tmp_path, i=i) for i in range(5)]
    result = _gate(previews, lineage=lineage)
    assert result["ok"] is False
    assert "real_acceptance_not_allowed" in result["failures"] or "working_tree_dirty" in result["failures"]
    sentinel = tmp_path / "PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE.json"
    sentinel.write_text("KEEP", encoding="utf-8")
    assert write_canonical_if_ok(tmp_path, {"PHYSICAL_PRODUCT_OS_V2_ACCEPTANCE": {"ok": True}}, ok=result["ok"]) == []
    assert sentinel.read_text(encoding="utf-8") == "KEEP"


def test_live_machine_not_blocked_fails(tmp_path):
    previews = [_preview(tmp_path, i=i) for i in range(5)]
    assert _gate(previews, live_cnc_blocked=False)["ok"] is False
    assert _gate(previews, live_laser_blocked=False)["ok"] is False
    assert "live_cnc_not_blocked" in _gate(previews, live_cnc_blocked=False)["failures"]
    assert "live_laser_not_blocked" in _gate(previews, live_laser_blocked=False)["failures"]


def _write_canonical(docs, *, gen="g1", commit="c1", skip=None, extra=None):
    docs.mkdir(parents=True, exist_ok=True)
    for name in CANONICAL_REAL_FILES:
        if skip == name:
            continue
        payload = {"acceptanceGenerationId": gen, "evidenceCodeCommit": commit, "domain": name}
        if extra and name in extra:
            payload.update(extra[name])
        (docs / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_canonical_reader_accepts_same_generation_and_commit(tmp_path):
    _write_canonical(tmp_path, gen="gen-a", commit="sha-a")
    result = read_canonical_truth_set(tmp_path)
    assert result["ok"] is True
    assert result["acceptanceGenerationId"] == "gen-a"
    assert result["evidenceCodeCommit"] == "sha-a"
    assert set(result["payloads"]) == set(CANONICAL_REAL_FILES)
    agg = aggregate_canonical_consistency(tmp_path)
    assert agg["canonicalTruthSetOk"] is True
    assert agg["secondAcceptanceSystem"] is False


def test_canonical_reader_rejects_mixed_generation(tmp_path):
    _write_canonical(tmp_path, gen="gen-a", commit="sha-a")
    mixed = json.loads((tmp_path / "NESTING_V3_ACCEPTANCE.json").read_text(encoding="utf-8"))
    mixed["acceptanceGenerationId"] = "gen-b"
    (tmp_path / "NESTING_V3_ACCEPTANCE.json").write_text(json.dumps(mixed), encoding="utf-8")
    result = read_canonical_truth_set(tmp_path)
    assert result["ok"] is False
    assert "mixed_generation" in result["errors"]
    assert any(e.startswith("generation_mismatch:") for e in result["errors"])


def test_canonical_reader_rejects_mixed_commit(tmp_path):
    _write_canonical(tmp_path, gen="gen-a", commit="sha-a")
    mixed = json.loads((tmp_path / "COMMERCIAL_COST_ACCEPTANCE.json").read_text(encoding="utf-8"))
    mixed["evidenceCodeCommit"] = "sha-b"
    (tmp_path / "COMMERCIAL_COST_ACCEPTANCE.json").write_text(json.dumps(mixed), encoding="utf-8")
    result = read_canonical_truth_set(tmp_path)
    assert result["ok"] is False
    assert "mixed_commit" in result["errors"]


def test_canonical_reader_rejects_missing_and_malformed(tmp_path):
    _write_canonical(tmp_path, skip="PACKAGING_V2_ACCEPTANCE")
    result = read_canonical_truth_set(tmp_path)
    assert result["ok"] is False
    assert "missing:PACKAGING_V2_ACCEPTANCE" in result["errors"]
    (tmp_path / "PACKAGING_V2_ACCEPTANCE.json").write_text("KEEP-OLD", encoding="utf-8")
    bad = read_canonical_truth_set(tmp_path)
    assert bad["ok"] is False
    assert "malformed:PACKAGING_V2_ACCEPTANCE" in bad["errors"]
