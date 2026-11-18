from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import io
import json
import logging
from pathlib import Path
import shutil
import subprocess
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, RectangleObject
import pytest

from fox3d import asset_usage, print_assets as assets, print_workspace as jobs
from fox3d.ids import new_id
from fox3d.print_api import print_router
from fox3d.product_models_api import product_models_router
from fox3d.recipe_3d import atomic_json

STATIC = Path(__file__).resolve().parents[1] / "src" / "fox3d" / "static"


def _pdf_bytes(seed: int = 0) -> bytes:
    writer = PdfWriter()
    for page_idx in range(3):
        pg = writer.add_blank_page(width=286 * jobs.PT, height=401 * jobs.PT)
        pg.mediabox = RectangleObject([0, 0, 286 * jobs.PT, 401 * jobs.PT])
        pg.trimbox = RectangleObject([3 * jobs.PT, 3 * jobs.PT, 283 * jobs.PT, 398 * jobs.PT])
        content = DecodedStreamObject()
        content.set_data(f"q 0 1 1 0 k {10 + seed + page_idx} 20 40 80 re f Q".encode())
        pg[NameObject("/Contents")] = writer._add_object(content)
        pg.rotate(90)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _create_classified_asset(root: Path, tenant: str = "tenant-a", seed: int = 0) -> dict:
    a = assets.import_asset(root, tenant, _pdf_bytes(seed), f"art-{seed}.pdf")
    return asset_usage.classify(root, tenant, a["id"], "ARTWORK", f"Approved synthetic artwork {seed}", 0)


def _draft(asset_id: str, sku: str = "SKU-001", name: str = "測試商品", rotation: int = 90) -> dict:
    return {
        "sku": sku,
        "name": name,
        "layout": "THREE_DOOR",
        "rip": "RasterLink 6",
        "machine": "Mimaki-Test",
        "substrate": "樺木夾板",
        "panels": [{"label": f"門片{i + 1}", "assetId": asset_id, "page": i, "rotation": rotation} for i in range(3)],
    }


def _release_payload(revision: int, plan_hash: str, proof_id: str, operator: str = "王大明") -> dict:
    return {
        "expectedRevision": revision,
        "planHash": plan_hash,
        "proofId": proof_id,
        "operator": operator,
        "measurementRecord": "實測板件尺寸與出血核對無誤紀錄",
        "testPrintRecord": "實機白墨與色彩試印確認無誤紀錄",
        "dimensionsChecked": True,
        "orderAndOrientationChecked": True,
        "bleedAndKeepOutChecked": True,
        "colorWhiteVarnishTestPassed": True,
        "ripScale100Confirmed": True,
    }


def _make_client(root: Path, tenant: str = "tenant-a") -> TestClient:
    platform = SimpleNamespace(root=root, mock_blender=True, runtime=SimpleNamespace(available=lambda: False))
    app = FastAPI()
    app.include_router(print_router(lambda: platform))
    app.include_router(product_models_router(lambda: platform))
    return TestClient(app, headers={"X-Tenant-Id": tenant})


