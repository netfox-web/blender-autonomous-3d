from __future__ import annotations

from typing import Protocol

from .models import (
    AfterSalesCase,
    AfterSalesResult,
    Candidate,
    CaptureRequest,
    HumanDecision,
    Observation,
    ReplacementDraft,
    ReplacementLine,
    ResultStatus,
    canonical_hash,
)


class ObservationProvider(Protocol):
    evidence_class: str

    def observe(self, case: AfterSalesCase) -> list[Observation]: ...


class FixtureObservationProvider:
    evidence_class = "MOCK_REGRESSION"

    def observe(self, case: AfterSalesCase) -> list[Observation]:
        return list(case.observations)


class DisabledVisualModelAdapter:
    evidence_class = "REAL_INTEGRATION_NOT_RUN"

    def observe(self, case: AfterSalesCase) -> list[Observation]:
        raise RuntimeError("visual model adapter is disabled; no GPU or paid API is permitted")


def _approval_block(case: AfterSalesCase) -> str | None:
    c = case.catalog
    if c.tenant_id != case.tenant_id or c.company_id != case.company_id:
        return "catalog tenant/company does not match the case"
    if c.sku != case.requested_sku or c.engineering_version != case.requested_engineering_version:
        return "requested SKU or engineering version does not match the snapshot"
    if case.photo_claimed_sku is not None and case.photo_claimed_sku != case.requested_sku:
        return "photo claim and requested SKU conflict"
    if c.approval_status == "TEST_APPROVAL":
        if case.source_class != "SYNTHETIC_FIXTURE" or c.bom_scope != "TEST_APPROVAL" or c.erp_binding != "TEST_APPROVAL":
            return "TEST_APPROVAL is only valid for an explicitly synthetic fixture"
    elif c.approval_status != "APPROVED":
        return "approval provenance is missing, expired, candidate or unbound"
    if not c.approval_ref:
        return "approval reference is required"
    if c.bom_scope not in {"APPROVED_SERVICE_BOM", "TEST_APPROVAL"}:
        return "candidate BOM cannot produce service advice"
    if c.erp_binding not in {"BOUND_READONLY", "TEST_APPROVAL"}:
        return "ERP binding is unbound"
    return None


def _manual_steps(case: AfterSalesCase) -> dict[str, dict]:
    rows = case.catalog.assembly["instructionsV2"].get("steps") or []
    indexed = {}
    for row in rows:
        key = row.get("id") if row.get("id") is not None else row.get("step")
        if key is not None:
            indexed[str(key)] = row
    return indexed


