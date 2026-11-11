"""Unit tests for fox3d.rd — offline, no Blender, no network."""

from __future__ import annotations

import pytest

from fox3d.parametric import CabinetSpec
from fox3d.rd import (
    GatewayVisionProvider,
    HeuristicVisionProvider,
    ProductRDAgent,
    VariantGenerator,
    VisionJudge,
)


def _cabinet_spec(**overrides: object) -> CabinetSpec:
    base = {
        "tenantId": "t-rd",
        "kind": "STORAGE_CABINET",
        "width": 800.0,
        "height": 1800.0,
        "depth": 400.0,
        "doorCount": 2,
        "shelfCount": 3,
        "drawerCount": 1,
        "material": "particle_board",
    }
    base.update(overrides)
    return CabinetSpec.model_validate(base)


def _variant_shape(row: dict) -> dict:
    return {k: v for k, v in row.items() if k != "variantId"}


class _FakeGateway:
    def __init__(self, adapters: dict | None = None) -> None:
        self._vision_adapters = adapters or {}


# --- VariantGenerator ---


def test_variant_generator_count_zero_clamps_to_minimum() -> None:
    spec = _cabinet_spec()
    out = VariantGenerator().generate(spec, count=0)
    assert len(out) == 10


def test_variant_generator_count_one_clamps_to_minimum() -> None:
    spec = _cabinet_spec()
    out = VariantGenerator().generate(spec, count=1)
    assert len(out) == 10


def test_variant_generator_count_twelve() -> None:
    spec = _cabinet_spec()
    out = VariantGenerator().generate(spec, count=12)
    assert len(out) == 12


def test_variant_generator_dimensions_within_bounds() -> None:
    spec = _cabinet_spec(width=500, height=2000, depth=350)
    for row in VariantGenerator().generate(spec, count=12):
        dims = row["dimensions"]
        assert dims["width"] >= 400
        assert dims["height"] == spec.height
        assert dims["depth"] == spec.depth
        assert row["shelf"] >= 0
        assert row["door"] >= 0


def test_variant_generator_same_input_same_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = (f"vid-{i}" for i in range(60))

    def _next_id() -> str:
        return next(ids)

    monkeypatch.setattr("fox3d.rd.new_id", _next_id)
    spec = _cabinet_spec()
    gen = VariantGenerator()
    a = [_variant_shape(v) for v in gen.generate(spec, count=12)]
    b = [_variant_shape(v) for v in gen.generate(spec, count=12)]
    assert a == b


# --- HeuristicVisionProvider ---


def test_heuristic_vision_provider_mock_scores() -> None:
    provider = HeuristicVisionProvider()
    assert provider.status == "MOCK"
    good = provider.score_image(
        preview={
            "sceneGraph": {"objects": [{}], "camera": {"fill": 0.6}},
            "dsl": {"scene": "WHITE_STUDIO"},
        }
    )
    assert good["composition"] == 0.9
    assert good["product_visibility"] == 0.85
    weak = provider.score_image(preview={"sceneGraph": {"camera": {"fill": 0.2}}, "dsl": {}})
    assert weak["composition"] == 0.55
    assert weak["product_visibility"] == 0.2


# --- VisionJudge ---


def test_vision_judge_none_spec_quote_with_veto() -> None:
    judge = VisionJudge()
    out = judge.score(preview={"variantId": "v1"}, spec=None, quote=None, report_ok=False)
    assert out["engineeringVeto"] is True
    assert out["overall"] <= 0.2
    assert out["scores"]["engineering_validity"] == 0.2
    assert out["scores"]["manufacturability"] == 0.3
    assert out["label"] == "MOCK"


def test_vision_judge_report_ok_false_does_not_claim_pass() -> None:
    spec = _cabinet_spec(metadata={"wallWidth": 3600})
    judge = VisionJudge()
    out = judge.score(
        preview={
            "variantId": "v2",
            "sceneGraph": {"objects": [{}], "camera": {"fill": 0.7}},
            "dsl": {"scene": "LIFESTYLE"},
        },
        spec=spec,
        quote={"estimatedCost": 12000},
        report_ok=False,
    )
    assert out["engineeringVeto"] is True
    assert out["overall"] <= 0.2
    assert out["visionScore"] > 0.5