def test_corrupted_job_and_asset_files_are_skipped_logged_and_paginated(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    c = _make_client(tmp_path, "tenant-a")
    a1 = _create_classified_asset(tmp_path, "tenant-a", seed=1)
    a2 = _create_classified_asset(tmp_path, "tenant-a", seed=2)
    a3 = _create_classified_asset(tmp_path, "tenant-a", seed=3)

    j1 = jobs.save_job(tmp_path, "tenant-a", _draft(a1["id"], sku="SKU-1", name="商品一"))
    j2 = jobs.save_job(tmp_path, "tenant-a", _draft(a2["id"], sku="SKU-2", name="商品二"))
    j3 = jobs.save_job(tmp_path, "tenant-a", _draft(a3["id"], sku="SKU-3", name="商品三"))

    ws = assets.workspace(tmp_path, "tenant-a")

    # Corrupted job.json files: invalid JSON, missing updatedAt, and non-dict payload
    bad_job_1 = ws / "jobs" / new_id() / "job.json"
    bad_job_1.parent.mkdir(parents=True, exist_ok=True)
    bad_job_1.write_text("{corrupted json", encoding="utf-8")

    bad_job_2_id = new_id()
    bad_job_2 = ws / "jobs" / bad_job_2_id / "job.json"
    bad_job_2.parent.mkdir(parents=True, exist_ok=True)
    bad_job_2.write_text(json.dumps({"id": bad_job_2_id, "revision": 1, "draft": {}}), encoding="utf-8")

    # Corrupted asset.json files: invalid JSON and missing 'id' / 'info'
    bad_asset_1 = ws / "assets" / ("e" * 64) / "asset.json"
    bad_asset_1.parent.mkdir(parents=True, exist_ok=True)
    bad_asset_1.write_text("{not valid json", encoding="utf-8")

    bad_asset_2 = ws / "assets" / ("f" * 64) / "asset.json"
    bad_asset_2.parent.mkdir(parents=True, exist_ok=True)
    bad_asset_2.write_text(json.dumps({"name": "missing-id.pdf"}), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        res_jobs = c.get("/api/print-workspace/jobs")
        res_assets = c.get("/api/print-workspace/assets")
        res_pm_assets = c.get("/api/product-models/assets")

    assert res_jobs.status_code == 200, res_jobs.text
    jobs_body = res_jobs.json()
    assert jobs_body["skipped"] == 2
    assert jobs_body["total"] == 3
    assert [item["id"] for item in jobs_body["items"]] == [j3["id"], j2["id"], j1["id"]]
    assert str(tmp_path) not in res_jobs.text
    assert "KeyError" not in res_jobs.text
    assert "updatedAt" not in jobs_body.get("detail", "")

    assert res_assets.status_code == 200, res_assets.text
    assets_body = res_assets.json()
    assert assets_body["skipped"] == 2
    assert assets_body["total"] == 3
    assert {item["id"] for item in assets_body["items"]} == {a1["id"], a2["id"], a3["id"]}
    assert str(tmp_path) not in res_assets.text
    assert "'id'" not in res_assets.text

    assert res_pm_assets.status_code == 200, res_pm_assets.text
    pm_body = res_pm_assets.json()
    assert pm_body["skipped"] == 2
    assert pm_body["total"] == 3
    assert len(pm_body["items"]) == 3
    assert str(tmp_path) not in res_pm_assets.text
    assert "'id'" not in res_pm_assets.text

    # Warning logs emitted for skipped records
    assert len(caplog.records) >= 4

    # Offset / limit pagination and upper bound validation
    paged_jobs = c.get("/api/print-workspace/jobs?offset=1&limit=1").json()
    assert paged_jobs["offset"] == 1
    assert paged_jobs["limit"] == 1
    assert paged_jobs["total"] == 3
    assert paged_jobs["skipped"] == 2
    assert [x["id"] for x in paged_jobs["items"]] == [j2["id"]]

    paged_assets = c.get("/api/print-workspace/assets?offset=1&limit=2").json()
    assert paged_assets["offset"] == 1
    assert paged_assets["limit"] == 2
    assert paged_assets["total"] == 3
    assert paged_assets["skipped"] == 2
    assert len(paged_assets["items"]) == 2

    paged_pm_assets = c.get("/api/product-models/assets?offset=2&limit=1").json()
    assert paged_pm_assets["offset"] == 2
    assert paged_pm_assets["limit"] == 1
    assert len(paged_pm_assets["items"]) == 1

    assert c.get("/api/print-workspace/jobs?limit=101").status_code == 422
    assert c.get("/api/print-workspace/assets?limit=101").status_code == 422
    assert c.get("/api/product-models/assets?limit=101").status_code == 422


def test_unknown_job_bundle_asset_return_404_and_422_hides_raw_exceptions(tmp_path: Path) -> None:
    c = _make_client(tmp_path, "tenant-a")
    a = _create_classified_asset(tmp_path, "tenant-a")
    j = jobs.save_job(tmp_path, "tenant-a", _draft(a["id"]))
    p = jobs.plan(tmp_path, "tenant-a", j["draft"])
    version = {"expectedRevision": 1, "planHash": p["planHash"]}

    missing_jid = new_id()
    missing_bid = new_id()
    missing_aid = "0" * 64

    assert c.get(f"/api/print-workspace/jobs/{missing_jid}").status_code == 404
    assert c.get("/api/print-workspace/jobs/not-a-uuid").status_code == 404
    assert c.put(f"/api/print-workspace/jobs/{missing_jid}", json={"draft": j["draft"], "expectedRevision": 1}).status_code == 404
    assert c.post(f"/api/print-workspace/jobs/{missing_jid}/proof", json=version).status_code == 404
    assert c.get(f"/api/print-workspace/jobs/{missing_jid}/preview").status_code == 404
    assert c.get(f"/api/print-workspace/jobs/{missing_jid}/bundles/{missing_bid}?workspace=tenant-a").status_code == 404
    assert c.get(f"/api/print-workspace/jobs/{j['id']}/bundles/{missing_bid}?workspace=tenant-a").status_code == 404
    assert c.get(f"/api/print-workspace/jobs/{j['id']}/bundles/not-a-uuid?workspace=tenant-a").status_code == 404
    assert c.get(f"/api/print-workspace/assets/{missing_aid}/preview?workspace=tenant-a").status_code == 404
    assert c.post(f"/api/print-workspace/sources/{missing_aid}/import").status_code == 404
    assert (
        c.post(
            f"/api/print-workspace/jobs/{j['id']}/release",
            json=_release_payload(1, p["planHash"], missing_bid),
        ).status_code
        == 404
    )
    assert (
        c.put(
            f"/api/product-models/assets/{missing_aid}/usage",
            json={"role": "ARTWORK", "note": "valid note", "expectedRevision": 0},
        ).status_code
        == 404
    )

    # Corrupt PDF/image upload returns 422 with clean validation message, no raw exception text
    bad_pdf = c.post(
        "/api/print-workspace/assets/upload",
        files={"file": ("broken.pdf", b"%PDF-corrupted-stream", "application/pdf")},
    )
    assert bad_pdf.status_code == 422
    assert "EOF" not in bad_pdf.text and "BytesIO" not in bad_pdf.text and str(tmp_path) not in bad_pdf.text

    bad_img = c.post(
        "/api/print-workspace/assets/upload",
        files={"file": ("broken.png", b"not-an-image-at-all", "image/png")},
    )
    assert bad_img.status_code == 422
    assert "BytesIO" not in bad_img.text and "cannot identify" not in bad_img.text and str(tmp_path) not in bad_img.text


def test_proof_and_release_idempotent_on_repeat_requests(tmp_path: Path) -> None:
    import zipfile

    c = _make_client(tmp_path, "tenant-a")
    a = _create_classified_asset(tmp_path, "tenant-a")
    j = jobs.save_job(tmp_path, "tenant-a", _draft(a["id"]))
    p = jobs.plan(tmp_path, "tenant-a", j["draft"])
    version = {"expectedRevision": 1, "planHash": p["planHash"]}

    # Sending proof twice for the same (job, revision, planHash) returns the exact same bundleId
    proof_1 = c.post(f"/api/print-workspace/jobs/{j['id']}/proof", json=version)
    proof_2 = c.post(f"/api/print-workspace/jobs/{j['id']}/proof", json=version)
    assert proof_1.status_code == 200 and proof_2.status_code == 200
    assert proof_1.json()["bundleId"] == proof_2.json()["bundleId"]

    bundles_dir = jobs.folder_for(tmp_path, "tenant-a", j["id"]) / "bundles"
    assert len([d for d in bundles_dir.iterdir() if d.is_dir()]) == 1

    # Sending identical release twice for the same proofId reuses the existing bundle
    rel_body_1 = _release_payload(1, p["planHash"], proof_1.json()["bundleId"], operator="王大明")
    rel_1 = c.post(f"/api/print-workspace/jobs/{j['id']}/release", json=rel_body_1)
    rel_2 = c.post(f"/api/print-workspace/jobs/{j['id']}/release", json=rel_body_1)
    assert rel_1.status_code == 200 and rel_2.status_code == 200
    bid_1 = rel_1.json()["bundleId"]
    assert bid_1 == rel_2.json()["bundleId"]
    assert len([d for d in bundles_dir.iterdir() if d.is_dir()]) == 2

    dl_1 = c.get(f"/api/print-workspace/jobs/{j['id']}/bundles/{bid_1}?workspace=tenant-a")
    assert dl_1.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dl_1.content)) as zf:
        manifest_1 = json.loads(zf.read("manifest.json"))
    assert manifest_1["humanRelease"] == rel_body_1

    # Submitting a different operator / measurementRecord / testPrintRecord for the same proofId
    # must NOT silently reuse the old bundle; it creates a new release bundle with updated manifest.
    rel_body_2 = {
        **rel_body_1,
        "operator": "李小華",
        "measurementRecord": "第二次實測板件與出血修正紀錄（李小華覆核）",
        "testPrintRecord": "第二次實機白墨與光油打樣確認紀錄（李小華覆核）",
    }
    rel_3 = c.post(f"/api/print-workspace/jobs/{j['id']}/release", json=rel_body_2)
    assert rel_3.status_code == 200
    bid_2 = rel_3.json()["bundleId"]
    assert bid_2 != bid_1
    assert len([d for d in bundles_dir.iterdir() if d.is_dir()]) == 3

    # Repeat identical second release request is idempotent
    rel_4 = c.post(f"/api/print-workspace/jobs/{j['id']}/release", json=rel_body_2)
    assert rel_4.status_code == 200
    assert rel_4.json()["bundleId"] == bid_2
    assert len([d for d in bundles_dir.iterdir() if d.is_dir()]) == 3

    # Job state reflects the latest release bundle and operator, and superseded bundle is rejected
    job_now = c.get(f"/api/print-workspace/jobs/{j['id']}").json()
    assert job_now["release"]["bundleId"] == bid_2
    assert job_now["release"]["operator"] == "李小華"
    assert c.get(f"/api/print-workspace/jobs/{j['id']}/bundles/{bid_1}?workspace=tenant-a").status_code == 422

    dl_2 = c.get(f"/api/print-workspace/jobs/{j['id']}/bundles/{bid_2}?workspace=tenant-a")
    assert dl_2.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dl_2.content)) as zf:
        manifest_2 = json.loads(zf.read("manifest.json"))
    assert manifest_2["humanRelease"] == rel_body_2
    assert manifest_2["humanRelease"]["operator"] == "李小華"
    assert manifest_2["humanRelease"]["measurementRecord"] == rel_body_2["measurementRecord"]
    assert manifest_2["humanRelease"]["testPrintRecord"] == rel_body_2["testPrintRecord"]

    # Changing only measurementRecord (same operator) also creates a new release bundle
    rel_body_3 = {
        **rel_body_2,
        "measurementRecord": "第三次量測微調紀錄（同人修正量測值）",
    }
    rel_5 = c.post(f"/api/print-workspace/jobs/{j['id']}/release", json=rel_body_3)
    assert rel_5.status_code == 200
    bid_3 = rel_5.json()["bundleId"]
    assert bid_3 not in {bid_1, bid_2}
    dl_3 = c.get(f"/api/print-workspace/jobs/{j['id']}/bundles/{bid_3}?workspace=tenant-a")
    assert dl_3.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dl_3.content)) as zf:
        manifest_3 = json.loads(zf.read("manifest.json"))
    assert manifest_3["humanRelease"] == rel_body_3