def analyze_case(case: AfterSalesCase, provider: ObservationProvider | None = None) -> AfterSalesResult:
    observations = (provider or FixtureObservationProvider()).observe(case)
    input_hash = case.input_hash()
    base_provenance = {
        "source_class": case.source_class,
        "catalog_revision": case.catalog.source_revision,
        "engineering_hash": case.catalog.engineering_hash,
        "bom_hash": case.catalog.bom_hash,
        "artwork_hash": case.catalog.artwork_hash,
        "manual_hash": case.catalog.manual_hash,
        "photo_original_hash": case.photo.original_sha256,
        "photo_derived_hash": case.photo.derived_sha256,
    }
    identity_fields = (
        case.catalog.tenant_id != case.tenant_id,
        case.catalog.company_id != case.company_id,
        case.catalog.sku != case.requested_sku,
        case.catalog.engineering_version != case.requested_engineering_version,
        case.photo_claimed_sku is not None and case.photo_claimed_sku != case.requested_sku,
    )
    block = _approval_block(case)
    status: ResultStatus
    if block:
        status = "BLOCKED_VERSION_OR_IDENTITY" if any(identity_fields) else "BLOCKED_APPROVAL_PROVENANCE"
        candidate_set_id = canonical_hash({"case": case.case_id, "input": input_hash, "status": status})
        return AfterSalesResult(
            case_id=case.case_id,
            candidate_set_id=candidate_set_id,
            input_hash=input_hash,
            status=status,
            candidates=[],
            capture_requests=[],
            warnings=[block],
            safety_actions=[],
            replacement_draft_eligible=False,
            provenance=base_provenance,
        )

    steps = _manual_steps(case)
    candidates: list[Candidate] = []
    captures: list[CaptureRequest] = []
    warnings: list[str] = []
    safety: list[str] = []
    saw_unknown = False
    saw_safety = False
    for index, obs in enumerate(observations):
        if obs.kind == "PROMPT_TEXT":
            warnings.append("image text was retained as evidence text and ignored as an instruction")
            continue
        if obs.kind in {"NO_PRODUCT", "MULTIPLE_PRODUCTS"}:
            saw_unknown = True
            captures.append(CaptureRequest(
                request_id=canonical_hash({"case": case.case_id, "i": index, "kind": obs.kind})[:24],
                reason="商品無法唯一辨識",
                requested_view="請在充足光線下拍攝單一商品全景與 SKU 標籤",
            ))
            continue
        if obs.kind == "STRUCTURAL_DAMAGE":
            saw_safety = True
            safety.extend(["停止使用並避免承重", "轉人工安全核對；本系統不判定結構安全"])
            continue
        if obs.kind == "ORIENTATION_MISMATCH":
            if not obs.part_id or not obs.manual_step_id or obs.manual_step_id not in steps:
                warnings.append("orientation observation lacks a valid existing manual step reference")
                continue
            candidate_id = canonical_hash({"case": case.case_id, "kind": obs.kind, "part": obs.part_id, "step": obs.manual_step_id})[:24]
            candidates.append(Candidate(
                candidate_id=candidate_id,
                kind="MISASSEMBLY_CANDIDATE",
                part_id=obs.part_id,
                manual_step_id=obs.manual_step_id,
                confidence=obs.confidence,
                support=list(obs.evidence_refs),
                counter_evidence=["single-view orientation can be ambiguous"],
                requires_human_review=True,
            ))
            continue
        if obs.kind == "VISIBLE_COUNT" and obs.expected_count is not None and obs.visible_count is not None:
            if obs.visible_count >= obs.expected_count:
                continue
            if not obs.part_id or not obs.manual_step_id or obs.manual_step_id not in steps:
                warnings.append("count observation lacks a valid existing manual step reference")
                continue
            if obs.occluded or not case.human_inventory_verified:
                captures.append(CaptureRequest(
                    request_id=canonical_hash({"case": case.case_id, "i": index, "part": obs.part_id})[:24],
                    reason="照片未見不等於缺件；數量尚未由人工盤點確認",
                    requested_view=f"請攤開 {obs.part_id} 並連同包裝標籤及全部數量補拍",
                ))
            else:
                candidate_id = canonical_hash({"case": case.case_id, "kind": obs.kind, "part": obs.part_id, "step": obs.manual_step_id})[:24]
                candidates.append(Candidate(
                    candidate_id=candidate_id,
                    kind="MISSING_PART_CANDIDATE",
                    part_id=obs.part_id,
                    manual_step_id=obs.manual_step_id,
                    confidence=obs.confidence,
                    support=list(obs.evidence_refs) + ["human inventory count explicitly verified"],
                    counter_evidence=[],
                    requires_human_review=True,
                ))

    if saw_safety:
        status = "SAFETY_REVIEW_REQUIRED"
    elif saw_unknown:
        status = "UNKNOWN"
    elif captures:
        status = "NEEDS_MORE_EVIDENCE"
    elif candidates:
        status = "NEEDS_HUMAN_REVIEW"
    else:
        status = "NO_CANDIDATE"
    replacement_eligible = bool(candidates) and all(c.kind == "MISSING_PART_CANDIDATE" for c in candidates) and not captures and not saw_safety
    candidate_set_id = canonical_hash({
        "case": case.case_id,
        "input": input_hash,
        "candidates": [c.model_dump(mode="json") for c in candidates],
        "captures": [c.model_dump(mode="json") for c in captures],
        "status": status,
    })
    return AfterSalesResult(
        case_id=case.case_id,
        candidate_set_id=candidate_set_id,
        input_hash=input_hash,
        status=status,
        candidates=candidates,
        capture_requests=captures,
        warnings=warnings,
        safety_actions=safety,
        replacement_draft_eligible=replacement_eligible,
        provenance=base_provenance,
    )


def build_replacement_draft(case: AfterSalesCase, result: AfterSalesResult, decision: HumanDecision) -> ReplacementDraft:
    if result.input_hash != case.input_hash() or result.case_id != case.case_id:
        raise ValueError("candidate set is stale for this case input")
    if not result.replacement_draft_eligible or decision.decision not in {"ACCEPT", "AMEND"}:
        raise ValueError("an accepted missing-part candidate set is required")
    accepted = {candidate_id for candidate_id in decision.candidate_ids}
    lines = [
        ReplacementLine(part_id=c.part_id, quantity=1, engineering_version=case.catalog.engineering_version)
        for c in result.candidates
        if c.candidate_id in accepted and c.kind == "MISSING_PART_CANDIDATE"
    ]
    if not lines or not case.catalog.approval_ref:
        raise ValueError("no accepted candidate with approval provenance")
    draft_id = canonical_hash({"case": case.case_id, "candidate_set": result.candidate_set_id, "decision": decision.model_dump(mode="json")})[:24]
    return ReplacementDraft(
        draft_id=draft_id,
        case_id=case.case_id,
        tenant_id=case.tenant_id,
        company_id=case.company_id,
        sku=case.requested_sku,
        approval_ref=case.catalog.approval_ref,
        source_revision=case.catalog.source_revision,
        candidate_set_id=result.candidate_set_id,
        lines=lines,
        human_decision=decision,
    )
