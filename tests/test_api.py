from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.platform import Platform


def _gpu(name: str, vram: float) -> dict:
    return {
        "blender": True,
        "blenderVersion": "mock-4.2",
        "cuda": True,
        "optix": True,
        "gpuCount": 1,
        "gpuName": name,
        "vramGb": vram,
        "driver": "mock",
        "gpus": [{"gpuIndex": 0, "name": name, "vramGb": vram, "freeVramGb": vram}],
    }


def test_api_job_twin_parametric_rd(tmp_path):
    plat = Platform(root=tmp_path / "data", mock_blender=True)  # API unit test — not production acceptance
    plat.register_node(target_key="5080-1", name="5080", detected=_gpu("NVIDIA GeForce RTX 5080", 16))
    client = TestClient(create_app(plat))
    headers = {"X-Tenant-Id": "acme"}
    assert client.get("/health").json()["status"] == "ok"

    twin = client.post("/api/digital-twins", json={"sku": "A-1", "dimensions": {"width": 100, "height": 120, "depth": 40}}, headers=headers)
    assert twin.status_code == 200, twin.text
    twin_id = twin.json()["twinId"]
    got = client.get(f"/api/digital-twins/{twin_id}", headers=headers)
    assert got.status_code == 200

    denied = client.get(f"/api/digital-twins/{twin_id}", headers={"X-Tenant-Id": "other"})
    assert denied.status_code == 404

    job = client.post("/api/3d/jobs", json={"jobType": "BLENDER_PREVIEW", "scene": "WHITE_STUDIO"}, headers=headers)
    assert job.status_code == 200
    job_id = job.json()["jobId"]
    assert client.get(f"/api/3d/jobs/{job_id}", headers=headers).status_code == 200
    cancelled = client.post(f"/api/3d/jobs/{job_id}/cancel", headers=headers)
    assert cancelled.json()["status"] == "cancelled"

    preview = client.post("/api/render/preview", json={"scene": "WHITE_STUDIO"}, headers=headers)
    assert preview.status_code == 200
    assert preview.json()["status"] == "succeeded"

    final = client.post("/api/render/final", json={"scene": "BLACK_LUXURY"}, headers=headers)
    assert final.json()["output"]["device"] == "OPTIX"

    para = client.post("/api/parametric/products", json={"kind": "SHOE_CABINET", "width": 800}, headers=headers)
    assert para.status_code == 200
    assert para.json()["report"]["ok"] is True

    rd = client.post("/api/product-rd/generate", json={"text": "做一個書櫃 80cm 寬"}, headers=headers)
    assert rd.status_code == 200
    assert rd.json()["approval"]["status"] == "WAITING_APPROVAL"

    admin = client.get("/admin")
    assert admin.status_code == 200
    assert "Blender UI" in admin.text
    assert "3D Jobs" in admin.text
