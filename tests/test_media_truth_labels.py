"""Issue #260: media.py stub/mock outputs must expose truthLabel and not mimic REAL."""

from __future__ import annotations

import json


def _assert_no_real_word(payload: dict) -> None:
    blob = json.dumps(payload, default=str)
    assert "REAL" not in blob, f"MOCK/STUB payload must not contain REAL: {blob[:500]}"


def test_product360_render_mock_truth_label(platform, tmp_path):
    twin = platform.create_twin({"tenantId": "t1", "sku": "SKU-360-TL", "dimensions": {"width": 10, "height": 10, "depth": 10}})
    out = platform.p360.render_mock(tmp_path, twin, frames=36)
    assert out["truthLabel"] == "MOCK"
    _assert_no_real_word(out)


def test_arexporter_stub_truth_and_actual_capabilities(platform, tmp_path):
    twin = platform.create_twin({"tenantId": "t1", "sku": "SKU-AR-TL"})
    exported = platform.ar.export(twin, tmp_path)
    assert exported["truthLabel"] == "STUB"
    assert exported["webFriendly"] is False
    assert exported["planned"]["textureCompression"] == "basis-uastc"
    assert exported["planned"]["meshOptimization"] is True
    assert exported["planned"]["webFriendly"] is True
    for lod in exported["lod"]:
        assert lod["textureCompression"] is None
        assert lod["meshOptimization"] is False
    _assert_no_real_word(exported)


def test_synthetic_factory_manifest_and_generate(platform, tmp_path):
    man = platform.synthetic.generate(tmp_path, job_id="j-tl", twin_id="tw-tl", frames=3)
    assert man["truthLabel"] == "MOCK"
    payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert payload["truthLabel"] == "MOCK"
    _assert_no_real_word(man)
    _assert_no_real_word(payload)


def test_assembly_animator_plan_label(platform):
    created = platform.create_parametric({"tenantId": "t1", "kind": "STORAGE_CABINET", "width": 600})
    anim = platform.assembly.from_component_graph(created["spec"])
    assert anim["truthLabel"] == "PLAN"


def test_retail_engine_plan_label(platform):
    out = platform.retail.propose(space={"kind": "STORE", "width": 3000, "depth": 2000}, brand="FOX", skus=["A"], count=2)
    assert out["truthLabel"] == "PLAN"


def test_blender_to_video_keyframes_plan_label(platform):
    twin = platform.create_twin({"tenantId": "t1", "sku": "SKU-B2V-TL", "dimensions": {"width": 80, "height": 120, "depth": 40}})
    plan = platform.studio.build(twin=twin)
    keys = platform.b2v.keyframes(plan["sceneGraph"])
    assert keys["truthLabel"] == "PLAN"
