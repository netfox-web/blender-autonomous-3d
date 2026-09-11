"""Provider-neutral Generative Render Gateway V1. Live H3/LTX stay BLOCKED without runtime."""

from __future__ import annotations

from typing import Any

from fox3d.ids import new_id, stable_hash
from fox3d.infra import utcnow
PROVIDERS = ("H3_MAX", "LTX_2_5", "FUTURE_PROVIDER")
QA_DECISIONS = (
    "APPROVED_FOR_ASSET_REVIEW",
    "REJECT_PRODUCT_DRIFT",
    "REJECT_ARTWORK_DRIFT",
    "REJECT_MISSING_EVIDENCE",
)


def route_generative_request(request: dict[str, Any]) -> dict[str, Any]:
    mode = str(request.get("mode") or "IMAGE").upper()
    if mode not in {"IMAGE", "VIDEO"}:
        mode = "IMAGE"
    controls = list(request.get("requiredControls") or ["depth", "normal", "product_mask"])
    prefer = list(request.get("providerPreference") or [])
    if not prefer:
        prefer = ["H3_MAX"] if mode == "IMAGE" else ["LTX_2_5"]
    prefer = [p for p in prefer if p in PROVIDERS] or (["H3_MAX"] if mode == "IMAGE" else ["LTX_2_5"])
    selected = prefer[0]
    reason = (
        f"{mode} prefers {selected} for controls={','.join(controls)}; "
        "live provider availability BLOCKED; quality UNVERIFIED"
    )
    return {
        "mode": mode,
        "requiredControls": controls,
        "providerPreference": prefer,
        "selectedProvider": selected,
        "reason": reason,
        "productLocked": True,
        "qualityClaim": "UNVERIFIED",
        "costLabel": "CONFIG_ESTIMATE",
        "liveProviderAvailable": False,
        "truthLabel": "REAL_LOGIC",
    }


