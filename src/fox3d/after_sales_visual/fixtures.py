from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import AfterSalesCase, CatalogSnapshot, Observation, PhotoEvidence


def fixture_manifest_path() -> Path:
    return Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "after_sales_visual" / "manifest.json"


def load_fixture_manifest(path: Path | None = None) -> dict:
    value = json.loads((path or fixture_manifest_path()).read_text(encoding="utf-8"))
    if value.get("schema_version") != "fox3d.after-sales-visual.dataset.v1" or len(value.get("cases", [])) < 24:
        raise ValueError("after-sales fixture manifest must contain at least 24 versioned cases")
    if any(row.get("source_class") != "SYNTHETIC_FIXTURE" for row in value["cases"]):
        raise ValueError("unapproved real customer data is forbidden")
    return value


def case_from_fixture(row: dict) -> AfterSalesCase:
    case_id = row["case_id"]
    image_hash = hashlib.sha256(f"synthetic-photo:{case_id}".encode()).hexdigest()
    derived_hash = hashlib.sha256(f"deidentified:{case_id}".encode()).hexdigest()
    hash_for = lambda label: hashlib.sha256(f"{label}:{row.get('version', 'ENG-V1')}".encode()).hexdigest()
    step = row.get("manual_step_id", "STEP-01")
    catalog = CatalogSnapshot(
        tenant_id=row.get("catalog_tenant", row.get("tenant_id", "tenant-a")),
        company_id=row.get("catalog_company", row.get("company_id", "company-a")),
        sku=row.get("catalog_sku", row.get("requested_sku", "SKU-A")),
        product_family_id="fixture.family.cabinet",
        engineering_version=row.get("catalog_version", row.get("version", "ENG-V1")),
        engineering_hash=hash_for("engineering"),
        bom_hash=hash_for("bom"),
        artwork_hash=hashlib.sha256(f"artwork:{case_id}".encode()).hexdigest(),
        manual_hash=hash_for("manual"),
        approval_ref=row.get("approval_ref", "TEST-APPROVAL:fixture-v1"),
        approval_status=row.get("approval_status", "TEST_APPROVAL"),
        bom_scope=row.get("bom_scope", "TEST_APPROVAL"),
        erp_binding=row.get("erp_binding", "TEST_APPROVAL"),
        source_revision=row.get("source_revision", "fixture-rev-1"),
        production_ready=False,
        assembly={
            "instructionsV2": {"steps": [{"id": "STEP-01", "title": "既有組裝步驟 1"}, {"id": "STEP-02", "title": "既有組裝步驟 2"}]},
            "partLabels": [{"partId": "PANEL-L"}, {"partId": "SCREW-A"}],
            "cartonContents": [{"partId": "SCREW-A", "quantity": 4}],
            "misassembly": {"source": "fox3d.kd.misassembly_risk"},
        },
    )
    observations = [Observation.model_validate(item) for item in row.get("observations", [{
        "kind": "CORRECT_ASSEMBLY", "confidence": 0.8, "evidence_refs": ["synthetic:region-1"]
    }])]
    return AfterSalesCase(
        case_id=case_id,
        tenant_id=row.get("tenant_id", "tenant-a"),
        company_id=row.get("company_id", "company-a"),
        requested_sku=row.get("requested_sku", "SKU-A"),
        requested_engineering_version=row.get("version", "ENG-V1"),
        photo_claimed_sku=row.get("photo_claimed_sku"),
        photo=PhotoEvidence(
            original_sha256=image_hash,
            derived_sha256=derived_hash,
            media_type="application/x.synthetic-observation+json",
            size_bytes=128,
            width=64,
            height=64,
            exif_removed=True,
            source_class="SYNTHETIC_FIXTURE",
        ),
        catalog=catalog,
        observations=observations,
        human_inventory_verified=bool(row.get("human_inventory_verified", False)),
        source_class="SYNTHETIC_FIXTURE",
    )