def test_concurrent_proof_and_release_create_single_bundle_directory(tmp_path: Path) -> None:
    a = _create_classified_asset(tmp_path, "tenant-a")
    j = jobs.save_job(tmp_path, "tenant-a", _draft(a["id"]))
    p = jobs.plan(tmp_path, "tenant-a", j["draft"])
    bundles_dir = jobs.folder_for(tmp_path, "tenant-a", j["id"]) / "bundles"

    workers = 8
    barrier = threading.Barrier(workers)

    def run_proof(_: int) -> dict:
        barrier.wait()
        return jobs.export_bundle(tmp_path, "tenant-a", j["id"], expected_revision=1, plan_hash=p["planHash"])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        proof_results = list(pool.map(run_proof, range(workers)))

    proof_ids = {r["bundleId"] for r in proof_results}
    assert len(proof_ids) == 1
    proof_id = next(iter(proof_ids))
    assert [d.name for d in bundles_dir.iterdir() if d.is_dir()] == [proof_id]

    barrier_rel = threading.Barrier(workers)
    rel_payload = _release_payload(1, p["planHash"], proof_id)

    def run_release(_: int) -> dict:
        barrier_rel.wait()
        return jobs.export_bundle(
            tmp_path, "tenant-a", j["id"], expected_revision=1, plan_hash=p["planHash"], release=rel_payload
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rel_results = list(pool.map(run_release, range(workers)))

    rel_ids = {r["bundleId"] for r in rel_results}
    assert len(rel_ids) == 1
    rel_id = next(iter(rel_ids))
    assert {d.name for d in bundles_dir.iterdir() if d.is_dir()} == {proof_id, rel_id}


def test_proof_bundle_retention_prunes_oldest_unreferenced_and_keeps_release_referenced(tmp_path: Path) -> None:
    a = _create_classified_asset(tmp_path, "tenant-a")
    j = jobs.save_job(tmp_path, "tenant-a", _draft(a["id"], sku="RET-001"))
    p1 = jobs.plan(tmp_path, "tenant-a", j["draft"])

    # Revision 1 proof + release referencing proof_1
    proof_1 = jobs.export_bundle(tmp_path, "tenant-a", j["id"], expected_revision=1, plan_hash=p1["planHash"])
    rel_1 = jobs.export_bundle(
        tmp_path,
        "tenant-a",
        j["id"],
        expected_revision=1,
        plan_hash=p1["planHash"],
        release=_release_payload(1, p1["planHash"], proof_1["bundleId"]),
    )

    proof_ids = [proof_1["bundleId"]]
    total_revisions = jobs.MAX_PROOF_BUNDLES + 4  # 14 revisions total

    for rev in range(2, total_revisions + 1):
        d = copy.deepcopy(j["draft"])
        d["sku"] = f"RET-{rev:03d}"
        j = jobs.save_job(tmp_path, "tenant-a", d, jid=j["id"], expected_revision=rev - 1)
        p = jobs.plan(tmp_path, "tenant-a", j["draft"])
        b = jobs.export_bundle(tmp_path, "tenant-a", j["id"], expected_revision=rev, plan_hash=p["planHash"])
        proof_ids.append(b["bundleId"])

    # Also ensure that if job.release explicitly points to proof_1, pruning respects it
    stored = jobs.get_job(tmp_path, "tenant-a", j["id"])
    assert stored["lastProofId"] == proof_ids[-1]

    bundles_dir = jobs.folder_for(tmp_path, "tenant-a", j["id"]) / "bundles"
    remaining_dirs = {d.name for d in bundles_dir.iterdir() if d.is_dir()}

    # Release bundle and the proof bundle it references (proof_1) must be preserved
    assert rel_1["bundleId"] in remaining_dirs
    assert proof_1["bundleId"] in remaining_dirs
    assert jobs.bundle_download(tmp_path, "tenant-a", j["id"], proof_1["bundleId"])[0].is_file()

    # Latest proof bundle (lastProofId) must be preserved
    assert proof_ids[-1] in remaining_dirs
    assert jobs.bundle_download(tmp_path, "tenant-a", j["id"], proof_ids[-1])[0].is_file()

    # Oldest unreferenced PROOF bundles (revisions 2..5) must have been pruned
    for old_proof_id in proof_ids[1:5]:
        assert old_proof_id not in remaining_dirs
        with pytest.raises(assets.NotFoundError):
            jobs.bundle_download(tmp_path, "tenant-a", j["id"], old_proof_id)

    # Total remaining PROOF bundles equals MAX_PROOF_BUNDLES
    remaining_proofs = [
        d.name
        for d in bundles_dir.iterdir()
        if d.is_dir() and json.loads((d / "manifest.json").read_text(encoding="utf-8")).get("kind") == "PROOF"
    ]
    assert len(remaining_proofs) == jobs.MAX_PROOF_BUNDLES


def test_cross_tenant_reads_and_mutations_return_404(tmp_path: Path) -> None:
    c_a = _make_client(tmp_path, "tenant-a")
    c_b = _make_client(tmp_path, "tenant-b")

    a = _create_classified_asset(tmp_path, "tenant-a")
    j = jobs.save_job(tmp_path, "tenant-a", _draft(a["id"]))
    p = jobs.plan(tmp_path, "tenant-a", j["draft"])
    version = {"expectedRevision": 1, "planHash": p["planHash"]}
    proof = jobs.export_bundle(tmp_path, "tenant-a", j["id"], expected_revision=1, plan_hash=p["planHash"])

    # Tenant B cannot read or mutate Tenant A's job, bundle, or asset -> 404
    assert c_b.get(f"/api/print-workspace/jobs/{j['id']}").status_code == 404
    assert c_b.put(f"/api/print-workspace/jobs/{j['id']}", json={"draft": j["draft"], "expectedRevision": 1}).status_code == 404
    assert c_b.post(f"/api/print-workspace/jobs/{j['id']}/proof", json=version).status_code == 404
    assert (
        c_b.post(
            f"/api/print-workspace/jobs/{j['id']}/release",
            json=_release_payload(1, p["planHash"], proof["bundleId"]),
        ).status_code
        == 404
    )
    assert c_b.get(f"/api/print-workspace/jobs/{j['id']}/preview").status_code == 404
    assert c_b.post(f"/api/print-workspace/jobs/{j['id']}/preview/cancel", json={"taskId": "t-1"}).status_code == 404
    assert (
        c_b.get(f"/api/print-workspace/jobs/{j['id']}/bundles/{proof['bundleId']}?workspace=tenant-b").status_code
        == 404
    )
    assert c_b.get(f"/api/print-workspace/assets/{a['id']}/preview?workspace=tenant-b").status_code == 404
    assert (
        c_b.put(
            f"/api/product-models/assets/{a['id']}/usage",
            json={"role": "ARTWORK", "note": "cross tenant attempt", "expectedRevision": 1},
        ).status_code
        == 404
    )

    # Tenant B's own listings are empty, while Tenant A still sees its items
    assert c_b.get("/api/print-workspace/jobs").json()["items"] == []
    assert c_b.get("/api/print-workspace/assets").json()["items"] == []
    assert len(c_a.get("/api/print-workspace/jobs").json()["items"]) == 1
    assert len(c_a.get("/api/print-workspace/assets").json()["items"]) == 1


def test_print_workspace_js_handles_404_409_and_skipped_count(tmp_path: Path) -> None:
    js_path = STATIC / "print-workspace.js"
    js = js_path.read_text(encoding="utf-8")
    assert "r.status === 404" in js
    assert "r.status === 409" in js
    assert "找不到指定資料（404）" in js
    assert "版本或狀態衝突（409）" in js
    assert "有 ${skipped} 筆無法讀取" in js
    assert "有 ${assetsSkipped} 筆無法讀取" in js

    node = shutil.which("node")
    if node:
        harness = f"""
        const fs = require('fs');
        const code = fs.readFileSync({json.dumps(str(js_path))}, 'utf8');
        const elements = new Map();
        function makeEl(tag, id = '') {{
          const el = {{
            tagName: String(tag).toUpperCase(),
            id,
            textContent: '',
            className: '',
            value: '',
            hidden: false,
            disabled: false,
            checked: false,
            dataset: {{}},
            attributes: {{}},
            children: [],
            listeners: {{}},
            isConnected: true,
            append(...kids) {{
              for (const k of kids) {{
                if (typeof k === 'string') {{
                  const t = makeEl('#text');
                  t.textContent = k;
                  this.children.push(t);
                }} else if (k) {{
                  this.children.push(k);
                }}
              }}
            }},
            replaceChildren(...kids) {{
              this.children = [];
              this.append(...kids);
            }},
            setAttribute(k, v) {{ this.attributes[k] = String(v); }},
            removeAttribute(k) {{ delete this.attributes[k]; }},
            addEventListener(ev, fn) {{ (this.listeners[ev] ||= []).push(fn); }},
            insertAdjacentElement() {{}},
            querySelector(sel) {{
              if (sel === '.image-size') return makeEl('div');
              if (sel === 'img') return makeEl('img');
              if (sel === '.asset-info') return makeEl('small');
              if (sel.startsWith('[data-key=')) return makeEl('input');
              return makeEl('div');
            }},
            querySelectorAll(sel) {{
              if (sel === 'button[data-id]') return this.children.filter(c => c.dataset && c.dataset.id);
              return [];
            }},
            allText() {{
              return this.textContent + this.children.map(c => c.allText ? c.allText() : (c.textContent || '')).join(' ');
            }}
          }};
          return el;
        }}
        global.document = {{
          getElementById(id) {{
            if (!elements.has(id)) elements.set(id, makeEl('div', id));
            return elements.get(id);
          }},
          createElement(tag) {{ return makeEl(tag); }},
          querySelectorAll() {{ return []; }},
        }};
        global.Option = function(text, value, defaultSelected, selected) {{
          const o = makeEl('option');
          o.textContent = String(text);
          o.value = String(value);
          o.selected = !!selected;
          return o;
        }};
        global.FormData = class FormData {{}};
        global.window = {{
          location: {{ href: '' }},
          addEventListener() {{}},
          mountRecipeViewer() {{ return () => {{}}; }},
        }};
        global.confirm = () => true;
        global.fetch = async (url) => ({{
          ok: !url.includes('/jobs/missing') && !url.includes('/jobs/conflict'),
          status: url.includes('/jobs/missing') ? 404 : (url.includes('/jobs/conflict') ? 409 : 200),
          statusText: 'ERR',
          async json() {{
            if (url.endsWith('/assets')) return {{ items: [{{ id: 'a'.repeat(64), name: 'A.pdf', info: {{ type: 'PDF', pages: [{{}}] }}, usage: {{ role: 'ARTWORK', canUseForPrint: true }} }}], skipped: 2 }};
            if (url.endsWith('/jobs')) return {{ items: [{{ id: 'missing', revision: 1, draft: {{ sku: 'S1', name: 'N1', panels: [] }} }}, {{ id: 'conflict', revision: 1, draft: {{ sku: 'S2', name: 'N2', panels: [] }} }}], skipped: 3 }};
            if (url.includes('/sources')) return {{ configured: false, total: 0, items: [] }};
            if (url.includes('/jobs/missing')) return {{ detail: '找不到印刷工作' }};
            if (url.includes('/jobs/conflict')) return {{ detail: '版本已變更' }};
            return {{}};
          }}
        }});
        eval(code);
        (async () => {{
          for (let i = 0; i < 20; i++) await Promise.resolve();
          const jobCount = document.getElementById('job-count').allText();
          const jobsText = document.getElementById('jobs').allText();
          const assetsText = document.getElementById('assets').allText();
          const btns = document.getElementById('jobs').querySelectorAll('button[data-id]');
          await btns[0].onclick();
          const notice404 = document.getElementById('notice').textContent;
          await btns[1].onclick();
          const notice409 = document.getElementById('notice').textContent;
          console.log(JSON.stringify({{ jobCount, jobsText, assetsText, notice404, notice409 }}));
        }})();
        """
        proc = subprocess.run([node, "-e", harness], check=True, capture_output=True, text=True, encoding="utf-8", timeout=15)
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        assert "有 3 筆無法讀取" in out["jobCount"]
        assert "有 3 筆無法讀取" in out["jobsText"]
        assert "有 2 筆無法讀取" in out["assetsText"]
        assert "找不到指定資料（404）：找不到印刷工作" in out["notice404"]
        assert "版本或狀態衝突（409）：版本已變更" in out["notice409"]

    # Also verify direct job.json release reference is protected during pruning
    a = _create_classified_asset(tmp_path, "tenant-a")
    j = jobs.save_job(tmp_path, "tenant-a", _draft(a["id"], sku="DIRECT-REL"))
    p1 = jobs.plan(tmp_path, "tenant-a", j["draft"])
    b1 = jobs.export_bundle(tmp_path, "tenant-a", j["id"], expected_revision=1, plan_hash=p1["planHash"])

    for rev in range(2, 6):
        d = copy.deepcopy(j["draft"])
        d["sku"] = f"DIRECT-{rev}"
        j = jobs.save_job(tmp_path, "tenant-a", d, jid=j["id"], expected_revision=rev - 1)
        stored = jobs.get_job(tmp_path, "tenant-a", j["id"])
        stored["release"] = {"bundleId": b1["bundleId"], "planHash": p1["planHash"], "revision": 1, "operator": "OP"}
        atomic_json(jobs.folder_for(tmp_path, "tenant-a", j["id"]) / "job.json", stored)
        p = jobs.plan(tmp_path, "tenant-a", j["draft"])
        jobs.export_bundle(
            tmp_path, "tenant-a", j["id"], expected_revision=rev, plan_hash=p["planHash"], max_proof_bundles=3
        )

    bundles_dir = jobs.folder_for(tmp_path, "tenant-a", j["id"]) / "bundles"
    remaining = {d.name for d in bundles_dir.iterdir() if d.is_dir()}
    assert b1["bundleId"] in remaining
    assert len(remaining) == 3


def test_ui_pagination_over_100_jobs_and_assets_across_pages(tmp_path: Path) -> None:
    node = shutil.which("node")
    assert node is not None, "node is required for UI pagination verification"

    pw_js_path = STATIC / "print-workspace.js"
    pm_js_path = STATIC / "product-models.js"
    mc_js_path = STATIC / "model-compositions.js"

    # 1. Verify print-workspace.js loads all pages (>100 jobs and >100 assets), shows accurate total count,
    #    allows opening the 105th job (on page 2), and keeps the 105th asset selected in its panels.
    pw_harness = f"""
    const fs = require('fs');
    const code = fs.readFileSync({json.dumps(str(pw_js_path))}, 'utf8');

    const totalCount = 105;
    const allAssets = Array.from({{ length: totalCount }}, (_, idx) => {{
      const num = idx + 1;
      const id = num.toString(16).padStart(64, '0');
      return {{
        id,
        name: `art-${{String(num).padStart(3, '0')}}.pdf`,
        info: {{ type: 'PDF', pages: [{{}}] }},
        usage: {{ role: 'ARTWORK', label: '印刷圖稿', canUseForPrint: true, canUseForModel: true, revision: 1 }},
      }};
    }});
    const allJobs = Array.from({{ length: totalCount }}, (_, idx) => {{
      const num = idx + 1;
      const id = `00000000-0000-0000-0000-${{String(num).padStart(12, '0')}}`;
      const assetId = allAssets[idx].id;
      return {{
        id,
        revision: 1,
        updatedAt: `2026-11-18T00:00:${{String(totalCount - idx).padStart(2, '0')}}Z`,
        draft: {{
          sku: `SKU-${{String(num).padStart(3, '0')}}`,
          name: `商品-${{String(num).padStart(3, '0')}}`,
          layout: 'FLAT',
          rip: 'RasterLink 6',
          machine: 'Mimaki',
          substrate: 'Birch',
          panels: [{{ label: '正面', assetId, page: 0, rotation: 0, quantity: 1 }}],
        }},
        plan: {{
          planHash: 'a'.repeat(64),
          panels: [{{ label: '正面', page: 0, rotation: 0, widthMm: 286, heightMm: 401, trimWidthMm: 280, trimHeightMm: 395, quantity: 1 }}],
          warnings: [],
        }},
        spec: {{}},
        lastProofId: null,
        release: null,
        blenderAvailable: false,
      }};
    }});

    const elements = new Map();
    let currentPanels = [];
    function makeEl(tag, id = '') {{
      const el = {{
        tagName: String(tag).toUpperCase(),
        id,
        textContent: '',
        className: '',
        value: '',
        hidden: false,
        disabled: false,
        checked: false,
        dataset: {{}},
        attributes: {{}},
        children: [],
        listeners: {{}},
        isConnected: true,
        append(...kids) {{
          for (const k of kids) {{
            if (typeof k === 'string') {{
              const t = makeEl('#text');
              t.textContent = k;
              this.children.push(t);
            }} else if (k) {{
              this.children.push(k);
              if (this.tagName === 'SELECT' && k.selected) {{
                this.value = k.value;
              }}
            }}
          }}
        }},
        replaceChildren(...kids) {{
          this.children = [];
          this.append(...kids);
          if (this.id === 'panels') currentPanels = this.children;
        }},
        setAttribute(k, v) {{ this.attributes[k] = String(v); }},
        removeAttribute(k) {{ delete this.attributes[k]; }},
        addEventListener(ev, fn) {{ (this.listeners[ev] ||= []).push(fn); }},
        insertAdjacentElement() {{}},
        findByDatasetKey(key) {{
          if (this.dataset && this.dataset.key === key) return this;
          for (const c of this.children) {{
            if (c.findByDatasetKey) {{
              const found = c.findByDatasetKey(key);
              if (found) return found;
            }}
          }}
          return null;
        }},
        findByClass(cls) {{
          if (String(this.className || '').split(/\\s+/).includes(cls)) return this;
          for (const c of this.children) {{
            if (c.findByClass) {{
              const found = c.findByClass(cls);
              if (found) return found;
            }}
          }}
          return null;
        }},
        findByTag(tName) {{
          if (this.tagName === tName.toUpperCase()) return this;
          for (const c of this.children) {{
            if (c.findByTag) {{
              const found = c.findByTag(tName);
              if (found) return found;
            }}
          }}
          return null;
        }},
        querySelector(sel) {{
          if (sel === '.image-size') return this.findByClass('image-size') || makeEl('div');
          if (sel === 'img') return this.findByTag('IMG') || makeEl('img');
          if (sel === '.asset-info') return this.findByClass('asset-info') || makeEl('small');
          if (sel.startsWith('[data-key=')) {{
            const key = sel.slice('[data-key='.length, -1);
            return this.findByDatasetKey(key) || makeEl('input');
          }}
          return makeEl('div');
        }},
        querySelectorAll(sel) {{
          if (sel === 'button[data-id]') return this.children.filter(c => c.dataset && c.dataset.id);
          return [];
        }},
        allText() {{
          return this.textContent + this.children.map(c => c.allText ? c.allText() : (c.textContent || '')).join(' ');
        }},
      }};
      return el;
    }}
    global.document = {{
      getElementById(id) {{
        if (!elements.has(id)) elements.set(id, makeEl('div', id));
        return elements.get(id);
      }},
      createElement(tag) {{ return makeEl(tag); }},
      querySelectorAll(sel) {{
        if (sel === '.panel') return currentPanels;
        return [];
      }},
    }};
    global.Option = function(text, value, defaultSelected, selected) {{
      const o = makeEl('option');
      o.textContent = String(text);
      o.value = String(value);
      o.selected = !!selected;
      return o;
    }};
    global.FormData = class FormData {{}};
    global.window = {{
      location: {{ href: '' }},
      addEventListener() {{}},
      mountRecipeViewer() {{ return () => {{}}; }},
    }};
    global.confirm = () => true;

    const requestedUrls = [];
    global.fetch = async (rawUrl) => {{
      requestedUrls.push(rawUrl);
      const u = new URL(rawUrl, 'http://localhost');
      const offset = Number(u.searchParams.get('offset') || 0);
      const limit = Math.min(Number(u.searchParams.get('limit') || 100), 100);
      return {{
        ok: true,
        status: 200,
        statusText: 'OK',
        async json() {{
          if (u.pathname === '/api/print-workspace/assets') {{
            return {{
              items: allAssets.slice(offset, offset + limit),
              total: allAssets.length,
              offset,
              limit,
              skipped: 1,
            }};
          }}
          if (u.pathname === '/api/print-workspace/jobs') {{
            return {{
              items: allJobs.slice(offset, offset + limit),
              total: allJobs.length,
              offset,
              limit,
              skipped: 2,
            }};
          }}
          if (u.pathname.startsWith('/api/print-workspace/jobs/') && u.pathname.endsWith('/preview')) {{
            return {{ state: 'idle', generated: false, stale: false }};
          }}
          if (u.pathname.startsWith('/api/print-workspace/jobs/')) {{
            const jid = u.pathname.split('/').pop();
            return allJobs.find(j => j.id === jid);
          }}
          if (u.pathname === '/api/print-workspace/sources') {{
            return {{ configured: false, total: 0, items: [] }};
          }}
          return {{}};
        }},
      }};
    }};

    eval(code);
    (async () => {{
      for (let i = 0; i < 40; i++) await Promise.resolve();
      const jobBtns = document.getElementById('jobs').querySelectorAll('button[data-id]');
      const jobCount = document.getElementById('job-count').allText();
      const assetsText = document.getElementById('assets').allText();
      // Click the 105th job (on page 2, index 104)
      await jobBtns[104].onclick();
      for (let i = 0; i < 20; i++) await Promise.resolve();
      const selectedSku = document.getElementById('sku').value;
      const saveState = document.getElementById('save-state').textContent;
      const panelSelect = currentPanels[0].findByDatasetKey('assetId');
      const selectedOpt = panelSelect.children.find(o => o.value === panelSelect.value);
      console.log(JSON.stringify({{
        requestedUrls,
        jobBtnsCount: jobBtns.length,
        lastJobId: jobBtns[104].dataset.id,
        jobCount,
        hasAsset105InList: assetsText.includes('art-105.pdf'),
        hasAssetTotalText: assetsText.includes('共 105 筆原稿'),
        selectedSku,
        saveState,
        panelSelectedAssetId: panelSelect.value,
        panelSelectedText: selectedOpt ? selectedOpt.textContent : '',
        panelSelectedDisabled: selectedOpt ? !!selectedOpt.disabled : true,
        panelOptionCount: panelSelect.children.length,
      }}));
    }})();
    """
    pw_proc = subprocess.run([node, "-e", pw_harness], check=True, capture_output=True, text=True, encoding="utf-8", timeout=15)
    pw_out = json.loads(pw_proc.stdout.strip().splitlines()[-1])

    assert "/api/print-workspace/assets" in pw_out["requestedUrls"]
    assert "/api/print-workspace/assets?offset=100&limit=100" in pw_out["requestedUrls"]
    assert "/api/print-workspace/jobs" in pw_out["requestedUrls"]
    assert "/api/print-workspace/jobs?offset=100&limit=100" in pw_out["requestedUrls"]
    assert pw_out["jobBtnsCount"] == 105
    assert pw_out["lastJobId"] == "00000000-0000-0000-0000-000000000105"
    assert "105 個商品（有 2 筆無法讀取）" in pw_out["jobCount"]
    assert pw_out["hasAsset105InList"] is True
    assert pw_out["hasAssetTotalText"] is True
    assert pw_out["selectedSku"] == "SKU-105"
    assert pw_out["saveState"] == "已儲存 · 版本 1"
    assert pw_out["panelSelectedAssetId"] == (105).to_bytes(32, "big").hex()
    assert "art-105.pdf" in pw_out["panelSelectedText"]
    assert pw_out["panelSelectedDisabled"] is False
    assert pw_out["panelOptionCount"] == 106

    # 2. Verify product-models.js and model-compositions.js load all pages (>100 assets),
    #    display accurate total count, keep page-2 linked assets marked as confirmed (not disabled/unconfirmed),
    #    and allow searching & classifying the 105th asset from page 2.
    pm_harness = f"""
    const fs = require('fs');
    const pmCode = fs.readFileSync({json.dumps(str(pm_js_path))}, 'utf8');
    const mcCode = fs.readFileSync({json.dumps(str(mc_js_path))}, 'utf8');

    const totalCount = 105;
    const roles = {{
      UNCLASSIFIED: '待分類',
      REFERENCE: '商品參考圖／電商圖',
      DIMENSION: '尺寸／結構圖',
      DIELINE: '刀模',
      ARTWORK: '印刷圖稿',
      PACKAGING: '貼紙／吊卡／包裝',
    }};
    const allAssets = Array.from({{ length: totalCount }}, (_, idx) => {{
      const num = idx + 1;
      const id = num.toString(16).padStart(64, '0');
      const isArtwork = num <= 104;
      return {{
        id,
        name: `art-${{String(num).padStart(3, '0')}}.pdf`,
        provenance: {{ type: 'NAS_PRODUCT_CATALOG', relativePath: `folder/art-${{String(num).padStart(3, '0')}}.pdf` }},
        info: {{ type: 'PDF', pages: [{{}}, {{}}] }},
        usage: {{
          role: isArtwork ? 'ARTWORK' : 'UNCLASSIFIED',
          label: isArtwork ? '印刷圖稿' : '待分類',
          note: isArtwork ? 'Confirmed artwork' : '',
          revision: isArtwork ? 1 : 0,
          canUseForModel: isArtwork,
          canUseForPrint: isArtwork,
        }},
      }};
    }});
    const asset104Id = allAssets[103].id;
    const asset105Id = allAssets[104].id;

    const model1 = {{
      id: 'model-104',
      revision: 2,
      inputHash: 'b'.repeat(64),
      templateState: 'DRAFT',
      classification: {{ categoryId: 'unclassified', path: ['未分類'], source: 'AUTO', revision: 0 }},
      readiness: {{ previewReady: true, assumptions: [] }},
      draft: {{
        name: '第104號素材測試母版',
        family: 'cabinet',
        subtype: 'open',
        geometry: 'OPEN_CABINET',
        widthMm: 424,
        depthMm: 295,
        heightMm: 900,
        panelMm: 15,
        backMm: 3,
        rows: 3,
        dimensionEvidence: '實測',
        structureEvidence: '三層',
        notes: '',
        variants: [{{ sku: 'SKU-104', artworkAssetId: asset104Id, note: '第2頁素材' }}],
        printFaces: [],
      }},
    }};

    const elements = new Map();
    const windowListeners = {{}};
    function makeEl(tag, id = '') {{
      let _innerHTML = '';
      const el = {{
        tagName: String(tag).toUpperCase(),
        id,
        textContent: '',
        className: '',
        value: '',
        hidden: false,
        disabled: false,
        checked: false,
        inert: false,
        dataset: {{}},
        attributes: {{}},
        children: [],
        listeners: {{}},
        elements: {{
          geometry: {{ value: 'OPEN_CABINET', addEventListener() {{}} }},
          namedItem(name) {{
            if (!this[name]) this[name] = makeEl('input', name);
            return this[name];
          }},
        }},
        get innerHTML() {{ return _innerHTML; }},
        set innerHTML(val) {{ _innerHTML = String(val); }},
        insertAdjacentHTML(_pos, val) {{ _innerHTML += String(val); }},
        append(...kids) {{
          for (const k of kids) {{
            if (typeof k === 'string') {{
              const t = makeEl('#text');
              t.textContent = k;
              this.children.push(t);
            }} else if (k) {{
              this.children.push(k);
            }}
          }}
        }},
        replaceChildren(...kids) {{
          this.children = [];
          this.append(...kids);
        }},
        reset() {{}},
        remove() {{}},
        setAttribute(k, v) {{ this.attributes[k] = String(v); }},
        addEventListener(ev, fn) {{ (this.listeners[ev] ||= []).push(fn); }},
        findRec(pred) {{
          if (pred(this)) return this;
          for (const c of this.children) {{
            if (c && c.findRec) {{
              const found = c.findRec(pred);
              if (found) return found;
            }}
          }}
          return null;
        }},
        querySelector(sel) {{
          if (sel === 'select[data-art]') return this.findRec(e => e.dataset && 'art' in e.dataset);
          if (sel === 'select[data-page]') return this.findRec(e => e.dataset && 'page' in e.dataset);
          if (sel === 'select[data-rotation]') return this.findRec(e => e.dataset && 'rotation' in e.dataset);
          if (sel === 'img') return this.findRec(e => e.tagName === 'IMG');
          if (sel === '.variant-sku') return {{ value: 'SKU-104' }};
          if (sel === '.variant-art') return this._variantArt || makeEl('select');
          if (sel === '.variant-note') return {{ value: '' }};
          return makeEl('div');
        }},
        querySelectorAll() {{ return []; }},
      }};
      return el;
    }}

    global.document = {{
      getElementById(id) {{
        if (!elements.has(id)) elements.set(id, makeEl('div', id));
        return elements.get(id);
      }},
      createElement(tag) {{ return makeEl(tag); }},
      createTextNode(text) {{
        const t = makeEl('#text');
        t.textContent = String(text);
        return t;
      }},
      querySelectorAll(sel) {{
        if (sel === '.variant-art') {{
          const v = document.getElementById('variants');
          return v.children.map(r => {{
            if (!r._variantArt) {{
              const s = makeEl('select');
              s.innerHTML = r.innerHTML;
              r._variantArt = s;
            }}
            return r._variantArt;
          }});
        }}
        return [];
      }},
    }};
    global.Option = function(text, value, defaultSelected, selected) {{
      const o = makeEl('option');
      o.textContent = String(text);
      o.value = String(value);
      o.selected = !!selected;
      return o;
    }};
    global.Event = class Event {{ constructor(type) {{ this.type = type; }} preventDefault() {{}} }};
    global.CustomEvent = class CustomEvent {{ constructor(type, init) {{ this.type = type; this.detail = init?.detail; }} preventDefault() {{}} }};
    global.URLSearchParams = URLSearchParams;
    global.window = {{
      location: {{ hash: '' }},
      confirm: () => true,
      addEventListener(ev, fn) {{ (windowListeners[ev] ||= []).push(fn); }},
      dispatchEvent(ev) {{
        for (const fn of (windowListeners[ev.type] || [])) fn(ev);
      }},
      mountRecipeViewer() {{ return () => {{}}; }},
    }};
    global.setInterval = () => 0;

    const requestedUrls = [];
    const classifiedCalls = [];
    global.fetch = async (rawUrl, options = {{}}) => {{
      requestedUrls.push(`${{options.method || 'GET'}} ${{rawUrl}}`);
      const u = new URL(rawUrl, 'http://localhost');
      return {{
        ok: true,
        status: 200,
        async json() {{
          if (u.pathname === '/api/product-models/catalog') {{
            return {{ families: {{ cabinet: '木櫃' }}, subtypes: {{ open: '開放櫃', other: '其他' }}, configured: false, fileCount: 0, total: 0, items: [] }};
          }}
          if (u.pathname === '/api/product-models/recipe-references') {{
            return {{ items: [] }};
          }}
          if (u.pathname === '/api/product-models/assets' && (!options.method || options.method === 'GET')) {{
            const offset = Number(u.searchParams.get('offset') || 0);
            const limit = Math.min(Number(u.searchParams.get('limit') || 100), 100);
            return {{
              roles,
              items: allAssets.slice(offset, offset + limit),
              total: allAssets.length,
              offset,
              limit,
              skipped: 1,
            }};
          }}
          if (u.pathname === `/api/product-models/assets/${{asset105Id}}/usage` && options.method === 'PUT') {{
            const body = JSON.parse(options.body);
            classifiedCalls.push(body);
            allAssets[104].usage = {{
              role: body.role,
              label: roles[body.role],
              note: body.note,
              revision: body.expectedRevision + 1,
              canUseForModel: body.role === 'ARTWORK',
              canUseForPrint: body.role === 'ARTWORK',
            }};
            return allAssets[104];
          }}
          if (u.pathname === '/api/product-models') {{
            return {{
              items: [model1],
              categoryTree: [{{ id: 'unclassified', label: '未分類' }}],
            }};
          }}
          if (u.pathname === `/api/product-models/${{model1.id}}`) {{
            return model1;
          }}
          if (u.pathname === `/api/product-models/${{model1.id}}/classification`) {{
            return model1.classification;
          }}
          if (u.pathname === `/api/product-models/${{model1.id}}/preview`) {{
            return {{ state: 'idle', generated: false, stale: false }};
          }}
          if (u.pathname === `/api/product-models/${{model1.id}}/composition`) {{
            return {{
              state: 'idle',
              generated: false,
              stale: false,
              scenes: {{ STUDIO: '白底棚拍' }},
              surfaces: [{{ componentId: 'door-1', label: '第一片門', widthMm: 280, heightMm: 395 }}],
              manifest: {{
                sourceRevision: 2,
                scene: 'STUDIO',
                draft: {{
                  sku: 'SKU-104',
                  scene: 'STUDIO',
                  placement: 'AUTO',
                  view: 'THREE_QUARTER',
                  placements: [{{ componentId: 'door-1', assetId: asset104Id, page: 0, rotation: 0 }}],
                }},
                spec: {{ engineeringHash: 'c'.repeat(64) }},
              }},
            }};
          }}
          return {{}};
        }},
      }};
    }};

    eval(pmCode);
    eval(mcCode);

    (async () => {{
      for (let i = 0; i < 60; i++) await Promise.resolve();
      const initialUsageCount = document.getElementById('usage-count').textContent;

      // Click model1 in #masters to load its variant (which links asset104Id from page 2)
      const masterBtn = document.getElementById('masters').children[0];
      await masterBtn.onclick();
      for (let i = 0; i < 60; i++) await Promise.resolve();

      const variantRowHtml = document.getElementById('variants').children[0].innerHTML;
      const compSurface = document.getElementById('composition-faces').children[0];
      const compArtSelect = compSurface.querySelector('select[data-art]');
      const compOptionTexts = compArtSelect.children.map(o => o.textContent);

      // Search for asset #105 (on page 2) in #usage-query and classify it as ARTWORK
      const qInput = document.getElementById('usage-query');
      qInput.value = 'art-105.pdf';
      qInput.oninput();
      const filteredButtons = document.getElementById('usage-list').children;
      filteredButtons[0].onclick();
      const reviewName = document.getElementById('usage-name').textContent;
      document.getElementById('usage-role').value = 'ARTWORK';
      document.getElementById('usage-note').value = '第105筆素材核對為正式印刷圖稿';
      await document.getElementById('usage-form').onsubmit();
      for (let i = 0; i < 40; i++) await Promise.resolve();
      const updatedUsageCount = document.getElementById('usage-count').textContent;

      console.log(JSON.stringify({{
        requestedUrls,
        initialUsageCount,
        variantRowHtml,
        compSelectedValue: compArtSelect.value,
        compHasStaleWarning: compOptionTexts.some(t => t.includes('原圖稿已停用')),
        compOptionCount: compArtSelect.children.length,
        filteredCount: filteredButtons.length,
        reviewName,
        classifiedCalls,
        updatedUsageCount,
      }}));
    }})();
    """
    pm_proc = subprocess.run([node, "-e", pm_harness], capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert pm_proc.returncode == 0, f"STDOUT:\n{pm_proc.stdout}\nSTDERR:\n{pm_proc.stderr}"
    pm_out = json.loads(pm_proc.stdout.strip().splitlines()[-1])

    assert "GET /api/product-models/assets" in pm_out["requestedUrls"]
    assert "GET /api/product-models/assets?offset=100&limit=100" in pm_out["requestedUrls"]
    assert "105 筆素材；104 筆已確認印刷用途。有 1 筆無法讀取。" in pm_out["initialUsageCount"]
    # Linked asset #104 (on page 2) is recognized as confirmed ARTWORK, NOT falsely marked as unconfirmed
    assert "art-104.pdf · 已確認印刷用途" in pm_out["variantRowHtml"]
    assert "原關聯素材未確認或已改用途" not in pm_out["variantRowHtml"]
    # In model-compositions.js, linked asset #104 (on page 2) is also recognized and selected
    assert pm_out["compSelectedValue"] == (104).to_bytes(32, "big").hex()
    assert pm_out["compHasStaleWarning"] is False
    assert pm_out["compOptionCount"] == 105  # 1 placeholder + 104 confirmed artworks
    # Asset #105 (on page 2) can be searched, reviewed, and classified
    assert pm_out["filteredCount"] == 1
    assert pm_out["reviewName"] == "art-105.pdf"
    assert len(pm_out["classifiedCalls"]) == 1
    assert pm_out["classifiedCalls"][0]["role"] == "ARTWORK"
    assert "105 筆已確認印刷用途" in pm_out["updatedUsageCount"]


def test_pagination_1000_jobs_and_assets_avoids_rereading_and_mid_page_update_never_misses_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c_a = _make_client(tmp_path, "tenant-a")
    c_b = _make_client(tmp_path, "tenant-b")

    # Seed one real classified artwork asset in tenant-a so save_job / plan validation succeeds on mid-page update,
    # and one asset + job in tenant-b to verify strict tenant isolation across cache and cursor pagination.
    real_asset_a = _create_classified_asset(tmp_path, "tenant-a", seed=1)
    real_asset_b = _create_classified_asset(tmp_path, "tenant-b", seed=2)
    job_b = jobs.save_job(tmp_path, "tenant-b", _draft(real_asset_b["id"], sku="TENANT-B-SKU", name="租戶B商品"))

    ws_a = assets.workspace(tmp_path, "tenant-a")
    assets_dir = ws_a / "assets"
    jobs_dir = ws_a / "jobs"
    assets_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir.mkdir(parents=True, exist_ok=True)

    total_items = 1000
    expected_asset_ids = {real_asset_a["id"]}
    for idx in range(2, total_items + 1):
        aid = f"{idx:064x}"
        expected_asset_ids.add(aid)
        afolder = assets_dir / aid
        afolder.mkdir(parents=True, exist_ok=True)
        (afolder / "asset.json").write_text(
            json.dumps(
                {
                    "id": aid,
                    "name": f"synthetic-{idx:04d}.pdf",
                    "sizeBytes": 512,
                    "info": {
                        "type": "PDF",
                        "pages": [
                            {
                                "mediaBoxPt": [0.0, 0.0, 286.0 * jobs.PT, 401.0 * jobs.PT],
                                "trimBoxPt": [3.0 * jobs.PT, 3.0 * jobs.PT, 283.0 * jobs.PT, 398.0 * jobs.PT],
                                "rotation": 0,
                                "widthMm": 286.0,
                                "heightMm": 401.0,
                                "trimWidthMm": 280.0,
                                "trimHeightMm": 395.0,
                            }
                        ],
                        "color": "SOURCE_PDF_PRESERVED",
                        "sizeAuthority": "PDF_BOXES_NOT_PHYSICAL_MEASUREMENT",
                    },
                    "provenance": {"type": "USER_UPLOAD"},
                    "truth": "USER_PROVIDED_SOURCE",
                }
            ),
            encoding="utf-8",
        )
        (afolder / "usage.json").write_text(
            json.dumps(
                {
                    "role": "ARTWORK",
                    "note": f"Synthetic classification {idx}",
                    "revision": 1,
                    "updatedAt": "2026-11-18T00:00:00Z",
                    "assetSha256": aid,
                    "authority": "OPERATOR_CLASSIFICATION_ONLY",
                }
            ),
            encoding="utf-8",
        )

    base_draft = _draft(real_asset_a["id"], sku="SKU-0001", name="商品-0001")
    expected_job_ids: list[str] = []
    for idx in range(1, total_items + 1):
        jid = f"00000000-0000-0000-0000-{idx:012d}"
        expected_job_ids.append(jid)
        jfolder = jobs_dir / jid
        jfolder.mkdir(parents=True, exist_ok=True)
        hh = (idx // 3600) % 24
        mm = (idx // 60) % 60
        ss = idx % 60
        ts = f"2026-11-18T{hh:02d}:{mm:02d}:{ss:02d}Z"
        (jfolder / "job.json").write_text(
            json.dumps(
                {
                    "id": jid,
                    "revision": 1,
                    "updatedAt": ts,
                    "draft": {**base_draft, "sku": f"SKU-{idx:04d}", "name": f"商品-{idx:04d}"},
                    "release": None,
                    "lastProofId": None,
                }
            ),
            encoding="utf-8",
        )

    # Clear caches so page 1 starts completely cold
    jobs.clear_job_cache()
    asset_usage.clear_asset_cache()

    read_counts = {"job.json": 0, "asset.json": 0, "usage.json": 0}
    real_read_text = Path.read_text

    def counting_read_text(self: Path, *args, **kwargs):
        if self.name in read_counts:
            read_counts[self.name] += 1
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    # 1. Paginate 1000 assets across 10 pages (limit=100):
    #    Page 1 reads all 1000 asset.json files once and 100 usage.json files;
    #    pages 2..10 read 0 asset.json files and 100 usage.json files each.
    collected_assets: list[str] = []
    per_page_asset_reads: list[int] = []
    per_page_usage_reads: list[int] = []
    for page_idx in range(10):
        before_asset = read_counts["asset.json"]
        before_usage = read_counts["usage.json"]
        res = c_a.get(f"/api/print-workspace/assets?offset={page_idx * 100}&limit=100")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1000
        assert body["skipped"] == 0
        assert len(body["items"]) == 100
        collected_assets.extend(item["id"] for item in body["items"])
        per_page_asset_reads.append(read_counts["asset.json"] - before_asset)
        per_page_usage_reads.append(read_counts["usage.json"] - before_usage)

    assert per_page_asset_reads[0] == 1000
    assert per_page_asset_reads[1:] == [0] * 9
    assert sum(per_page_asset_reads) == 1000  # 1x total instead of 10x (10,000)
    assert per_page_usage_reads == [100] * 10
    assert sum(per_page_usage_reads) == 1000  # 1x total instead of 10x (10,000)
    assert len(collected_assets) == 1000
    assert set(collected_assets) == expected_asset_ids

    # Subsequent pagination via /api/product-models/assets reads 0 asset.json and 0 usage.json files
    before_pm_asset = read_counts["asset.json"]
    before_pm_usage = read_counts["usage.json"]
    pm_res = c_a.get("/api/product-models/assets?offset=0&limit=100")
    assert pm_res.status_code == 200 and pm_res.json()["total"] == 1000
    assert read_counts["asset.json"] - before_pm_asset == 0
    assert read_counts["usage.json"] - before_pm_usage == 0

    # 2. Paginate 1000 jobs across 10 pages (limit=100) while updating jobs mid-pagination:
    #    Descending order means idx=1000 is first (index 0) and idx=1 is last (index 999).
    #    - Page 1 (offset=0, limit=100) returns jobs 1000..901.
    #    - Before Page 2, update job 850 (which sits on Page 2 at index 150) AND job 995 (on Page 1 at index 5).
    #      Under a naive updatedAt sort, job 850 would jump to index 0 (Page 1) and push job 901 to Page 2,
    #      causing job 850 to be completely missed!
    per_page_job_reads: list[int] = []
    collected_jobs_offset: list[dict] = []
    collected_jobs_cursor: list[dict] = []

    before_p1 = read_counts["job.json"]
    p1_res = c_a.get("/api/print-workspace/jobs?offset=0&limit=100")
    assert p1_res.status_code == 200
    p1 = p1_res.json()
    per_page_job_reads.append(read_counts["job.json"] - before_p1)
    assert per_page_job_reads[0] == 1000
    assert p1["total"] == 1000
    assert len(p1["items"]) == 100
    assert p1["nextCursor"]
    collected_jobs_offset.extend(p1["items"])
    collected_jobs_cursor.extend(p1["items"])

    # Mid-pagination update of a Page-2 job (job 850) and a Page-1 job (job 995)
    job_850_id = f"00000000-0000-0000-0000-{850:012d}"
    job_995_id = f"00000000-0000-0000-0000-{995:012d}"
    assert job_850_id not in {item["id"] for item in p1["items"]}
    assert job_995_id in {item["id"] for item in p1["items"]}

    upd_850 = c_a.put(
        f"/api/print-workspace/jobs/{job_850_id}",
        json={"draft": {**base_draft, "sku": "SKU-0850-UPD", "name": "換頁期間更新商品850"}, "expectedRevision": 1},
    )
    assert upd_850.status_code == 200, upd_850.text
    assert upd_850.json()["revision"] == 2

    upd_995 = c_a.put(
        f"/api/print-workspace/jobs/{job_995_id}",
        json={"draft": {**base_draft, "sku": "SKU-0995-UPD", "name": "換頁期間更新商品995"}, "expectedRevision": 1},
    )
    assert upd_995.status_code == 200, upd_995.text
    assert upd_995.json()["revision"] == 2

    cursor = p1["nextCursor"]
    for page_idx in range(1, 10):
        before = read_counts["job.json"]
        res_off = c_a.get(f"/api/print-workspace/jobs?offset={page_idx * 100}&limit=100")
        assert res_off.status_code == 200
        body_off = res_off.json()
        per_page_job_reads.append(read_counts["job.json"] - before)
        collected_jobs_offset.extend(body_off["items"])

        res_cur = c_a.get(f"/api/print-workspace/jobs?offset={page_idx * 100}&limit=100&cursor={cursor}")
        assert res_cur.status_code == 200
        body_cur = res_cur.json()
        collected_jobs_cursor.extend(body_cur["items"])
        cursor = body_cur["nextCursor"] or ""

    # Page 2 only re-read the 2 updated job.json files (NOT all 1000), and pages 3..10 read 0 files!
    assert per_page_job_reads[1] == 2
    assert per_page_job_reads[2:] == [0] * 8
    assert sum(per_page_job_reads) == 1002  # instead of 10 * 1000 = 10,000

    # Neither offset pagination nor cursor pagination missed any of the 1000 jobs!
    offset_ids = [item["id"] for item in collected_jobs_offset]
    cursor_ids = [item["id"] for item in collected_jobs_cursor]
    assert len(offset_ids) == 1000
    assert len(set(offset_ids)) == 1000
    assert set(offset_ids) == set(expected_job_ids)
    assert len(cursor_ids) == 1000
    assert len(set(cursor_ids)) == 1000
    assert set(cursor_ids) == set(expected_job_ids)

    # Job 850 (updated while on Page 1) was returned on Page 2 with its updated revision=2 and SKU
    fetched_850 = next(item for item in collected_jobs_cursor if item["id"] == job_850_id)
    assert fetched_850["revision"] == 2
    assert fetched_850["draft"]["sku"] == "SKU-0850-UPD"

    # Tenant isolation: tenant-b never sees tenant-a's cached items or cursor results
    b_jobs = c_b.get(f"/api/print-workspace/jobs?cursor={p1['nextCursor']}").json()
    assert b_jobs["total"] == 1
    assert [item["id"] for item in b_jobs["items"]] == [job_b["id"]]
    b_assets = c_b.get("/api/print-workspace/assets").json()
    assert b_assets["total"] == 1
    assert [item["id"] for item in b_assets["items"]] == [real_asset_b["id"]]

    # Boundary / malformed cursor inputs are handled cleanly without leaking internals
    empty_cur = c_a.get("/api/print-workspace/jobs?cursor=&limit=5")
    assert empty_cur.status_code == 200 and len(empty_cur.json()["items"]) == 5
    unknown_cur = c_a.get("/api/print-workspace/jobs?cursor=unknown-cursor-id&offset=0&limit=5")
    assert unknown_cur.status_code == 200 and len(unknown_cur.json()["items"]) == 5
    too_long_cur = c_a.get(f"/api/print-workspace/jobs?cursor={'x' * 201}")
    assert too_long_cur.status_code == 422
    assert str(tmp_path) not in too_long_cur.text and "Traceback" not in too_long_cur.text


def test_ui_fetch_all_pages_1000_jobs_with_mid_pagination_update_loses_no_items() -> None:
    node = shutil.which("node")
    assert node is not None, "node is required for UI pagination verification"

    pagination_js_path = STATIC / "fox3d-pagination.js"
    harness = f"""
    const fs = require('fs');
    const code = fs.readFileSync({json.dumps(str(pagination_js_path))}, 'utf8');
    global.window = {{}};
    eval(code);

    const totalCount = 1000;
    const jobs = Array.from({{ length: totalCount }}, (_, idx) => {{
      const num = totalCount - idx;
      const id = `00000000-0000-0000-0000-${{String(num).padStart(12, '0')}}`;
      const createdAt = `2026-11-18T00:${{String(Math.floor(num / 60)).padStart(2, '0')}}:${{String(num % 60).padStart(2, '0')}}Z`;
      return {{ id, revision: 1, createdAt, updatedAt: createdAt, draft: {{ sku: `SKU-${{num}}` }} }};
    }});

    const calls = [];
    async function mockApi(path) {{
      calls.push(path);
      const u = new URL(path, 'http://localhost');
      const limit = Number(u.searchParams.get('limit') || 100);
      const offset = Number(u.searchParams.get('offset') || 0);
      const cursor = u.searchParams.get('cursor') || '';

      // Simulate a job on page 2 (index 150) being updated AND a new job being created right after page 1 is fetched
      if (calls.length === 2) {{
        jobs[150].revision = 2;
        jobs[150].updatedAt = '2026-11-19T00:00:00Z';
        jobs.unshift({{
          id: '00000000-0000-0000-0000-000000009999',
          revision: 1,
          createdAt: '2026-11-19T01:00:00Z',
          updatedAt: '2026-11-19T01:00:00Z',
          draft: {{ sku: 'SKU-NEW' }},
        }});
      }}

      let filtered = jobs;
      if (cursor && cursor.includes('|')) {{
        const [cTime, cId] = cursor.split('|');
        filtered = jobs.filter(j => (j.createdAt < cTime) || (j.createdAt === cTime && j.id < cId));
      }} else {{
        filtered = jobs.slice(offset);
      }}
      const sliced = filtered.slice(0, limit);
      const last = sliced[sliced.length - 1];
      const nextCursor = (last && last.id !== jobs[jobs.length - 1].id) ? `${{last.createdAt}}|${{last.id}}` : null;
      return {{ items: sliced, total: jobs.length, offset, limit, skipped: 0, nextCursor }};
    }}

    (async () => {{
      const updatedTargetId = jobs[150].id;
      const res = await global.window.fox3dFetchAllPages(mockApi, '/jobs');
      const uniqueIds = new Set(res.items.map(x => x.id));
      const updatedItem = res.items.find(x => x.id === updatedTargetId);
      console.log(JSON.stringify({{
        callCount: calls.length,
        secondCallHasCursor: calls[1].includes('cursor='),
        totalReturned: res.items.length,
        uniqueCount: uniqueIds.size,
        updatedRevision: updatedItem ? updatedItem.revision : 0,
      }}));
    }})();
    """
    proc = subprocess.run([node, "-e", harness], check=True, capture_output=True, text=True, encoding="utf-8", timeout=15)
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["callCount"] == 10
    assert out["secondCallHasCursor"] is True
    assert out["totalReturned"] == 1000
    assert out["uniqueCount"] == 1000
    assert out["updatedRevision"] == 2


