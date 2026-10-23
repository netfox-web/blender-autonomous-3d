from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from fox3d.after_sales_visual.engine import DisabledVisualModelAdapter, analyze_case, build_replacement_draft
from fox3d.after_sales_visual.fixtures import case_from_fixture, load_fixture_manifest
from fox3d.after_sales_visual.intake import PhotoIntakeError, intake_photo_bytes, read_local_fixture
from fox3d.after_sales_visual.models import HumanDecision
from fox3d.after_sales_visual.store import JsonCaseStore
from fox3d.after_sales_visual.batch import BatchInterrupted, FixtureBatchRunner

MANIFEST = load_fixture_manifest()


@pytest.mark.parametrize("row", MANIFEST["cases"], ids=lambda row: row["case_id"])
def test_golden_manifest(row):
    result = analyze_case(case_from_fixture(row))
    assert result.status == row["expected_status"]
    assert result.live_model_used is False
    assert result.external_write_performed is False
    assert result.structural_safety_determined is False
    assert result.production_ready is False


def test_same_input_has_stable_candidate_set():
    case = case_from_fixture(MANIFEST["cases"][1])
    assert analyze_case(case).candidate_set_id == analyze_case(case).candidate_set_id


def test_occluded_count_cannot_create_draft():
    case = case_from_fixture(MANIFEST["cases"][2])
    result = analyze_case(case)
    assert result.status == "NEEDS_MORE_EVIDENCE"
    assert result.replacement_draft_eligible is False


def test_verified_missing_part_produces_non_executable_draft():
    case = case_from_fixture(MANIFEST["cases"][3])
    result = analyze_case(case)
    decision = HumanDecision(
        decision="ACCEPT",
        actor_ref="fixture-reviewer",
        decided_at="2026-10-23T00:00:00Z",
        reason="fixture count reviewed",
        candidate_ids=[result.candidates[0].candidate_id],
    )
    draft = build_replacement_draft(case, result, decision)
    assert draft.status == "DRAFT_NOT_SUBMITTED"
    assert draft.executable is False
    assert draft.external_write_performed is False
    assert draft.lines[0].part_id == "SCREW-A"


def test_changed_input_invalidates_old_candidate_set():
    case = case_from_fixture(MANIFEST["cases"][3])
    result = analyze_case(case)
    changed = case.model_copy(update={"requested_engineering_version": "ENG-V2"})
    decision = HumanDecision(
        decision="ACCEPT", actor_ref="fixture-reviewer", decided_at="2026-10-23T00:00:00Z",
        reason="stale check", candidate_ids=[result.candidates[0].candidate_id]
    )
    with pytest.raises(ValueError, match="stale"):
        build_replacement_draft(changed, result, decision)


def test_disabled_real_provider_is_explicitly_not_run():
    case = case_from_fixture(MANIFEST["cases"][0])
    with pytest.raises(RuntimeError, match="disabled"):
        analyze_case(case, DisabledVisualModelAdapter())


def test_image_intake_strips_metadata_and_hashes_derivative():
    buffer = io.BytesIO()
    Image.new("RGB", (16, 12), color=(12, 34, 56)).save(buffer, format="JPEG", exif=b"Exif\x00\x00fixture")
    evidence, derived = intake_photo_bytes(buffer.getvalue(), source_class="SYNTHETIC_FIXTURE")
    assert evidence.exif_removed is True
    assert evidence.original_sha256 != evidence.derived_sha256
    assert derived.startswith(b"\x89PNG")


def test_image_intake_rejects_non_image_and_oversize():
    with pytest.raises(PhotoIntakeError):
        intake_photo_bytes(b"not an image", source_class="SYNTHETIC_FIXTURE")
    with pytest.raises(PhotoIntakeError):
        intake_photo_bytes(b"x" * 12_000_001, source_class="SYNTHETIC_FIXTURE")


def test_fixture_path_cannot_escape(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    inside = root / "photo.png"
    inside.write_bytes(b"fixture")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"fixture")
    assert read_local_fixture(inside, fixture_root=root) == b"fixture"
    with pytest.raises(PhotoIntakeError, match="escapes"):
        read_local_fixture(outside, fixture_root=root)


def test_store_is_idempotent_append_only_and_tenant_isolated(tmp_path: Path):
    case = case_from_fixture(MANIFEST["cases"][3])
    result = analyze_case(case)
    store = JsonCaseStore(tmp_path / "store")
    first = store.save_result(case.tenant_id, result)
    assert store.save_result(case.tenant_id, result) == first
    decision = HumanDecision(
        decision="ACCEPT", actor_ref="fixture-reviewer", decided_at="2026-10-23T00:00:00Z",
        reason="append only", candidate_ids=[result.candidates[0].candidate_id]
    )
    changed = store.append_decision(case.tenant_id, case.case_id, decision)
    repeated = store.append_decision(case.tenant_id, case.case_id, decision)
    assert len(changed["review_events"]) == 1
    assert repeated == changed
    with pytest.raises(FileNotFoundError):
        store.append_decision("tenant-b", case.case_id, decision)


def test_batch_interrupt_cancel_resume_and_retry(tmp_path: Path):
    runner = FixtureBatchRunner(tmp_path / "batch")
    with pytest.raises(BatchInterrupted):
        runner.run(MANIFEST, stop_after=5)
    cancelled = runner.cancel(MANIFEST)
    assert cancelled["status"] == "CANCELLED"
    completed = runner.run(MANIFEST, resume=True)
    assert completed["case_count"] == 24
    assert runner.run(MANIFEST, resume=True)["results"] == completed["results"]
