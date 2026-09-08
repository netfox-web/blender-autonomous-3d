"""Scoped readiness model + truth-label validator. No global productionReady cover-up."""

from __future__ import annotations

from typing import Any

READY_KEYS = (
    "coreRenderE2EReady",
    "kdPrototypeReady",
    "retailPrototypeReady",
    "packagingPrototypeReady",
    "acrylicPrototypeReady",
    "commercialPricingReady",
    "liveProviderReady",
    "machineControlReady",
    "fullAutonomousFactoryReady",
)

BLOCKING_FOR_FULL = (
    "liveProviderReady",
    "machineControlReady",
    "liveVisionReady",
    "liveDemandReady",
    "osSandboxReady",
)


def scoped_readiness(*, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    ev = evidence or {}
    live_provider = bool(ev.get("liveProvider"))
    machine = bool(ev.get("liveMachine"))
    vision = bool(ev.get("liveVision"))
    demand = bool(ev.get("liveDemand"))
    jail = bool(ev.get("osJail"))
    matrix = {
        "coreRenderE2EReady": bool(ev.get("coreRender", True)),
        "kdPrototypeReady": bool(ev.get("kd", True)),
        "retailPrototypeReady": bool(ev.get("retail", True)),
        "packagingPrototypeReady": bool(ev.get("packaging", True)),
        "acrylicPrototypeReady": bool(ev.get("acrylic", True)),
        "commercialPricingReady": bool(ev.get("importedCost") or ev.get("configCost")),
        "liveProviderReady": live_provider,
        "machineControlReady": machine,
        "liveVisionReady": vision,
        "liveDemandReady": demand,
        "osSandboxReady": jail,
        "fullAutonomousFactoryReady": False,
        "labels": {
            "commercialPricingReady": "IMPORTED" if ev.get("importedCost") else "CONFIG_ESTIMATE",
            "liveProviderReady": "LIVE_PROVIDER" if live_provider else "BLOCKED",
            "machineControlReady": "BLOCKED",
            "liveVisionReady": "MOCK",
            "liveDemandReady": "MOCK",
            "osSandboxReady": "PARTIAL",
        },
        "globalProductionReady": False,
        "humanApprovalGate": True,
        "liveMachineControl": False,
    }
    matrix["fullAutonomousFactoryReady"] = all(
        [
            matrix["coreRenderE2EReady"],
            matrix["kdPrototypeReady"],
            matrix["liveProviderReady"],
            matrix["machineControlReady"],
            vision,
            demand,
            jail,
        ]
    )
    return matrix


def validate_truth_labels(payload: dict[str, Any]) -> list[str]:
    """Return violation codes. Empty list means the payload is honest."""
    issues: list[str] = []
    source = str(payload.get("source") or payload.get("costSource") or payload.get("label") or "")
    label = str(payload.get("truthLabel") or payload.get("status") or payload.get("label") or "")
    if source.upper() in {"MOCK", "UNAVAILABLE"} and label.upper() == "REAL":
        issues.append("MOCK_MARKED_REAL")
    if str(payload.get("costSource") or "").upper() in {"CONFIG", "ESTIMATED", "CONFIG_ESTIMATE", "MANUAL", "IMPORTED"} and str(
        payload.get("providerLabel") or payload.get("truthLabel") or ""
    ).upper() in {"REAL_PROVIDER", "LIVE_PROVIDER"}:
        issues.append("CONFIG_MARKED_LIVE_PROVIDER")
    if payload.get("liveMachineControl") is True or payload.get("machineControlReady") is True:
        issues.append("BLOCKED_MACHINE_MARKED_READY")
    if payload.get("fullAutonomousFactoryReady") is True:
        blockers = [k for k in BLOCKING_FOR_FULL if not payload.get(k)]
        if blockers or payload.get("vision") == "MOCK" or payload.get("demand") == "MOCK":
            issues.append("FULL_READY_WITH_BLOCKERS")
    if payload.get("globalProductionReady") is True and payload.get("fullAutonomousFactoryReady") is not True:
        issues.append("GLOBAL_PRODUCTION_READY_UNSCOPED")
    return issues