def test_vision_judge_report_ok_true_combined_score() -> None:
    spec = _cabinet_spec(metadata={"wallWidth": 1200})
    judge = VisionJudge()
    out = judge.score(
        preview={
            "variantId": "v3",
            "sceneGraph": {"objects": [{}], "camera": {"fill": 0.7}},
            "dsl": {"scene": "WHITE_STUDIO"},
        },
        spec=spec,
        quote={"estimatedCost": 12000},
        report_ok=True,
    )
    assert out["engineeringVeto"] is False
    assert out["overall"] > 0.2
    assert out["scores"]["engineering_validity"] == 1.0


# --- GatewayVisionProvider ---


def test_gateway_vision_status_mock_when_no_adapters() -> None:
    gw = GatewayVisionProvider(_FakeGateway())
    assert gw.status == "MOCK"
    scores = gw.score_image(preview={"sceneGraph": {"objects": [{}], "camera": {"fill": 0.7}}, "dsl": {"scene": "x"}})
    assert scores["composition"] == 0.9


def test_gateway_vision_status_real_when_adapters_present() -> None:
    gw = GatewayVisionProvider(
        _FakeGateway({"default": lambda p: {"composition": 0.88, "aesthetics": 0.77, "product_visibility": 0.66, "brand_consistency": 0.55}})
    )
    assert gw.status == "REAL"
    scores = gw.score_image(preview={})
    assert scores == {"composition": 0.88, "aesthetics": 0.77, "product_visibility": 0.66, "brand_consistency": 0.55}


def test_gateway_vision_adapter_exception_not_swallowed() -> None:
    def _boom(_preview: dict) -> dict:
        raise RuntimeError("gateway down")

    gw = GatewayVisionProvider(_FakeGateway({"live": _boom}))
    assert gw.status == "REAL"
    with pytest.raises(RuntimeError, match="gateway down"):
        gw.score_image(preview={})


def test_gateway_vision_adapter_missing_numeric_fields_fallback_values() -> None:
    gw = GatewayVisionProvider(_FakeGateway({"live": lambda p: {"composition": "n/a", "note": "skip"}}))
    scores = gw.score_image(preview={})
    assert scores == {}
    judge = VisionJudge(gw)
    verdict = judge.score(preview={"variantId": "x"}, spec=None, quote=None, report_ok=True)
    assert verdict["provider"]["status"] == "REAL"
    assert verdict["scores"]["composition"] == 0.5
    assert verdict["engineeringVeto"] is False


# --- ProductRDAgent ---


def test_product_rd_agent_run_waits_for_human(platform) -> None:
    result = platform.rd.run(tenant_id="t-rd", text="做一個收納櫃 80cm 寬", variant_count=10)
    assert result["approval"]["status"] == "WAITING_APPROVAL"
    assert result["productionAssets"] == []
    assert result["scoredCount"] >= 1
    assert result["pipeline"][-2] == "human_approval_gate"


def test_product_rd_agent_auto_approve_forbidden(platform) -> None:
    result = platform.rd.run(tenant_id="t-rd", text="鞋櫃", variant_count=10, auto_approve=True)
    assert result["approval"]["status"] == "WAITING_APPROVAL"
    assert result["productionAssets"] == []


def test_product_rd_agent_approve_sets_actor_and_assets(platform) -> None:
    rd = platform.rd.run(tenant_id="t-rd", text="書櫃 80cm", variant_count=10)
    approved = platform.rd.approve(rd, actor="qa-lead")
    assert approved["approval"]["status"] == "APPROVED"
    assert approved["approval"]["actor"] == "qa-lead"
    assert approved["productionAssets"]
    assert all(item["kind"] == "production_candidate" for item in approved["productionAssets"])


def test_product_rd_agent_repeated_approve_idempotent(platform) -> None:
    rd = platform.rd.run(tenant_id="t-rd", text="床頭櫃", variant_count=10)
    first = platform.rd.approve(rd, actor="owner-a")
    second = platform.rd.approve(first, actor="owner-b")
    assert second["approval"]["status"] == "APPROVED"
    assert second["approval"]["actor"] == "owner-b"
    assert len(second["productionAssets"]) == len(first["productionAssets"])


def test_product_rd_agent_approve_requires_actor_keyword() -> None:
    agent = ProductRDAgent(None, None, VisionJudge(), None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        agent.approve({"top": []})
