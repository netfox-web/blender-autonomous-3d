"""Tenant-scoped prototype validation board and floor operations API."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

from fastapi import APIRouter, Body, Header, HTTPException, Query

from fox3d.ids import stable_hash
from fox3d.infra import validate_tenant_id
from fox3d.prototype import PrototypeError
from fox3d.storelock import FileLock

_MAX_KEY_LEN = 200


def _tenant_header(x_tenant_id: str | None) -> str:
    try:
        return validate_tenant_id(x_tenant_id or "")
    except ValueError as exc:
        raise HTTPException(400, "X-Tenant-Id 無效") from exc


def _body(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(422, "請求內容須為 JSON 物件")
    return payload


def _idempotency_key(payload: dict[str, Any]) -> str:
    raw = payload.get("idempotencyKey")
    if not isinstance(raw, str):
        raise HTTPException(422, "idempotencyKey 必填且須為字串")
    key = raw.strip()
    if not key or len(raw) > _MAX_KEY_LEN:
        raise HTTPException(422, "idempotencyKey 須為 1 至 200 字的非空字串")
    return key


def _verify_shift(provider: Callable[[], Any], *, tenant_id: str, operator_id: str, shift_id: str) -> None:
    ident = provider().pilot.identity
    try:
        ident.get_operator(operator_id, tenant_id=tenant_id)
    except KeyError as exc:
        raise HTTPException(403, "找不到作業員") from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    try:
        ident.get_shift(shift_id, tenant_id=tenant_id)
    except KeyError as exc:
        raise HTTPException(403, "找不到班別") from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


def _operator_shift(payload: dict[str, Any]) -> tuple[str, str]:
    op = payload.get("operatorId")
    sh = payload.get("shiftId")
    if not isinstance(op, str) or not op.strip():
        raise HTTPException(422, "operatorId 必填")
    if not isinstance(sh, str) or not sh.strip():
        raise HTTPException(422, "shiftId 必填")
    return op.strip(), sh.strip()


def _map_prototype_error(exc: BaseException) -> NoReturn:
    if isinstance(exc, KeyError):
        raise HTTPException(404, "找不到資源") from exc
    if isinstance(exc, PrototypeError):
        status = 409 if exc.code == "HOLD" else 403
        detail = str(exc) or exc.code
        raise HTTPException(status, detail) from exc
    if isinstance(exc, PermissionError):
        msg = str(exc)
        if msg.startswith("tenant isolation"):
            raise HTTPException(404, "找不到資源") from exc
        raise HTTPException(403, msg) from exc
    raise exc


def _json_bool(payload: dict[str, Any], key: str, *, default: bool = False) -> bool:
    if key not in payload:
        return default
    val = payload[key]
    if isinstance(val, bool):
        return val
    raise HTTPException(422, f"{key} 須為布林值")


def _api_idem_lock_path(factory: Any) -> Path:
    return factory.root / "api-idem.lock"


def _idem_run(
    factory: Any,
    *,
    tenant_id: str,
    scope: str,
    idem_key: str,
    sig: str,
    action: Callable[[], dict[str, Any]],
    durable_intent: bool = False,
) -> dict[str, Any]:
    store_key = f"{tenant_id}::api-idem::{scope}::{idem_key}"
    with FileLock(_api_idem_lock_path(factory)):
        factory.load()
        prev = factory.api_idem.get(store_key)
        if prev is not None:
            if prev.get("sig") != sig:
                raise HTTPException(409, "idempotencyKey 衝突")
            result = prev.get("result")
            if isinstance(result, dict):
                return dict(result)
        if durable_intent:
            # Inventory is stored separately. Persist the signature before any stock
            # mutation, and let the operation persist its recovery checkpoints.
            if prev is None:
                factory.api_idem[store_key] = {"sig": sig}
                factory.persist()
            try:
                try:
                    result = action()
                except (PrototypeError, PermissionError, KeyError) as exc:
                    _map_prototype_error(exc)
                if not isinstance(result, dict):
                    raise HTTPException(500, "內部回應格式錯誤")
                durable_result = dict(result)
                factory.api_idem[store_key] = {"sig": sig, "result": durable_result}
                factory.persist()
                return durable_result
            except Exception:
                factory.load()
                raise
        created: dict[str, Any] | None = None
        factory.begin_persist_hold()
        try:
            try:
                result = action()
            except (PrototypeError, PermissionError, KeyError) as exc:
                _map_prototype_error(exc)
            if not isinstance(result, dict):
                raise HTTPException(500, "內部回應格式錯誤")
            created = dict(result)
            factory.api_idem[store_key] = {"sig": sig, "result": created}
            try:
                factory.end_persist_hold_and_flush()
            except Exception:
                factory.api_idem.pop(store_key, None)
                if created:
                    _rollback_api_idem_action(factory, created)
                factory.abort_persist_hold()
                factory.load()
                raise
        except HTTPException:
            factory.api_idem.pop(store_key, None)
            if created:
                _rollback_api_idem_action(factory, created)
            factory.abort_persist_hold()
            factory.load()
            raise
        except Exception:
            factory.api_idem.pop(store_key, None)
            if created:
                _rollback_api_idem_action(factory, created)
            factory.abort_persist_hold()
            factory.load()
            raise
        return created


def _rollback_api_idem_action(factory: Any, result: dict[str, Any]) -> None:
    labor_id = result.get("laborId")
    if isinstance(labor_id, str):
        factory.labor.pop(labor_id, None)
    unit_id = result.get("prototypeUnitId")
    if isinstance(unit_id, str):
        unit = factory.units.get(unit_id)
        if isinstance(unit, dict) and unit.get("latestLaborId") == labor_id:
            unit.pop("latestLaborId", None)


def _idem_sig(payload: dict[str, Any]) -> str:
    return stable_hash(payload)


def _unit_or_404(factory: Any, unit_id: str, tid: str) -> dict[str, Any]:
    rec = factory.units.get(unit_id)
    if rec is None or rec.get("tenantId") != tid:
        raise HTTPException(404, "找不到資源")
    return rec


def _candidate_or_404(factory: Any, candidate_id: str, tid: str) -> dict[str, Any]:
    try:
        return factory._candidate(candidate_id, tid)
    except KeyError as exc:
        raise HTTPException(404, "找不到資源") from exc
    except PermissionError as exc:
        raise HTTPException(404, "找不到資源") from exc


def _launch_readonly(factory: Any, candidate_id: str, tid: str) -> dict[str, Any] | None:
    rows = [
        r
        for r in factory.launch_decisions.values()
        if r.get("candidateId") == candidate_id and r.get("tenantId") == tid
    ]
    if not rows:
        return None
    return sorted(rows, key=lambda r: str(r.get("at") or r.get("launchDecisionId") or ""))[-1]


def _pilot_batch_readonly(factory: Any, candidate_id: str, tid: str) -> dict[str, Any] | None:
    rows = [
        r
        for r in factory.decisions.values()
        if r.get("candidateId") == candidate_id
        and r.get("tenantId") == tid
        and r.get("decision") == "READY_FOR_MANUAL_PILOT_BATCH"
    ]
    if not rows:
        return None
    return sorted(rows, key=lambda r: str(r.get("at") or r.get("decisionId") or ""))[-1]


def _public_evidence_source(row: dict[str, Any]) -> str | None:
    for key in ("evidenceSource", "source", "truthLabel"):
        val = row.get(key)
        if isinstance(val, str) and val.strip():
            src = val.strip().upper()
            if src == "REAL":
                return "REAL_LOGIC"
            if src in {"FIXTURE", "MANUAL_EVIDENCE", "IMPORTED_EVIDENCE", "MANUAL", "IMPORTED", "REAL_LOGIC"}:
                if src == "MANUAL":
                    return "MANUAL_EVIDENCE"
                if src == "IMPORTED":
                    return "IMPORTED_EVIDENCE"
                return src
    return None


def _unit_detail(factory: Any, unit: dict[str, Any]) -> dict[str, Any]:
    tid = str(unit.get("tenantId") or "")
    cid = str(unit.get("candidateId") or "")
    meas = factory.measurements.get(unit.get("latestMeasurementId") or "")
    cost = factory.costs.get(unit.get("actualCostId") or "")
    pack = factory.checklists.get(unit.get("packagingChecklistId") or "")
    pkg = factory.packages.get(unit.get("evidencePackageId") or "")
    readiness = factory.readiness(cid, tenant_id=tid)
    return {
        **unit,
        "matrixRow": factory.matrix_row(unit),
        "readiness": readiness,
        "measurement": meas,
        "actualCost": cost,
        "packagingChecklist": pack,
        "evidencePackage": pkg,
        "launchDecisionRecord": _launch_readonly(factory, cid, tid),
        "pilotBatchApprovalRecord": _pilot_batch_readonly(factory, cid, tid),
        "evidenceSourceLabel": _public_evidence_source(meas or unit),
        "liveMachineControl": False,
        "productionReady": False,
    }


def prototype_router(provider: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/api/prototypes")

    def factory() -> Any:
        return provider().prototype

    @router.get("/board")
    def decision_board(
        portfolioId: str = Query(..., min_length=1),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = _tenant_header(x_tenant_id)
        plat = provider()
        try:
            plat.portfolio.get_intent(portfolioId, tenant_id=tid)
        except KeyError as exc:
            raise HTTPException(404, "找不到資源") from exc
        except PermissionError as exc:
            raise HTTPException(404, "找不到資源") from exc
        try:
            board = factory().decision_board(portfolioId, tenant_id=tid)
        except (PrototypeError, PermissionError, KeyError) as exc:
            _map_prototype_error(exc)
        for row in board.get("rows") or []:
            row["evidenceSourceLabel"] = _public_evidence_source(row)
        return board

    @router.get("/candidates/{candidate_id}/readiness")
    def candidate_readiness(candidate_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = _tenant_header(x_tenant_id)
        _candidate_or_404(factory(), candidate_id, tid)
        try:
            body = factory().readiness(candidate_id, tenant_id=tid)
        except (PrototypeError, PermissionError, KeyError) as exc:
            _map_prototype_error(exc)
        body["evidenceSourceLabel"] = _public_evidence_source(body)
        body["launchDecisionRecord"] = _launch_readonly(factory(), candidate_id, tid)
        body["pilotBatchApprovalRecord"] = _pilot_batch_readonly(factory(), candidate_id, tid)
        return body

    @router.get("/units")
    def list_units(
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=100),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        tid = _tenant_header(x_tenant_id)
        rows = sorted(
            (u for u in factory().units.values() if u.get("tenantId") == tid),
            key=lambda u: str(u.get("createdAt") or u.get("prototypeUnitId") or ""),
        )
        page = rows[offset : offset + limit]
        items = []
        for unit in page:
            item = {**unit, "matrixRow": factory().matrix_row(unit)}
            item["evidenceSourceLabel"] = _public_evidence_source(unit)
            items.append(item)
        return {"items": items, "total": len(rows), "offset": offset, "limit": limit, "liveMachineControl": False}

    @router.get("/units/{unit_id}")
    def get_unit(unit_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        tid = _tenant_header(x_tenant_id)
        unit = _unit_or_404(factory(), unit_id, tid)
        return _unit_detail(factory(), unit)

    @router.post("/units")
    def create_unit(payload: Any = Body(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = _body(payload)
        tid = _tenant_header(x_tenant_id)
        selection_id = body.get("selectionId")
        if not isinstance(selection_id, str) or not selection_id.strip():
            raise HTTPException(422, "selectionId 必填")
        op, shift = _operator_shift(body)
        _verify_shift(provider, tenant_id=tid, operator_id=op, shift_id=shift)
        idem = _idempotency_key(body)
        seq = body.get("seq", 1)
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            raise HTTPException(422, "seq 須為正整數")
        pf = factory()
        sel = pf.selections.get(selection_id.strip())
        if sel is None or sel.get("tenantId") != tid:
            raise HTTPException(404, "找不到資源")

        def _action() -> dict[str, Any]:
            return pf.create_unit(
                tenant_id=tid,
                selection_id=selection_id.strip(),
                operator_id=op,
                shift_id=shift,
                seq=int(seq),
            )

        return _idem_run(pf, tenant_id=tid, scope="create-unit", idem_key=idem, sig=_idem_sig(body), action=_action)

    @router.post("/units/{unit_id}/start")
    def start_unit(unit_id: str, payload: Any = Body(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = _body(payload)
        tid = _tenant_header(x_tenant_id)
        _unit_or_404(factory(), unit_id, tid)
        op, shift = _operator_shift(body)
        _verify_shift(provider, tenant_id=tid, operator_id=op, shift_id=shift)
        idem = _idempotency_key(body)
        pf = factory()

        def _action() -> dict[str, Any]:
            return pf.start_unit(unit_id, tenant_id=tid, operator_id=op, shift_id=shift)

        return _idem_run(pf, tenant_id=tid, scope=f"start::{unit_id}", idem_key=idem, sig=_idem_sig(body), action=_action)

    @router.post("/units/{unit_id}/complete")
    def complete_unit(unit_id: str, payload: Any = Body(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = _body(payload)
        tid = _tenant_header(x_tenant_id)
        _unit_or_404(factory(), unit_id, tid)
        op, shift = _operator_shift(body)
        _verify_shift(provider, tenant_id=tid, operator_id=op, shift_id=shift)
        idem = _idempotency_key(body)
        pf = factory()

        def _action() -> dict[str, Any]:
            return pf.complete_build(unit_id, tenant_id=tid, operator_id=op, shift_id=shift)

        return _idem_run(pf, tenant_id=tid, scope=f"complete::{unit_id}", idem_key=idem, sig=_idem_sig(body), action=_action)

    @router.post("/units/{unit_id}/material")
    def consume_material(unit_id: str, payload: Any = Body(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = _body(payload)
        tid = _tenant_header(x_tenant_id)
        _unit_or_404(factory(), unit_id, tid)
        op, shift = _operator_shift(body)
        _verify_shift(provider, tenant_id=tid, operator_id=op, shift_id=shift)
        idem = _idempotency_key(body)
        pf = factory()
        consumes = _json_bool(body, "consumesInventory", default=False)
        sheets = body.get("sheets")
        if sheets is not None and (isinstance(sheets, bool) or not isinstance(sheets, int) or sheets < 1):
            raise HTTPException(422, "sheets 須為正整數")

        def _action() -> dict[str, Any]:
            rec = pf.consume_material_once(
                unit_id,
                tenant_id=tid,
                operator_id=op,
                shift_id=shift,
                sheets=int(sheets) if sheets is not None else None,
                consumes_inventory=consumes,
                lot_id=body.get("lotId") if isinstance(body.get("lotId"), str) else None,
                material=body.get("material") if isinstance(body.get("material"), str) else None,
                thickness=body.get("thickness") if isinstance(body.get("thickness"), (int, float)) else None,
                grain=body.get("grain") if isinstance(body.get("grain"), str) else None,
            )
            return rec

        return _idem_run(pf, tenant_id=tid, scope=f"material::{unit_id}", idem_key=idem, sig=_idem_sig(body), action=_action, durable_intent=consumes)

    @router.post("/units/{unit_id}/as-built")
    def record_as_built(unit_id: str, payload: Any = Body(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = _body(payload)
        tid = _tenant_header(x_tenant_id)
        _unit_or_404(factory(), unit_id, tid)
        op, shift = _operator_shift(body)
        _verify_shift(provider, tenant_id=tid, operator_id=op, shift_id=shift)
        idem = _idempotency_key(body)
        source = body.get("source", "FIXTURE")
        if not isinstance(source, str) or not source.strip():
            raise HTTPException(422, "source 必填")
        values = body.get("values")
        if not isinstance(values, dict):
            raise HTTPException(422, "values 須為物件")
        pf = factory()

        def _action() -> dict[str, Any]:
            result = pf.record_as_built(
                unit_id,
                tenant_id=tid,
                operator_id=op,
                shift_id=shift,
                source=source.strip(),
                values=values,
                dam_refs=body.get("damRefs") if isinstance(body.get("damRefs"), list) else None,
                notes=body.get("notes") if isinstance(body.get("notes"), dict) else None,
                observations=body.get("observations") if isinstance(body.get("observations"), dict) else None,
            )
            result["evidenceSourceLabel"] = _public_evidence_source(result)
            return result

        return _idem_run(pf, tenant_id=tid, scope=f"as-built::{unit_id}", idem_key=idem, sig=_idem_sig(body), action=_action)

    @router.post("/units/{unit_id}/labor")
    def record_labor(unit_id: str, payload: Any = Body(default=None), x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
        body = _body(payload)
        tid = _tenant_header(x_tenant_id)
        _unit_or_404(factory(), unit_id, tid)
        op, shift = _operator_shift(body)
        _verify_shift(provider, tenant_id=tid, operator_id=op, shift_id=shift)
        idem = _idempotency_key(body)
        raw_minutes = body.get("minutes")
        if isinstance(raw_minutes, bool) or not isinstance(raw_minutes, (int, float)):
            raise HTTPException(422, "minutes 須為數字")
        reason = body.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise HTTPException(422, "reason 必填")
        source = str(body.get("source") or "MANUAL")
        pf = factory()

        def _action() -> dict[str, Any]:
            result = pf.record_labor(
                unit_id,
                tenant_id=tid,
                operator_id=op,
                shift_id=shift,
                minutes=float(raw_minutes),
                reason=reason.strip(),
                source=source,
                idempotency_key=idem,
            )
            result["evidenceSourceLabel"] = _public_evidence_source(result)
            return result

        return _idem_run(pf, tenant_id=tid, scope=f"labor::{unit_id}", idem_key=idem, sig=_idem_sig(body), action=_action)

    @router.post("/units/{unit_id}/evidence-packages")
    def create_evidence_package(
        unit_id: str, payload: Any = Body(default=None), x_tenant_id: str | None = Header(default=None)
    ) -> dict[str, Any]:
        body = _body(payload)
        tid = _tenant_header(x_tenant_id)
        _unit_or_404(factory(), unit_id, tid)
        op, shift = _operator_shift(body)
        _verify_shift(provider, tenant_id=tid, operator_id=op, shift_id=shift)
        idem = _idempotency_key(body)
        source = body.get("source", "FIXTURE")
        if not isinstance(source, str) or not source.strip():
            raise HTTPException(422, "source 必填")
        reason = str(body.get("reason") or "physical-evidence")
        pf = factory()

        def _action() -> dict[str, Any]:
            result = pf.create_evidence_package(
                unit_id,
                tenant_id=tid,
                operator_id=op,
                shift_id=shift,
                source=source.strip(),
                reason=reason,
            )
            result["evidenceSourceLabel"] = _public_evidence_source(result)
            return result

        return _idem_run(
            pf, tenant_id=tid, scope=f"evidence-create::{unit_id}", idem_key=idem, sig=_idem_sig(body), action=_action
        )

    @router.post("/units/{unit_id}/evidence-packages/{package_id}/finalize")
    def finalize_evidence_package(
        unit_id: str,
        package_id: str,
        payload: Any = Body(default=None),
        x_tenant_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = _body(payload)
        tid = _tenant_header(x_tenant_id)
        _unit_or_404(factory(), unit_id, tid)
        pkg = factory().packages.get(package_id)
        if pkg is None or pkg.get("tenantId") != tid or pkg.get("prototypeUnitId") != unit_id:
            raise HTTPException(404, "找不到資源")
        op, shift = _operator_shift(body)
        _verify_shift(provider, tenant_id=tid, operator_id=op, shift_id=shift)
        idem = _idempotency_key(body)
        pf = factory()

        def _action() -> dict[str, Any]:
            result = pf.finalize_evidence_package(
                package_id,
                tenant_id=tid,
                operator_id=op,
                shift_id=shift,
            )
            result["evidenceSourceLabel"] = _public_evidence_source(result)
            return result

        return _idem_run(
            pf,
            tenant_id=tid,
            scope=f"evidence-finalize::{unit_id}::{package_id}",
            idem_key=idem,
            sig=_idem_sig(body),
            action=_action,
        )

    return router