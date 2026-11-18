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

    # Sending release twice for the same proofId returns the existing release and keeps it valid
    rel_body = _release_payload(1, p["planHash"], proof_1.json()["bundleId"])
    rel_1 = c.post(f"/api/print-workspace/jobs/{j['id']}/release", json=rel_body)
    rel_2 = c.post(f"/api/print-workspace/jobs/{j['id']}/release", json=rel_body)
    assert rel_1.status_code == 200 and rel_2.status_code == 200
    assert rel_1.json()["bundleId"] == rel_2.json()["bundleId"]
    assert len([d for d in bundles_dir.iterdir() if d.is_dir()]) == 2

    dl = c.get(f"/api/print-workspace/jobs/{j['id']}/bundles/{rel_1.json()['bundleId']}?workspace=tenant-a")
    assert dl.status_code == 200


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
        proc = subprocess.run([node, "-e", harness], check=True, capture_output=True, text=True, timeout=15)
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

