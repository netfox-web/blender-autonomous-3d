"""Preview geometry, truthful asset boundaries and background lifecycle."""
import copy
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fox3d.recipe_3d import (build_recipe_spec, resolve_recipe_preview_assumptions,
    get_recipe_3d_dir, get_recipe_3d_status, atomic_json, input_hash, generate_recipe_3d_product)
from fox3d.recipe_admin_api import recipe_router
from fox3d.recipe_workbench import RecipeWorkbench
from fox3d.recipe_preview_service import RecipePreviewService

HEADERS = {"X-Tenant-Id": "sonaqueen-home"}

@pytest.fixture
def drafts(tmp_path):
    store = RecipeWorkbench(tmp_path)
    return {sku: store.get("sonaqueen-home", sku)["draft"] for sku in ("MY-012", "LI-D40", "LI-PU63D-免組裝")}

@pytest.mark.parametrize("sku,rows,doors,dividers", [("MY-012",6,0,6),("LI-D40",4,4,0),("LI-PU63D-免組裝",3,3,3)])
def test_seed_topology_and_actual_outer_bounds(drafts,sku,rows,doors,dividers):
    spec = build_recipe_spec(drafts[sku])
    parts = spec["components"]
    assert sum(p["role"] == "door" for p in parts) == doors
    assert sum(p["role"] == "divider" for p in parts) == dividers
    assert sum(p["role"] == "shelf" for p in parts) == rows-1
    for axis, size in enumerate([spec["width"],spec["depth"],spec["height"]]):
        low = min(p["location"][axis]-p["size"][axis]/2 for p in parts)
        high = max(p["location"][axis]+p["size"][axis]/2 for p in parts)
        assert high-low == pytest.approx(size/1000)
    door_parts = [p for p in parts if p["role"] == "door"]
    assert len({p["location"][2] for p in door_parts}) == doors
    assert not spec["engineeringReady"] and not spec["productionReady"]

@pytest.mark.parametrize("sku,key", [("MY-012","panelThicknessMm"),("LI-D40","panelThicknessMm"),("LI-PU63D-免組裝","sidePanelThicknessMm")])
def test_canonical_thickness_honored(drafts,sku,key):
    drafts[sku]["values"][key] = {"value":18,"evidence":"test drawing"}
    result = resolve_recipe_preview_assumptions(drafts[sku])
    assert result["resolved"]["boardThicknessMm"] == 18
    assert key not in [a["field"] for a in result["assumptions"]]
    if sku.startswith("LI-PU"):
        assert result["resolved"]["fixedPanelThicknessMm"] == 25

@pytest.mark.parametrize("field", ["widthMm","depthMm","heightMm","rowCount","compartmentCount","doorCount"])
def test_missing_core_has_no_fabricated_defaults(drafts,field):
    del drafts["MY-012"]["values"][field]
    with pytest.raises(ValueError,match="生成前請先填寫"):
        build_recipe_spec(drafts["MY-012"])

def test_exact_divider_coordinates(drafts):
    d=drafts["MY-012"]
    d["values"]["rowDividerCoordinates"]={"value":"100, 200, 300, 400, 200, 100"}
    assert resolve_recipe_preview_assumptions(d)["resolved"]["dividerCentersMm"] == [100,200,300,400,200,100]
    d["values"]["rowDividerCoordinates"]={"value":"nan 2 3 4 5 6"}
    with pytest.raises(ValueError): build_recipe_spec(d)

def test_incompatible_topology_rejected(drafts):
    drafts["LI-D40"]["values"]["doorCount"]={"value":2}
    with pytest.raises(ValueError,match="每行"):
        build_recipe_spec(drafts["LI-D40"])

def test_path_identity_isolation(tmp_path):
    assert get_recipe_3d_dir(tmp_path,"a/b","SKU") != get_recipe_3d_dir(tmp_path,"a_b","SKU")
    assert get_recipe_3d_dir(tmp_path,"a","../outside").is_relative_to(tmp_path)

def test_mock_never_claims_real_model(tmp_path,drafts):
    with pytest.raises(RuntimeError,match="Blender"):
        generate_recipe_3d_product(SimpleNamespace(root=tmp_path,mock_blender=True),"a","MY-012",drafts["MY-012"])
    assert not get_recipe_3d_status(tmp_path,"a","MY-012")["generated"]

def test_status_stale_and_missing_files(tmp_path,drafts):
    d=drafts["MY-012"]
    folder=get_recipe_3d_dir(tmp_path,"a","MY-012")
    atomic_json(folder/"meta.json", {"generationId":"11111111-1111-1111-1111-111111111111","inputHash":input_hash(d),"renderInfo":{"realBlender":True,"usedMock":False}})
    status=get_recipe_3d_status(tmp_path,"a","MY-012",current_draft=d)
    assert not status["generated"] and not status["stale"]
    d["values"]["widthMm"]["value"]+=1
    assert get_recipe_3d_status(tmp_path,"a","MY-012",current_draft=d)["stale"]

@pytest.fixture
def client(tmp_path):
    app=FastAPI()
    app.include_router(recipe_router(lambda:SimpleNamespace(root=tmp_path)))
    with TestClient(app) as c: yield c

