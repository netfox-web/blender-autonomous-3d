"""Real HTTP + Blender acceptance, bound to the current clean CODE commit."""
import argparse
import hashlib
import json
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-dirty", action="store_true", help="Development check only; never acceptance")
    args = parser.parse_args()
    import httpx
    from fox3d.recipe_3d import validate_outputs
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    clean = not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if not clean and not args.allow_dirty:
        raise SystemExit("Real acceptance requires a clean CODE working tree")
    gid = str(uuid.uuid4())
    folder = ROOT / ".fox3d-work" / "recipe-studio-e2e" / gid
    folder.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log = (folder / "server.log").open("w", encoding="utf-8")
    command = [sys.executable, str(ROOT / "scripts/run_recipe_admin.py"), "--port", str(port), "--data-root", str(folder / "data")]
    def start():
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(180):
            if process.poll() is not None:
                raise RuntimeError("Server stopped; see " + str(folder / "server.log"))
            try:
                if client.get("/api/recipe-library/health").status_code == 200:
                    return process
            except httpx.HTTPError:
                pass
            time.sleep(1)
        process.terminate()
        raise RuntimeError("Server startup timeout")
    evidence = {"generationId": gid, "evidenceCodeCommit": sha, "workingTreeClean": clean,
                "developmentOnly": args.allow_dirty, "mode": "LIVE_LOCAL_HTTP_BLENDER", "usedMock": False, "products": []}
    process = None
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers={"X-Tenant-Id": "sonaqueen-home"}, timeout=30) as client:
            process = start()
            assert client.get("/admin/recipes").status_code == 200
            assert client.get("/api/recipe-library/health").json()["blenderAvailable"]
            for item in client.get("/api/recipe-library").json()["items"]:
                sku = item["draft"]["sku"]
                base = "/api/recipe-library/products/" + quote(sku, safe="") + "/3d"
                plan = client.get(base + "/plan").json()
                assert plan["ready"] and plan["assumptions"]
                started = client.post(base + "/generate", json={"expectedRevision": plan["revision"], "planHash": plan["planHash"], "assumptionsAccepted": True})
                assert started.status_code == 202, started.text
                deadline = time.monotonic() + 720
                while time.monotonic() < deadline:
                    status = client.get(base + "/status").json()
                    if status["state"] not in {"queued", "running"}:
                        break
                    time.sleep(2)
                assert status["state"] == "succeeded" and status["generated"], status
                assert status["renderInfo"]["realBlender"] and not status["renderInfo"]["usedMock"]
                download_dir = folder / sku
                download_dir.mkdir()
                for fmt, name in [("png", "beauty.png"), ("blend", "model.blend"), ("glb", "model.glb")]:
                    response = client.get(base + "/download/" + fmt, params={"generation": status["generationId"]})
                    assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
                    (download_dir / name).write_bytes(response.content)
                from fox3d.recipe_3d import get_recipe_3d_dir
                actual = get_recipe_3d_dir(folder / "data", "sonaqueen-home", sku) / "generations" / status["generationId"] / "geometry.json"
                (download_dir / "geometry.json").write_bytes(actual.read_bytes())
                hashes = validate_outputs(download_dir, status["spec"])
                from fox3d.blender import find_blender
                reopen = subprocess.run([find_blender(), "-b", str(download_dir / "model.blend"), "--python-exit-code", "1", "--python-expr",
                    "import bpy; parts=[o for o in bpy.data.objects if o.get('recipeComponentId')]; "
                    + f"assert len(parts)=={len(status['spec']['components'])}; print('RECIPE_BLEND_REOPEN_PASS')"],
                    capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                assert reopen.returncode == 0 and b"RECIPE_BLEND_REOPEN_PASS" in reopen.stdout, reopen.stderr[-2000:]
                evidence["products"].append({"sku": sku, "generationId": status["generationId"], "renderInfo": status["renderInfo"],
                    "parts": len(status["spec"]["components"]), "files": hashes, "sourceRevision": status["sourceRevision"], "blendReopenVerified": True})
                print(json.dumps({"sku": sku, "state": "verified", "parts": len(status["spec"]["components"])}, ensure_ascii=True), flush=True)
            process.terminate(); process.wait(timeout=30)
            process = start()
            for product in evidence["products"]:
                status = client.get("/api/recipe-library/products/" + quote(product["sku"], safe="") + "/3d/status").json()
                assert status["generated"] and status["generationId"] == product["generationId"]
            evidence.update(status="PASS", restartPersistenceVerified=True, engineeringReady=False, productionReady=False)
    except Exception as exc:
        evidence.update(status="FAIL", error=str(exc))
        raise
    finally:
        if process and process.poll() is None:
            process.terminate(); process.wait(timeout=30)
        log.close()
        (folder / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        print(str(folder / "evidence.json"), flush=True)


if __name__ == "__main__":
    main()