def validate_generative_result(result: dict[str, Any], *, pack: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if not isinstance(result, dict):
        return ["result_missing"]
    if result.get("inputRenderPackId") != pack.get("renderPackId"):
        failures.append("wrong_render_pack")
    if result.get("usedMock") is False:
        evidence = result.get("liveProviderEvidence") if isinstance(result.get("liveProviderEvidence"), dict) else {}
        if not evidence.get("providerRequestId") or not evidence.get("runtime"):
            failures.append("mock_claimed_live_provider")
    if result.get("liveH3MaxProviderReady") is True or result.get("liveLtx25ProviderReady") is True:
        failures.append("fixture_live_provider")
    if result.get("mutatedProductTruth") is True:
        failures.append("product_truth_mutated")
    if pack.get("engineeringHash") and result.get("productTruthEngineeringHash") not in {None, pack.get("engineeringHash")}:
        failures.append("product_truth_mutated")
    return failures


def qa_product_consistency(*, pack: dict[str, Any], generated: dict[str, Any] | None, vision_live: bool = False) -> dict[str, Any]:
    categories = {
        "STRUCTURE": "REAL_LOGIC",
        "ARTWORK/LOGO": "REAL_LOGIC",
        "COLOR": "REAL_LOGIC",
        "SILHOUETTE / PRODUCT MASK": "REAL_LOGIC",
        "CAMERA / FRAMING": "REAL_LOGIC",
        "GENERATED BACKGROUND": "REAL_LOGIC",
    }
    if not vision_live:
        categories["COLOR"] = "MOCK"
    aovs = pack.get("aovs") if isinstance(pack.get("aovs"), dict) else {}
    if not generated:
        return {
            "decision": "REJECT_MISSING_EVIDENCE",
            "categories": categories,
            "liveVisionJudgeReady": False,
            "visionLabel": "MOCK",
            "humanReviewRequired": True,
        }
    gen_pack = generated.get("inputRenderPackId")
    if gen_pack != pack.get("renderPackId"):
        return {
            "decision": "REJECT_PRODUCT_DRIFT",
            "categories": categories,
            "liveVisionJudgeReady": False,
            "visionLabel": "MOCK",
            "humanReviewRequired": True,
        }
    gen_masks = generated.get("masks") if isinstance(generated.get("masks"), dict) else {}
    product = aovs.get("product_mask") or {}
    artwork = aovs.get("artwork_mask") or {}
    if gen_masks.get("productOccupancy") is not None:
        try:
            if abs(float(gen_masks["productOccupancy"]) - float(product.get("occupancy") or 0)) > 0.15:
                return {
                    "decision": "REJECT_PRODUCT_DRIFT",
                    "categories": categories,
                    "liveVisionJudgeReady": False,
                    "visionLabel": "MOCK",
                    "humanReviewRequired": True,
                }
        except (TypeError, ValueError):
            return {
                "decision": "REJECT_MISSING_EVIDENCE",
                "categories": categories,
                "liveVisionJudgeReady": False,
                "visionLabel": "MOCK",
                "humanReviewRequired": True,
            }
    if gen_masks.get("artworkOccupancy") is not None:
        try:
            if abs(float(gen_masks["artworkOccupancy"]) - float(artwork.get("occupancy") or 0)) > 0.15:
                return {
                    "decision": "REJECT_ARTWORK_DRIFT",
                    "categories": categories,
                    "liveVisionJudgeReady": False,
                    "visionLabel": "MOCK",
                    "humanReviewRequired": True,
                }
        except (TypeError, ValueError):
            return {
                "decision": "REJECT_MISSING_EVIDENCE",
                "categories": categories,
                "liveVisionJudgeReady": False,
                "visionLabel": "MOCK",
                "humanReviewRequired": True,
            }
    return {
        "decision": "APPROVED_FOR_ASSET_REVIEW",
        "categories": categories,
        "liveVisionJudgeReady": False,
        "visionLabel": "MOCK",
        "humanReviewRequired": True,
        "productionAsset": False,
    }


class GenerativeRenderGateway:
    def __init__(self, platform: Any) -> None:
        self.platform = platform

    def submit(self, request: dict[str, Any], *, pack: dict[str, Any]) -> dict[str, Any]:
        routing = route_generative_request(request)
        if request.get("renderPackId") not in {None, "", pack.get("renderPackId")}:
            result = {
                "provider": routing["selectedProvider"],
                "providerModel": None,
                "providerRequestId": None,
                "outputArtifacts": [],
                "inputRenderPackId": request.get("renderPackId"),
                "inputLineageHash": None,
                "usedMock": True,
                "status": "BLOCKED",
                "liveH3MaxProviderReady": False,
                "liveLtx25ProviderReady": False,
                "truthLabel": "BLOCKED",
            }
            result["acceptanceFailures"] = validate_generative_result(result, pack=pack)
            return {**result, "routing": routing}
        lineage = {
            "renderPackId": pack.get("renderPackId"),
            "engineeringHash": pack.get("engineeringHash"),
            "artworkHash": pack.get("artworkHash"),
            "placementHash": pack.get("placementHash"),
            "cameraRecipeHash": pack.get("cameraRecipeHash"),
            "sceneRecipeHash": pack.get("sceneRecipeHash"),
            "requiredControls": routing["requiredControls"],
        }
        result = {
            "provider": routing["selectedProvider"],
            "providerModel": f"{routing['selectedProvider']}_FIXTURE",
            "providerRequestId": new_id(),
            "outputArtifacts": [],
            "inputRenderPackId": pack.get("renderPackId"),
            "inputLineageHash": stable_hash(lineage),
            "usedMock": True,
            "status": "MOCK",
            "latency": None,
            "cost": None,
            "costLabel": "CONFIG_ESTIMATE",
            "liveProviderEvidence": None,
            "liveH3MaxProviderReady": False,
            "liveLtx25ProviderReady": False,
            "generativeRenderGatewayLogicReady": True,
            "mutatedProductTruth": False,
            "productTruthEngineeringHash": pack.get("engineeringHash"),
            "truthLabel": "FIXTURE/MOCK",
            "generatedAt": utcnow().isoformat(),
            "routing": routing,
        }
        result["acceptanceFailures"] = validate_generative_result(result, pack=pack)
        result["ok"] = not result["acceptanceFailures"]
        return result
