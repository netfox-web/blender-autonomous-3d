"""Clean-CODE acceptance using a real local HTTP server and durable draft store.

This exercises the recipe workbench, never Blender or machine controls.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import httpx
import uvicorn
from fastapi import FastAPI
from fox3d.evidence import inspect_repo_lineage
from fox3d.ids import new_id, sha256_bytes
from fox3d.infra import utcnow
from fox3d.recipe_admin_api import recipe_router
from fox3d.recipe_workbench import DEFAULT_CATALOG


@contextmanager
def live_server(root):
    app = FastAPI()
    app.include_router(recipe_router(lambda: SimpleNamespace(root=root)))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{sock.getsockname()[1]}",
                          headers={"X-Tenant-Id": "acceptance"}, timeout=15) as client:
            yield client
    finally:
        server.should_exit = True
        thread.join(15)
        sock.close()
        if thread.is_alive():
            raise RuntimeError("acceptance HTTP server did not stop")


def run(expected_commit):
    lineage = inspect_repo_lineage(ROOT)
    if lineage["evidenceCodeCommit"] != expected_commit:
        raise ValueError("expected CODE commit differs from HEAD")
    checks = []
    original_hash = sha256_bytes(DEFAULT_CATALOG.read_bytes())
    with TemporaryDirectory(prefix="fox3d-recipe-acceptance-") as folder:
        root = Path(folder)
        with live_server(root) as client:
            def ok(response, status=200):
                if response.status_code != status:
                    raise ValueError(f"HTTP {response.status_code}: {response.text[:300]}")
                return response

            assert "商品 Recipe 庫" in ok(client.get("/admin/recipes")).text
            items = ok(client.get("/api/recipe-library")).json()["items"]
            assert len(items) == 3
            for item in items:
                sku = item["draft"]["sku"]
                for source in item["sources"]:
                    if source["mediaType"] == "image/jpeg":
                        image = ok(client.get(f"/api/recipe-library/sources/{sku}/{source['sourceId']}"))
                        assert sha256_bytes(image.content) == source["sha256"]
            checks.append("page_and_three_products_and_seven_source_images")
            draft = {"sku": "QA-HTTP-001", "name": "驗收測試商品", "family": "STACKED_HINGED_CABINET",
                     "values": {"widthMm": {"value": 500, "evidence": "驗收測試值"}}}
            base = "/api/recipe-library/products/QA-HTTP-001"
            saved = ok(client.post("/api/recipe-library/products", json={"expectedRevision": 0, "draft": draft}), 201).json()
            draft = saved["draft"]
            draft["notes"] = "驗收資料，非真實商品尺寸"
            saved = ok(client.put(base, json={"expectedRevision": 1, "draft": draft})).json()
            assert saved["revision"] == 2
            assert client.put(base, json={"expectedRevision": 1, "draft": draft}).status_code == 409
            validation = ok(client.post(base + "/validate")).json()
            assert validation["missingFields"] and not validation["renderReady"]
            checks.append("create_edit_conflict_and_missing_data_validation")
            seed = items[0]
            source = next(s for s in seed["sources"] if s["mediaType"] == "image/jpeg")
            photo = (DEFAULT_CATALOG.parent / source["path"]).read_bytes()
            upload = ok(client.post(base + "/images", files={"file": ("reference.jpg", photo, "image/jpeg")}), 201).json()
            image_path = base + "/images/" + upload["digest"]
            assert ok(client.get(image_path, params={"workspace": "acceptance"})).content == photo
            assert client.get(image_path, params={"workspace": "another"}).status_code == 404
            checks.append("upload_retrieve_and_workspace_isolation")
            exported = ok(client.get("/api/recipe-library/export", params={"sku": draft["sku"]})).json()
            imported = ok(client.post("/api/recipe-library/import", headers={"X-Tenant-Id": "import-target"}, json=exported)).json()
            assert imported["items"][0]["draft"] == draft
            assert not imported["items"][0]["uploads"]
            assert not imported["items"][0]["engineeringReady"]
            assert client.post("/api/recipe-library/import", json=exported).status_code == 409
            checks.append("export_import_and_duplicate_protection")
        # A different server/router instance proves SQLite and file persistence.
        with live_server(root) as client:
            reopened = client.get(base).json()
            assert reopened["revision"] == 2 and reopened["draft"] == draft
            assert client.get(image_path, params={"workspace": "acceptance"}).content == photo
            checks.append("server_restart_retains_draft_and_image")
    assert sha256_bytes(DEFAULT_CATALOG.read_bytes()) == original_hash
    inspect_repo_lineage(ROOT)
    return {"ok": True, "generationId": new_id(), "generatedAt": utcnow().isoformat(),
            "evidenceCodeCommit": expected_commit, "workingTreeClean": True,
            "executionMode": "LIVE_LOCAL_HTTP", "checks": checks,
            "supplierCatalogUnchanged": True, "browserAutomation": False,
            "realBlenderAcceptance": False, "engineeringReady": False, "productionReady": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args(argv)
    report = run(args.expected_commit)
    output = ROOT / ".fox3d-data/recipe-admin-acceptance" / report["generationId"] / "report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(output)}))


if __name__ == "__main__":
    main()
