from __future__ import annotations

import io
import tempfile
from pathlib import Path

from PIL import Image

from fox3d.after_sales_visual.catalog import adapt_product_dna_snapshot
from fox3d.after_sales_visual.engine import DisabledVisualModelAdapter, analyze_case, build_replacement_draft
from fox3d.after_sales_visual.fixtures import case_from_fixture, load_fixture_manifest
from fox3d.after_sales_visual.intake import PhotoIntakeError, intake_photo_bytes, read_local_fixture
from fox3d.after_sales_visual.models import HumanDecision
from fox3d.after_sales_visual.store import JsonCaseStore
from fox3d.kd import assembly_instruction_v2, carton_contents_manifest, misassembly_risk, part_label_manifest
from fox3d.product_dna import project_manifest


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    manifest = load_fixture_manifest()
    product_dna = project_manifest("tenant-a")
    check(product_dna["skuCount"] == 3, "existing Product DNA SKU count")
    check(len({row["hashes"]["engineeringHash"] for row in product_dna["twins"]}) == 1, "shared engineering hash")
    check(len({row["hashes"]["artworkHash"] for row in product_dna["twins"]}) == 3, "artwork hash remains separate")
    check(product_dna["truth"]["engineeringReady"] is False and product_dna["truth"]["manufacturingReady"] is False, "candidate readiness remains false")

    graph = {
        "nodes": ["L_SIDE", "R_SIDE"],
        "steps": [{"step": 1, "parts": ["L_SIDE", "R_SIDE"], "hardware": ["CAM-A"], "tool": "hex_key"}],
        "twoPerson": False,
    }
    bom = {"lines": [
        {"partId": "L_SIDE", "partType": "side", "length": 900, "width": 300, "thickness": 15, "quantity": 1, "hardware": False},
        {"partId": "R_SIDE", "partType": "side", "length": 900, "width": 300, "thickness": 15, "quantity": 1, "hardware": False},
        {"partId": "CAM-A", "partType": "hardware", "quantity": 4, "hardware": True},
    ]}
    spec = {"productId": "fixture-cabinet", "revision": 1}
    instructions = assembly_instruction_v2(graph, spec, bom)
    labels = part_label_manifest(spec, bom, graph)
    cartons = carton_contents_manifest(spec, bom, {"length": 920, "width": 320, "height": 120})
    risk = misassembly_risk(spec, bom)
    check(instructions["version"] == 2 and instructions["source"] == "assembly_graph_v2", "existing instructionsV2 reused")
    check(len(labels["labels"]) == 2 and cartons["reconciled"] is True, "existing labels and carton contents reused")
    check(any(row["code"] == "LR_SIMILAR" for row in risk["warnings"]), "existing misassembly risk reused")
    results = {}
    for row in manifest["cases"]:
        result = analyze_case(case_from_fixture(row))
        check(result.status == row["expected_status"], f"{row['case_id']} status")
        check(result.live_model_used is False, "live model disabled")
        check(result.external_write_performed is False, "external writes disabled")
        check(result.structural_safety_determined is False, "no structural safety determination")
        results[row["case_id"]] = result

    repeat = analyze_case(case_from_fixture(manifest["cases"][23]))
    check(repeat.candidate_set_id == results["ASV-024"].candidate_set_id, "deterministic candidate set")
    check(results["ASV-003"].replacement_draft_eligible is False, "occlusion blocks draft")

    case = case_from_fixture(manifest["cases"][3])
    result = results["ASV-004"]
    decision = HumanDecision(
        decision="ACCEPT",
        actor_ref="fixture-reviewer",
        decided_at="2026-10-23T00:00:00Z",
        reason="synthetic fixture count reviewed",
        candidate_ids=[result.candidates[0].candidate_id],
    )
    draft = build_replacement_draft(case, result, decision)
    check(draft.status == "DRAFT_NOT_SUBMITTED" and draft.executable is False, "non-executable draft")
    check(draft.external_write_performed is False, "draft has no write")

    orientation = case_from_fixture(manifest["cases"][1])
    existing_step_case = orientation.model_copy(update={
        "catalog": orientation.catalog.model_copy(update={"assembly": {**orientation.catalog.assembly, "instructionsV2": instructions}}),
        "observations": [orientation.observations[0].model_copy(update={"manual_step_id": "1"})],
    })
    check(analyze_case(existing_step_case).status == "NEEDS_HUMAN_REVIEW", "numeric existing instructionsV2 step reference")

    unbound = adapt_product_dna_snapshot(
        {
            "familyId": "fixture.family.cabinet",
            "engineeringVersion": "ENG-V1",
            "sourceRefs": [{"system": "ERP", "binding": "UNBOUND"}],
            "truth": {"engineeringReady": False, "manufacturingReady": False},
            "contentHash": "candidate-revision",
            "twins": [{
                "sku": "SKU-A", "familyId": "fixture.family.cabinet", "engineeringVersion": "ENG-V1",
                "hashes": {
                    "engineeringHash": case.catalog.engineering_hash,
                    "bomHash": case.catalog.bom_hash,
                    "artworkHash": case.catalog.artwork_hash,
                    "bomScope": "CANDIDATE_ONLY_NOT_A_CUT_LIST",
                },
            }],
        },
        tenant_id=case.tenant_id,
        company_id=case.company_id,
        sku=case.requested_sku,
        assembly=case.catalog.assembly,
    )
    blocked = analyze_case(case.model_copy(update={"catalog": unbound}))
    check(blocked.status == "BLOCKED_APPROVAL_PROVENANCE", "UNBOUND Product DNA remains blocked")

    changed = case.model_copy(update={"requested_engineering_version": "ENG-V2"})
    try:
        build_replacement_draft(changed, result, decision)
        raise AssertionError("stale result accepted")
    except ValueError as error:
        check("stale" in str(error), "stale reason")

    try:
        analyze_case(case, DisabledVisualModelAdapter())
        raise AssertionError("disabled provider executed")
    except RuntimeError as error:
        check("disabled" in str(error), "provider disabled reason")

    buffer = io.BytesIO()
    Image.new("RGB", (16, 12), color=(12, 34, 56)).save(buffer, format="JPEG")
    evidence, derived = intake_photo_bytes(buffer.getvalue(), source_class="SYNTHETIC_FIXTURE")
    check(evidence.original_sha256 != evidence.derived_sha256 and derived.startswith(b"\x89PNG"), "image hashes")
    try:
        intake_photo_bytes(b"not an image", source_class="SYNTHETIC_FIXTURE")
        raise AssertionError("invalid image accepted")
    except PhotoIntakeError:
        pass

    with tempfile.TemporaryDirectory(prefix="fox3d-after-sales-") as temp:
        root = Path(temp)
        fixture_root = root / "fixtures"
        fixture_root.mkdir()
        inside = fixture_root / "photo.png"
        inside.write_bytes(b"fixture")
        outside = root / "outside.png"
        outside.write_bytes(b"fixture")
        check(read_local_fixture(inside, fixture_root=fixture_root) == b"fixture", "fixture read")
        try:
            read_local_fixture(outside, fixture_root=fixture_root)
            raise AssertionError("path escape accepted")
        except PhotoIntakeError:
            pass
        symlink = fixture_root / "link.png"
        try:
            symlink.symlink_to(inside)
            try:
                read_local_fixture(symlink, fixture_root=fixture_root)
                raise AssertionError("symlink fixture accepted")
            except PhotoIntakeError:
                pass
        except OSError:
            pass

        store = JsonCaseStore(root / "store")
        first = store.save_result(case.tenant_id, result)
        check(store.save_result(case.tenant_id, result) == first, "store retry idempotent")
        reviewed = store.append_decision(case.tenant_id, case.case_id, decision)
        reviewed_again = store.append_decision(case.tenant_id, case.case_id, decision)
        check(len(reviewed["review_events"]) == 1 and reviewed == reviewed_again, "review append idempotent")
        try:
            store.append_decision("tenant-b", case.case_id, decision)
            raise AssertionError("cross tenant evidence read accepted")
        except FileNotFoundError:
            pass

    print({
        "suite": "after_sales_visual",
        "evidence_class": "REAL_CPU_SANDBOX_ON_SYNTHETIC_FIXTURES",
        "cases": len(manifest["cases"]),
        "status": "PASS",
        "live_model": "NOT_RUN",
        "external_writes": 0,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
