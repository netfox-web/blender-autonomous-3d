"""HTTP API for small-space KD SKU portfolio planning (tenant-scoped)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, NoReturn

from fastapi import APIRouter, Body, Header, HTTPException

from fox3d.infra import validate_tenant_id
from fox3d.operator import require_confirm
from fox3d.portfolio import PortfolioError

_APPROVE_LOCKS: dict[int, threading.Lock] = {}
_APPROVE_GUARD = threading.Lock()


def _approve_lock(factory: Any) -> threading.Lock:
    key = id(factory)
    with _APPROVE_GUARD:
        if key not in _APPROVE_LOCKS:
            _APPROVE_LOCKS[key] = threading.Lock()
        return _APPROVE_LOCKS[key]


def _tenant(x_tenant_id: str | None) -> str:
    try:
        return validate_tenant_id(x_tenant_id or "")
    except ValueError as exc:
        raise HTTPException(400, "X-Tenant-Id 無效") from exc


def _require_tenant(x_tenant_id: str | None, payload: dict[str, Any] | None = None) -> str:
    header = _tenant(x_tenant_id)
    body_tid = (payload or {}).get("tenantId")
    if body_tid is None or body_tid == "":
        return header
    if not isinstance(body_tid, str):
        raise HTTPException(422, "body tenantId must be a string")
    if body_tid != header:
        raise HTTPException(403, "body tenantId does not match X-Tenant-Id")
    return header


def _require_body(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(422, "請求內容須為 JSON 物件")
    return payload


def _actor_reason(body: dict[str, Any], *, require_reason: bool) -> tuple[str, str]:
    actor = body.get("actor")
    if not isinstance(actor, str) or not actor.strip():
        raise HTTPException(422, "actor 必填")
    reason = body.get("reason")
    if require_reason:
        if not isinstance(reason, str) or not reason.strip():
            raise HTTPException(422, "reason 必填")
        text = reason.strip()
        if not (1 <= len(text) <= 200):
            raise HTTPException(422, "reason 長度須為 1–200 字")
        return actor.strip(), text
    return actor.strip(), str(reason or "").strip()


def _map_portfolio_error(exc: BaseException) -> NoReturn:
    if isinstance(exc, KeyError):
        raise HTTPException(404, "找不到組合需求或候選") from exc
    if isinstance(exc, PortfolioError):
        if exc.code == "NEEDS_INPUT":
            raise HTTPException(400, "請求內容不完整或無效") from exc
        raise HTTPException(400, "請求無法完成") from exc
    if isinstance(exc, PermissionError):
        msg = str(exc)
        if msg.startswith("tenant isolation"):
            raise HTTPException(404, "找不到組合需求或候選") from exc
        if "confirm" in msg:
            raise HTTPException(403, "需要確認") from exc
        raise HTTPException(403, "無權限") from exc
    raise exc


def _ranking_view(pf: Any, ranking: dict[str, Any]) -> dict[str, Any]:
    stale_ids: list[str] = []
    for row in ranking.get("scored") or []:
        cid = row.get("candidateId")
        if not cid or cid not in pf.candidates:
            continue
        rec = pf.candidates[cid]
        if (rec.get("commercial") or {}).get("stale"):
            stale_ids.append(str(cid))
    out = dict(ranking)
    out["demandReal"] = False
    out["demandEstimateLabel"] = "需求為估計值"
    if stale_ids:
        out["staleCostHints"] = sorted(set(stale_ids))
    return out


def portfolio_router(provider: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    def pf() -> Any:
        return provider().portfolio

    @router.post("/api/portfolio/intents")
    def create_intent(
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body(payload)
        tid = _require_tenant(x_tenant_id, body)
        try:
            return pf().create_intent(
                tenant_id=tid,
                segment=str(body.get("segment") or "STUDENT"),
                demand_source=str(body.get("demandSource") or body.get("demand_source") or "MOCK"),
                candidate_count=int(body.get("candidateCount") or body.get("candidate_count") or 24),
                seed=str(body.get("seed") or "portfolio-v1"),
                envelope=body.get("envelope") if isinstance(body.get("envelope"), dict) else None,
            )
        except (KeyError, PermissionError, PortfolioError) as exc:
            _map_portfolio_error(exc)

    @router.get("/api/portfolio/intents")
    def list_intents(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = _tenant(x_tenant_id)
        items = sorted(
            (i for i in pf().intents.values() if i.get("tenantId") == tid),
            key=lambda r: str(r.get("createdAt") or ""),
        )
        return {"items": items, "total": len(items), "liveMachineControl": False}

    @router.get("/api/portfolio/intents/{portfolio_id}")
    def get_intent(portfolio_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = _tenant(x_tenant_id)
        try:
            return pf().get_intent(portfolio_id, tenant_id=tid)
        except (KeyError, PermissionError, PortfolioError) as exc:
            _map_portfolio_error(exc)

    @router.post("/api/portfolio/intents/{portfolio_id}/candidates")
    def generate_candidates(portfolio_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = _tenant(x_tenant_id)
        try:
            return pf().generate_candidates(portfolio_id, tenant_id=tid)
        except (KeyError, PermissionError, PortfolioError) as exc:
            _map_portfolio_error(exc)

    @router.get("/api/portfolio/intents/{portfolio_id}/candidates")
    def list_candidates(portfolio_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = _tenant(x_tenant_id)
        try:
            items = pf().list_candidates(portfolio_id, tenant_id=tid)
            return {"portfolioId": portfolio_id, "items": items, "total": len(items)}
        except (KeyError, PermissionError, PortfolioError) as exc:
            _map_portfolio_error(exc)

    @router.post("/api/portfolio/intents/{portfolio_id}/material-plan")
    def material_plan(
        portfolio_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body(payload)
        tid = _require_tenant(x_tenant_id, body)
        raw_ids = body.get("candidateIds") or body.get("candidate_ids")
        candidate_ids = None
        if raw_ids is not None:
            if not isinstance(raw_ids, list) or not all(isinstance(x, str) for x in raw_ids):
                raise HTTPException(422, "candidateIds 須為字串陣列")
            candidate_ids = raw_ids
        try:
            plan = pf().plan_material(portfolio_id, tenant_id=tid, candidate_ids=candidate_ids)
            used = list((plan.get("remnantFirst") or {}).get("usedRemnantIds") or [])
            pf().assert_no_double_remnant(used)
            return plan
        except (KeyError, PermissionError, PortfolioError) as exc:
            _map_portfolio_error(exc)

    @router.post("/api/portfolio/intents/{portfolio_id}/rankings")
    def create_ranking(
        portfolio_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body(payload)
        tid = _require_tenant(x_tenant_id, body)
        policy = body.get("policy") if isinstance(body.get("policy"), dict) else None
        try:
            ranking = pf().rank(portfolio_id, tenant_id=tid, policy=policy, demand_real=False)
            return _ranking_view(pf(), ranking)
        except (KeyError, PermissionError, PortfolioError) as exc:
            _map_portfolio_error(exc)

    @router.post("/api/portfolio/rankings/{ranking_id}/override")
    def override_ranking(
        ranking_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body(payload)
        tid = _require_tenant(x_tenant_id, body)
        actor, reason = _actor_reason(body, require_reason=True)
        candidate_id = body.get("candidateId")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise HTTPException(422, "candidateId 必填")
        try:
            ranking = pf().override_rank(
                ranking_id,
                tenant_id=tid,
                actor=actor,
                reason=reason,
                candidate_id=candidate_id.strip(),
            )
            return _ranking_view(pf(), ranking)
        except (KeyError, PermissionError, PortfolioError) as exc:
            _map_portfolio_error(exc)

    @router.post("/api/portfolio/candidates/{candidate_id}/submit-approval")
    def submit_candidate_approval(
        candidate_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body(payload)
        tid = _require_tenant(x_tenant_id, body)
        actor = str(body.get("actor") or "pm")
        try:
            return pf().submit_approval(candidate_id, tenant_id=tid, actor=actor)
        except (KeyError, PermissionError, PortfolioError) as exc:
            _map_portfolio_error(exc)

    @router.post("/api/portfolio/approvals/{approval_id}/approve")
    def approve_candidate(
        approval_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _require_body(payload)
        tid = _require_tenant(x_tenant_id, body)
        try:
            require_confirm(body, action="portfolio_prototype_approve")
        except PermissionError as exc:
            raise HTTPException(403, "需要確認") from exc
        actor, reason = _actor_reason(body, require_reason=True)
        factory = pf()
        with _approve_lock(factory):
            try:
                approval = factory.approvals[approval_id]
                factory._require_tenant(approval, tid)
            except (KeyError, PermissionError) as exc:
                _map_portfolio_error(exc)
            if approval.get("status") == "APPROVED_FOR_PROTOTYPE" and approval.get("approvedAt"):
                return dict(approval)
            try:
                return factory.approve_prototype(approval_id, tenant_id=tid, actor=actor, reason=reason)
            except (KeyError, PermissionError, PortfolioError) as exc:
                _map_portfolio_error(exc)

    @router.post("/api/portfolio/candidates/{candidate_id}/supersede")
    def supersede_candidate(candidate_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = _tenant(x_tenant_id)
        try:
            return pf().supersede(candidate_id, tenant_id=tid)
        except (KeyError, PermissionError, PortfolioError) as exc:
            _map_portfolio_error(exc)

    @router.get("/api/portfolio/candidates/{candidate_id}/prototype-pack")
    def get_prototype_pack(candidate_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = _tenant(x_tenant_id)
        try:
            pf().detect_stale_cost(candidate_id, tenant_id=tid)
            return pf().prototype_pack(candidate_id, tenant_id=tid)
        except (KeyError, PermissionError, PortfolioError) as exc:
            _map_portfolio_error(exc)

    @router.get("/api/portfolio/candidates/{candidate_id}/media-pack")
    def get_media_pack(candidate_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = _tenant(x_tenant_id)
        try:
            return pf().media_pack(candidate_id, tenant_id=tid, render=False)
        except (KeyError, PermissionError, PortfolioError) as exc:
            _map_portfolio_error(exc)

    return router