def test_api_requires_current_confirmed_plan_and_real_backend(client):
    base="/api/recipe-library/products/MY-012/3d"
    plan=client.get(base+"/plan",headers=HEADERS).json()
    assert plan["ready"] and plan["assumptions"] and not plan["blenderAvailable"]
    body={"expectedRevision":plan["revision"],"planHash":plan["planHash"],"assumptionsAccepted":True}
    assert client.post(base+"/generate",headers=HEADERS,json=body).status_code==503
    body["assumptionsAccepted"]=False
    assert client.post(base+"/generate",headers=HEADERS,json=body).status_code==422
    body.update(assumptionsAccepted=True,planHash="outdated")
    assert client.post(base+"/generate",headers=HEADERS,json=body).status_code==409
    assert client.get(base+"/render",headers=HEADERS).status_code==404
    assert client.get("/api/recipe-library/products/unknown/3d/status",headers=HEADERS).status_code==404
    assert client.get("/admin/recipes/assets/recipe-viewer.js").status_code==200

def wait_done(service,sku,draft):
    for _ in range(200):
        result=service.status("t",sku,draft)
        if result["state"] not in {"queued","running"}: return result
        time.sleep(.01)
    raise AssertionError("background task did not finish")

def test_background_cancel_duplicate_and_failure(tmp_path,drafts,monkeypatch):
    started=threading.Event()
    def renderer(*args,**kwargs):
        started.set()
        kwargs["cancel_flag"].wait(2)
        raise RuntimeError("render interrupted")
    monkeypatch.setattr("fox3d.recipe_preview_service.generate_recipe_3d_product",renderer)
    service=RecipePreviewService(SimpleNamespace(root=tmp_path))
    d=drafts["MY-012"];item={"revision":0,"draft":d}
    task=service.submit("t","MY-012",item)
    assert started.wait(1)
    with pytest.raises(ValueError): service.submit("t","MY-012",item)
    service.cancel("t","MY-012",task["taskId"])
    assert wait_done(service,"MY-012",d)["state"]=="cancelled"
    def failed(*args,**kwargs): raise RuntimeError("export failed")
    monkeypatch.setattr("fox3d.recipe_preview_service.generate_recipe_3d_product",failed)
    service.submit("t","MY-012",item)
    status=wait_done(service,"MY-012",d)
    assert status["state"]=="failed" and status["error"]=="export failed"
    service.executor.shutdown()

def test_interrupted_process_is_recoverable(tmp_path,drafts):
    atomic_json(get_recipe_3d_dir(tmp_path,"t","MY-012")/"state.json",
                {"state":"running","taskId":"old","inputHash":input_hash(drafts["MY-012"])})
    service=RecipePreviewService(SimpleNamespace(root=tmp_path))
    status=service.status("t","MY-012",drafts["MY-012"])
    assert status["state"]=="failed" and "中斷" in status["error"]
    service.executor.shutdown()


def test_verified_download_unicode_and_corruption(client,tmp_path,drafts):
    # Synthetic bytes exercise routing/integrity only; live model validity is tested by the Blender runner.
    from fox3d.recipe_3d import FILES
    from fox3d.ids import sha256_bytes
    sku="LI-PU63D-免組裝";tid="sonaqueen-home";gid="22222222-2222-2222-2222-222222222222"
    base=get_recipe_3d_dir(tmp_path,tid,sku);folder=base/"generations"/gid
    folder.mkdir(parents=True)
    files={}
    for fmt,name in FILES.items():
        data=("unit-test-only-"+fmt).encode()
        (folder/name).write_bytes(data)
        files[fmt]={"sha256":sha256_bytes(data),"sizeBytes":len(data)}
    meta={"generationId":gid,"sku":sku,"tenantId":tid,"files":files,"inputHash":input_hash(drafts[sku]),"renderInfo":{"realBlender":True,"usedMock":False}}
    atomic_json(folder/"meta.json",meta);atomic_json(base/"meta.json",meta)
    atomic_json(base/"state.json", {"state": "succeeded", "progress": 100})
    url="/api/recipe-library/products/"+sku+"/3d"
    response=client.get(url+"/download/blend",headers=HEADERS)
    assert response.status_code==200 and "filename*=utf-8''" in response.headers["content-disposition"]
    assert client.get(url+"/download/glb",headers={"X-Tenant-Id":"other"}).status_code==404
    assert client.get(url+"/download/png",headers=HEADERS,params={"generation":"../invalid"}).status_code==404
    (folder/"model.glb").write_bytes(b"modified")
    damaged = client.get(url+"/status",headers=HEADERS).json()
    assert not damaged["generated"] and damaged["state"] == "failed"
    assert "檔案驗證失敗" in damaged["error"]
    assert client.get(url+"/download/blend",headers=HEADERS).status_code==404


def test_adapter_rejects_missing_real_exports(tmp_path,drafts):
    plat=SimpleNamespace(root=tmp_path,mock_blender=False,runtime=SimpleNamespace(available=lambda:True),probe=None)
    plat.submit_job=lambda job:job
    plat.execute_job=lambda job,**kwargs:{"status":"completed","realBlender":True,"usedMock":False,"output":{"files":{}}}
    with pytest.raises(ValueError,match="beauty.png"):
        generate_recipe_3d_product(plat,"t","MY-012",drafts["MY-012"])
    assert not get_recipe_3d_status(tmp_path,"t","MY-012")["generated"]
