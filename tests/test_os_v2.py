"""Phase 241–300 commercialization hardening. Mock blender — not production ready."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.commerce import mixed_landed_cost, quote_binding, quote_stale, supplier_alternatives
from fox3d.evidence import evidence_bundle, verify_bundle
from fox3d.ids import sha256_bytes
from fox3d.ops import assert_job_paths_safe
from fox3d.packv2 import (
    artwork_preflight,
    barcode_zone,
    board_grade,
    box_compression_estimate,
    carton_optimize,
    fit_regression,
    shipping_load_scenario,
    validate_bleed,
    validate_dieline,
)
from fox3d.publish import CatalogRelease, ar_export_boundary, publication_package, web3d_manifest
from fox3d.rdloop import DemandRegistryV2, evidence_weighted_rank, import_outcomes, kpi_read_model, substitution_candidates
from fox3d.readiness import scoped_readiness, validate_truth_labels
from fox3d.release import ReleaseGate
from fox3d.safety import SafetyRuleRegistry, acrylic_risk, evaluate_product, furniture_stability, wall_anchor_warning
from fox3d.sandbox import SandboxRegistry, job_policy_manifest


def test_scoped_readiness_not_global(platform):
    m = scoped_readiness(evidence={"kd": True, "retail": True, "coreRender": True})
    assert m["kdPrototypeReady"] is True
    assert m["globalProductionReady"] is False
    assert m["fullAutonomousFactoryReady"] is False
    assert m["liveProviderReady"] is False
    assert m["machineControlReady"] is False
    phys = platform.physical.readiness()
    assert phys["globalProductionReady"] is False
    assert phys["fullAutonomousFactoryReady"] is False


def test_truth_label_validator():
    assert "MOCK_MARKED_REAL" in validate_truth_labels({"source": "MOCK", "label": "REAL"})
    assert "CONFIG_MARKED_LIVE_PROVIDER" in validate_truth_labels({"costSource": "CONFIG_ESTIMATE", "providerLabel": "LIVE_PROVIDER"})
    assert "BLOCKED_MACHINE_MARKED_READY" in validate_truth_labels({"liveMachineControl": True})
    assert "FULL_READY_WITH_BLOCKERS" in validate_truth_labels({"fullAutonomousFactoryReady": True, "demand": "MOCK"})
    assert validate_truth_labels({"source": "IMPORTED", "label": "IMPORTED", "fullAutonomousFactoryReady": False}) == []


def test_evidence_bundle_verifier(tmp_path):
    art = tmp_path / "beauty.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
    job = {"jobId": "j1", "worker": "w", "gpuUuid": "u", "blenderVersion": "5.2.1", "usedMock": False, "realBlender": True, "status": "completed", "outputHash": sha256_bytes(art.read_bytes()), "outputSize": art.stat().st_size}
    bun = evidence_bundle(commit_sha="abc", job=job, artifact_path=art, engineering_hash="e", bom_hash="b")
    ok = verify_bundle(bun)
    assert ok["ok"] is True
    bun_bad = dict(bun)
    bun_bad["usedMock"] = True
    assert verify_bundle(bun_bad)["ok"] is False
    bun_miss = dict(bun)
    bun_miss["artifactPath"] = str(tmp_path / "nope.png")
    assert "artifact_missing" in verify_bundle(bun_miss)["errors"]


def test_approval_audit_and_stale(platform):
    rec = platform.kd.build_sku(tenant_id="t1", kind="BEDSIDE_CABINET")
    gate = platform.release
    ap = gate.advance(rec["spec"]["productId"], target="ENGINEERING_VALID", actor="ops", entity=rec, evidence_ok=True)
    assert ap["audit"]["immutable"] is True
    assert ap["audit"]["engineeringHash"] == rec["engineeringHash"]
    rec2 = dict(rec)
    rec2["engineeringHash"] = "changed"
    rec2["lineage"] = {**(rec.get("lineage") or {}), "engineeringHash": "changed"}
    stale = gate.refresh_stale(rec["spec"]["productId"], rec2)
    assert stale["stale"] is True
    with pytest.raises(PermissionError):
        gate.advance("x", target="LIVE_CNC", actor="ops", entity=rec)


def test_release_export_not_live(platform):
    rec = platform.kd.build_sku(tenant_id="t1", kind="PET_FURNITURE")
    g = platform.release
    g.advance(rec["spec"]["productId"], target="ENGINEERING_VALID", actor="ops", entity=rec)
    with pytest.raises(PermissionError):
        g.advance(rec["spec"]["productId"], target="EVIDENCE_VERIFIED", actor="ops", entity=rec, evidence_ok=False)
    g.advance(rec["spec"]["productId"], target="EVIDENCE_VERIFIED", actor="ops", entity=rec, evidence_ok=True)
    g.advance(rec["spec"]["productId"], target="WAITING_APPROVAL", actor="ops", entity=rec, evidence_ok=True)
    done = g.advance(rec["spec"]["productId"], target="APPROVED_FOR_EXPORT", actor="ops", entity=rec, evidence_ok=True)
    assert done["state"] == "APPROVED_FOR_EXPORT"
    assert done["equalsLiveCnc"] is False
    assert done["liveMachineControl"] is False


def test_sandbox_policy_partial(platform):
    backend = platform.sandbox.get("PATH_GUARD_ONLY")
    assert backend.status == "PARTIAL"
    job = {"jobId": "j", "glbPath": "ok.glb"}
    pol = job_policy_manifest(job, work_dir=str(platform.root))
    assert pol["networkAllowed"] is False
    assert pol["enforce"] == "PARTIAL"
    out = backend.enforce(job, pol)
    assert out["osJail"] is False
    assert "network" in out["notEnforced"]
    with pytest.raises(PermissionError):
        assert_job_paths_safe({"glbPath": "..\\..\\secret"})
    assert platform.sandbox.get("CONTAINER").status == "BLOCKED"


def test_provider_import_and_mixed_cost(platform):
    csv_text = "supplier,materialCode,thickness,sheetSize,currency,UOM,price,effectiveAt,expiresAt,sourceRef\nA,WOOD_WHITE,18,2440x1220,TWD,sheet,900,2026-01-01,2027-01-01,manual\n"
    rows = platform.providers.import_csv(platform.providers.material, csv_text, source="MANUAL")
    assert rows[0]["source"] == "MANUAL"
    assert rows[0]["liveProvider"] is False
    hw = platform.providers.import_rows(
        platform.providers.hardware,
        [{"vendorNeutralId": "HW_CAM_LOCK_15", "supplierSku": "CAM-15", "price": 2.5, "packQty": 20, "effectiveAt": "2026-01-01"}],
        source="IMPORTED",
    )
    assert hw[0]["kind"] == "hardware"
    fx = platform.providers.import_rows(platform.providers.fx, [{"pair": "USD/TWD", "rate": 32.1, "effectiveAt": "2026-01-01"}], source="MANUAL")
    assert fx[0]["source"] == "MANUAL"
    mixed = mixed_landed_cost(
        [
            {"name": "sheet", "amount": 900, "source": "REAL_IMPORTED"},
            {"name": "logistics", "amount": 80, "source": "CONFIG_ESTIMATE"},
        ]
    )
    assert mixed["truthLabel"] == "MIXED"
    assert mixed["liveProviderReady"] is False
    rec = platform.kd.build_sku(tenant_id="t1", kind="DESK_RISER")
    bind = quote_binding(rec, snapshot_ids=[rows[0]["snapshotId"]], valid_from="2026-01-01", valid_to="2026-12-31")
    assert quote_stale(bind, rec, now="2026-06-01", snapshot_ids=[rows[0]["snapshotId"]]) is False
    rec2 = dict(rec)
    rec2["engineeringHash"] = "nope"
    assert quote_stale(bind, rec2, now="2026-06-01") is True
    alts = supplier_alternatives(rec["spec"], rows + [{"snapshotId": "bad", "thickness": 25, "materialCode": "MDF", "price": 1}], thickness=18, material_code="WOOD_WHITE")
    assert alts["autoReplaceForbidden"] is True
    assert alts["vetoed"]


def test_packaging_v2_validators():
    grade = board_grade("KRAFT_B_ECT32")
    assert grade["certification"] is False
    inner = {"length": 300, "width": 200, "height": 150}
    comp = box_compression_estimate(inner=inner, grade=grade)
    assert comp["source"] == "ENGINEERING_ESTIMATE"
    assert comp["certification"] is False
    load = shipping_load_scenario(product_weight_kg=2.0, stack_count=6, compression=comp)
    assert load["label"] == "ENGINEERING_ESTIMATE"
    from fox3d.packaging import dieline_primitives

    die = dieline_primitives("RSC_CARTON", inner)
    geo = validate_dieline(die)
    assert geo["ok"] is True
    bleed = validate_bleed({"zones": [{"name": "main", "bleedMm": 3, "safeMm": 5}]})
    assert bleed["completePrintPreflight"] is False
    pf = artwork_preflight(None)
    assert pf["ok"] is False
    assert pf["guessedPassForbidden"] is True
    bc = barcode_zone({"w": 120, "h": 80})
    assert bc["label"] == "PARTIAL"
    fit = fit_regression()
    assert fit["n"] >= 20
    assert fit["allOk"] is True
    opt = carton_optimize({"width": 120, "height": 80, "depth": 40}, grade=grade)
    assert opt["engineeringVetoFirst"] is True
    assert opt["chosen"]["family"] in {"RSC_CARTON", "MAILER_BOX", "SLEEVE", "TRAY", "PDQ_TRAY"}


def test_safety_engine_cases(platform):
    assert SafetyRuleRegistry().list()
    dangerous = furniture_stability({"width": 200, "depth": 180, "height": 2000, "boardThickness": 18})
    assert dangerous["veto"] is True
    assert dangerous["certification"] is False
    assert wall_anchor_warning({"width": 400, "depth": 250, "height": 1600})["required"] is True
    kd_ok = 0
    for kind in ["DESK_RISER", "BEDSIDE_CABINET", "OPEN_SHELF", "PET_FURNITURE", "STORAGE_BENCH", "MOBILE_SIDE_TABLE", "NARROW_BOOKCASE", "APPLIANCE_RACK", "STUDENT_DESK", "GARMENT_RACK"]:
        rec = platform.kd.build_sku(tenant_id="t1", kind=kind)
        ev = evaluate_product("KD", rec)
        assert ev["notCertified"] is True
        if not ev["veto"]:
            kd_ok += 1
    assert kd_ok >= 8
    for fam in ["COUNTER_DISPLAY", "FLOOR_DISPLAY", "PDQ_DISPLAY", "RISER_DISPLAY", "PEGBOARD_DISPLAY", "ENDCAP_MODULE"]:
        fx = platform.physical.retail.build(tenant_id="t1", family=fam, render=False)
        ev = evaluate_product("RETAIL", fx)
        assert ev["boundary"]["notCertified"] is True
    for kind in ["MENU_STAND", "SIGN_HOLDER", "DISPLAY_BOX"]:
        ac = platform.physical.acrylic.build(tenant_id="t1", kind=kind)
        ev = evaluate_product("ACRYLIC", ac)
        assert ev["checks"]
    thin = acrylic_risk({"dimensions": {"width": 800, "height": 800, "depth": 10}, "sheet": {"thickness": 3}, "cutBend": {"bends": [{}]}})
    assert thin["veto"] is True
    assert thin["liveLaser"] is False


def test_publication_and_catalog(platform, tmp_path):
    rec = platform.kd.build_sku(tenant_id="t1", kind="OPEN_SHELF")
    pack = publication_package(rec, family="KD_FURNITURE")
    assert pack["publicationHash"]
    assert pack["liveMachineControl"] is False
    glb = tmp_path / "p.glb"
    glb.write_bytes(b"glTF" + b"\x00" * 20)
    from fox3d.publish import glb_publication

    pub = glb_publication({"dimensions": {"width": 1, "height": 1, "depth": 1}}, glb)
    assert pub["label"] == "REAL"
    man = web3d_manifest(twin={"dimensions": {"width": 100}}, glb=pub)
    assert man["arRuntime"] == "PARTIAL"
    ar = ar_export_boundary({"usdzReserved": True})
    assert ar["label"] == "PARTIAL"
    assert ar["usdzProduced"] is False
    cat = CatalogRelease()
    sku = cat.add_sku(rec, family="KD_FURNITURE")
    rel = cat.release(name="r1", sku_ids=[sku["skuId"]])
    cat.supersede(rel["releaseId"], successor="r2")
    assert cat.releases[rel["releaseId"]]["stale"] is True


def test_rdloop_outcomes_and_kpi(platform):
    demand = DemandRegistryV2()
    sig = demand.signal(kind="OPEN_SHELF")
    assert sig["market"] == "MARKET_UNVERIFIED"
    demand.register("csv", "IMPORTED")
    assert demand.signal(kind="x", name="csv")["label"] == "IMPORTED"
    rows = import_outcomes(json.dumps([{"skuId": "s1", "productVersion": 1, "sales": 3, "margin": 0.2}]), source="FIXTURE")
    assert rows[0]["realMarketData"] is False
    ranked = evidence_weighted_rank([{"productId": "s1", "materialUtilization": 0.7, "trueScrap": 0.1, "kind": "A"}], rows)
    assert ranked["ranked"][0]["rankSource"] == "ENGINEERING_MATERIAL_ONLY"
    sub = substitution_candidates({"thickness": 18, "material": "WOOD_WHITE"}, [{"snapshotId": "1", "thickness": 18, "price": 1}])
    assert sub["autoSwapForbidden"] is True
    assert sub["alternatives"][0]["reapprovalRequired"] is True
    kpi = kpi_read_model(platform)
    assert kpi["liveMachineControl"] is False
    assert "MOCK" in kpi["labels"]


def test_api_v2_routes(platform):
    client = TestClient(create_app(platform))
    headers = {"X-Tenant-Id": "acme"}
    assert client.get("/api/readiness").json()["globalProductionReady"] is False
    assert client.get("/api/kpi").status_code == 200
    imp = client.post("/api/commerce/import", json={"kind": "logistics", "source": "MANUAL", "rows": [{"zone": "TW", "baseFee": 80, "perKg": 12}]}, headers=headers)
    assert imp.status_code == 200
    assert imp.json()["liveProviderReady"] is False
    live = client.post("/api/release/advance", json={"entityId": "x", "target": "LIVE_LASER", "entity": {}}, headers=headers)
    assert live.status_code == 403
    admin = client.get("/admin")
    assert "Physical Product OS" in admin.text
    assert "/api/kpi" in admin.text
