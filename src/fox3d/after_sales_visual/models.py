from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

HASH_RE = re.compile(r"^[a-f0-9]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

PhotoMediaType = Literal["image/png", "image/jpeg", "application/x.synthetic-observation+json"]
SourceClass = Literal["SYNTHETIC_FIXTURE", "APPROVED_DEIDENTIFIED"]
ApprovalStatus = Literal["APPROVED", "TEST_APPROVAL", "CANDIDATE", "UNBOUND", "EXPIRED"]
BomScope = Literal["APPROVED_SERVICE_BOM", "TEST_APPROVAL", "CANDIDATE_ONLY_NOT_A_CUT_LIST"]
ErpBinding = Literal["BOUND_READONLY", "TEST_APPROVAL", "UNBOUND"]
ResultStatus = Literal[
    "NO_CANDIDATE",
    "NEEDS_HUMAN_REVIEW",
    "NEEDS_MORE_EVIDENCE",
    "UNKNOWN",
    "BLOCKED_VERSION_OR_IDENTITY",
    "BLOCKED_APPROVAL_PROVENANCE",
    "SAFETY_REVIEW_REQUIRED",
]


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PhotoEvidence(StrictModel):
    original_sha256: str
    derived_sha256: str
    media_type: PhotoMediaType
    size_bytes: int = Field(ge=1, le=12_000_000)
    width: int = Field(ge=1, le=12_000)
    height: int = Field(ge=1, le=12_000)
    exif_removed: bool
    source_class: SourceClass

    @model_validator(mode="after")
    def valid_hashes(self):
        if not HASH_RE.fullmatch(self.original_sha256) or not HASH_RE.fullmatch(self.derived_sha256):
            raise ValueError("photo hashes must be lowercase SHA-256")
        return self


class CatalogSnapshot(StrictModel):
    tenant_id: str
    company_id: str
    sku: str
    product_family_id: str
    engineering_version: str
    engineering_hash: str
    bom_hash: str
    artwork_hash: str
    manual_hash: str
    approval_ref: str | None
    approval_status: ApprovalStatus
    bom_scope: BomScope
    erp_binding: ErpBinding
    source_revision: str
    production_ready: Literal[False] = False
    assembly: dict[str, Any]

    @model_validator(mode="after")
    def validate_snapshot(self):
        for value in (self.tenant_id, self.company_id, self.sku, self.engineering_version, self.source_revision):
            if not ID_RE.fullmatch(value):
                raise ValueError("catalog identity contains unsupported characters")
        for value in (self.engineering_hash, self.bom_hash, self.artwork_hash, self.manual_hash):
            if not HASH_RE.fullmatch(value):
                raise ValueError("catalog hashes must be lowercase SHA-256")
        instructions = self.assembly.get("instructionsV2")
        if not isinstance(instructions, dict) or not isinstance(instructions.get("steps"), list):
            raise ValueError("existing instructionsV2 snapshot is required")
        return self


class Observation(StrictModel):
    kind: Literal[
        "CORRECT_ASSEMBLY",
        "ORIENTATION_MISMATCH",
        "VISIBLE_COUNT",
        "NO_PRODUCT",
        "MULTIPLE_PRODUCTS",
        "STRUCTURAL_DAMAGE",
        "PROMPT_TEXT",
    ]
    part_id: str | None = None
    manual_step_id: str | None = None
    visible_count: int | None = Field(default=None, ge=0)
    expected_count: int | None = Field(default=None, ge=0)
    occluded: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[str]
    note: str | None = None


class AfterSalesCase(StrictModel):
    schema_version: Literal["fox3d.after-sales-visual.case.v1"] = "fox3d.after-sales-visual.case.v1"
    case_id: str
    tenant_id: str
    company_id: str
    requested_sku: str
    requested_engineering_version: str
    photo_claimed_sku: str | None = None
    photo: PhotoEvidence
    catalog: CatalogSnapshot
    observations: list[Observation]
    human_inventory_verified: bool = False
    source_class: SourceClass

    @model_validator(mode="after")
    def validate_identity(self):
        for value in (self.case_id, self.tenant_id, self.company_id, self.requested_sku, self.requested_engineering_version):
            if not ID_RE.fullmatch(value):
                raise ValueError("case identity contains unsupported characters")
        if self.source_class != self.photo.source_class:
            raise ValueError("case and photo source classes differ")
        return self

    def input_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class Candidate(StrictModel):
    candidate_id: str
    kind: Literal["MISASSEMBLY_CANDIDATE", "MISSING_PART_CANDIDATE"]
    part_id: str
    manual_step_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_semantics: Literal["FIXTURE_RULE_SCORE_NOT_MODEL_ACCURACY"] = "FIXTURE_RULE_SCORE_NOT_MODEL_ACCURACY"
    support: list[str]
    counter_evidence: list[str]
    requires_human_review: Literal[True] = True


class CaptureRequest(StrictModel):
    request_id: str
    reason: str
    requested_view: str


class AfterSalesResult(StrictModel):
    schema_version: Literal["fox3d.after-sales-visual.result.v1"] = "fox3d.after-sales-visual.result.v1"
    case_id: str
    candidate_set_id: str
    input_hash: str
    status: ResultStatus
    candidates: list[Candidate]
    capture_requests: list[CaptureRequest]
    warnings: list[str]
    safety_actions: list[str]
    replacement_draft_eligible: bool
    provenance: dict[str, str]
    live_model_used: Literal[False] = False
    external_write_performed: Literal[False] = False
    structural_safety_determined: Literal[False] = False
    production_ready: Literal[False] = False


class HumanDecision(StrictModel):
    decision: Literal["ACCEPT", "REJECT", "AMEND"]
    actor_ref: str
    decided_at: str
    reason: str
    candidate_ids: list[str]


class ReplacementLine(StrictModel):
    part_id: str
    quantity: int = Field(ge=1)
    engineering_version: str
    requires_final_quantity_check: Literal[True] = True


class ReplacementDraft(StrictModel):
    schema_version: Literal["fox3d.after-sales-visual.erp-draft.v1"] = "fox3d.after-sales-visual.erp-draft.v1"
    draft_id: str
    case_id: str
    tenant_id: str
    company_id: str
    sku: str
    approval_ref: str
    source_revision: str
    candidate_set_id: str
    lines: list[ReplacementLine]
    status: Literal["DRAFT_NOT_SUBMITTED"] = "DRAFT_NOT_SUBMITTED"
    executable: Literal[False] = False
    external_write_performed: Literal[False] = False
    human_decision: HumanDecision
