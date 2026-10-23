from __future__ import annotations

from typing import Any, cast

from .models import ApprovalStatus, BomScope, CatalogSnapshot, ErpBinding, canonical_hash


def adapt_product_dna_snapshot(
    payload: dict[str, Any],
    *,
    tenant_id: str,
    company_id: str,
    sku: str,
    assembly: dict[str, Any],
    approval: dict[str, str] | None = None,
) -> CatalogSnapshot:
    """Adapt an already-fetched Product DNA export without live DB/API access.

    Product DNA's current UNBOUND/candidate truth stays blocked unless a separate
    explicit approval snapshot is supplied.  The adapter never chooses a latest
    version and never mutates Product DNA or ERP.
    """
    twins = payload.get("twins") or []
    twin = next((row for row in twins if row.get("sku") == sku), None)
    if twin is None:
        raise ValueError("exact SKU is absent from the Product DNA snapshot")
    hashes = twin.get("hashes") or {}
    engineering_version = str(twin.get("engineeringVersion") or payload.get("engineeringVersion") or "")
    if not engineering_version:
        raise ValueError("engineering version is required; latest fallback is forbidden")
    engineering_hash = str(hashes.get("engineeringHash") or payload.get("engineeringHash") or "")
    bom_hash = str(hashes.get("bomHash") or payload.get("bomHash") or "")
    artwork_hash = str(hashes.get("artworkHash") or "")
    refs = list(payload.get("sourceRefs") or []) + list(twin.get("sourceRefs") or [])
    erp_unbound = any(row.get("system") == "ERP" and row.get("binding") == "UNBOUND" for row in refs)
    truth = twin.get("truth") or payload.get("truth") or {}
    current_candidate = (
        hashes.get("bomScope") == "CANDIDATE_ONLY_NOT_A_CUT_LIST"
        or truth.get("engineeringReady") is False
        or truth.get("manufacturingReady") is False
        or erp_unbound
    )
    if approval is None:
        approval_status: ApprovalStatus = "UNBOUND" if erp_unbound else "CANDIDATE"
        approval_ref: str | None = None
        bom_scope: BomScope = "CANDIDATE_ONLY_NOT_A_CUT_LIST"
        erp_binding: ErpBinding = "UNBOUND" if erp_unbound else "BOUND_READONLY"
        source_revision = str(payload.get("contentHash") or "product-dna-candidate")
    else:
        # CatalogSnapshot remains the runtime validator for this untrusted boundary;
        # these casts only preserve its Literal contract for static analysis.
        approval_status = cast(ApprovalStatus, approval["approval_status"])
        approval_ref = approval["approval_ref"]
        bom_scope = cast(BomScope, approval["bom_scope"])
        erp_binding = cast(ErpBinding, approval["erp_binding"])
        source_revision = approval["source_revision"]
    if current_candidate and approval_status == "APPROVED" and not approval_ref:
        raise ValueError("candidate Product DNA cannot be silently promoted")
    return CatalogSnapshot(
        tenant_id=tenant_id,
        company_id=company_id,
        sku=sku,
        product_family_id=str(twin.get("familyId") or payload.get("familyId") or ""),
        engineering_version=engineering_version,
        engineering_hash=engineering_hash,
        bom_hash=bom_hash,
        artwork_hash=artwork_hash,
        manual_hash=canonical_hash(assembly.get("instructionsV2") or {}),
        approval_ref=approval_ref,
        approval_status=approval_status,
        bom_scope=bom_scope,
        erp_binding=erp_binding,
        source_revision=source_revision,
        production_ready=False,
        assembly=assembly,
    )
