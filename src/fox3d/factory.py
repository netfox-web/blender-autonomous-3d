"""Autonomous furniture factory orchestration.

Space → layout → furniture variants → BOM → nesting → cost → preview → WAITING_APPROVAL.
Does not rewrite Scheduler / Queue / DAM / Recipe Registry / TwinStore.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from fox3d.furniture import (
    FurnitureProductTypeRegistry,
    assembly_from_placements,
    customer_revision,
    validate_assembly,
)
from fox3d.ids import new_id, stable_hash
from fox3d.manufacturing import (
    ManufacturingCandidateGate,
    NestingEngine,
    QuoteEngine,
    build_manufacturing_pack,
)
from fox3d.infra import utcnow
from fox3d.inventory import atomic_write_json
from fox3d.parametric import BOMEngine, CabinetSpec
from fox3d.space import SpaceConstraintEngine, SpaceDigitalTwin, WallFitSolver
from fox3d.storelock import FileLock

logger = logging.getLogger(__name__)


class FurnitureFactory:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.types = FurnitureProductTypeRegistry()
        self.solver = WallFitSolver()
        self.constraints = SpaceConstraintEngine()
        self.spaces: dict[str, SpaceDigitalTwin] = {}
        self.assemblies: dict[str, dict[str, Any]] = {}
        self.quotes: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.revisions: list[dict[str, Any]] = []
        self._quote_run_index: dict[str, str] = {}
        self._lock = threading.RLock()
        self.load()

    def _storage_root(self) -> Path | None:
        root = getattr(self.platform, "root", None)
        return Path(root) if root else None

    def _state_path(self) -> Path | None:
        root = self._storage_root()
        return (root / "factory" / "state.json") if root else None

    def _rebuild_quote_index(self) -> None:
        index: dict[str, str] = {}
        for run_id, run in self.runs.items():
            qid = (run.get("quote") or {}).get("quoteId")
            if qid:
                index[str(qid)] = str(run_id)
        self._quote_run_index = index

    def _read_state_file(self, path: Path) -> dict[str, Any]:
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("factory state root must be an object")
            return payload
        except (json.JSONDecodeError, ValueError, TypeError, OSError):
            return {}

    def _snapshot_payload(self) -> dict[str, Any]:
        return {
            "spaces": {sid: twin.model_dump(mode="json") for sid, twin in self.spaces.items()},
            "assemblies": dict(self.assemblies),
            "quotes": dict(self.quotes),
            "runs": dict(self.runs),
            "revisions": list(self.revisions),
            "quoteRunIndex": dict(self._quote_run_index),
            "parametrics": {
                str(k): v for k, v in getattr(self.platform, "parametrics", {}).items() if isinstance(v, dict)
            },
        }

    _GATE_RANK: dict[str, int] = {
        "APPROVED": 4,
        "WAITING_APPROVAL": 3,
        "PREVIEWED": 2,
        "COSTED": 1,
    }

    @staticmethod
    def _merge_record_maps(
        disk: dict[str, Any],
        local: dict[str, Any],
        *,
        pick: Any,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for key in set(disk) | set(local):
            disk_rec = disk.get(key)
            local_rec = local.get(key)
            if isinstance(disk_rec, dict) and isinstance(local_rec, dict):
                merged[key] = pick(disk_rec, local_rec)
            elif isinstance(local_rec, dict):
                merged[key] = local_rec
            elif isinstance(disk_rec, dict):
                merged[key] = disk_rec
        return merged

    @classmethod
    def _pick_winning_run(cls, disk_rec: dict[str, Any], local_rec: dict[str, Any]) -> dict[str, Any]:
        d_gate = disk_rec.get("gate") or {}
        l_gate = local_rec.get("gate") or {}
        d_rank = cls._GATE_RANK.get(str(d_gate.get("status") or ""), 0)
        l_rank = cls._GATE_RANK.get(str(l_gate.get("status") or ""), 0)
        if d_rank != l_rank:
            return disk_rec if d_rank > l_rank else local_rec
        d_stamp = str(d_gate.get("approvedAt") or disk_rec.get("createdAt") or "")
        l_stamp = str(l_gate.get("approvedAt") or local_rec.get("createdAt") or "")
        if d_stamp != l_stamp:
            return disk_rec if d_stamp > l_stamp else local_rec
        return disk_rec

    @staticmethod
    def _pick_disk_on_conflict(disk_rec: dict[str, Any], local_rec: dict[str, Any]) -> dict[str, Any]:
        return disk_rec

    @classmethod
    def _rebuild_quote_run_index(cls, runs: dict[str, Any]) -> dict[str, str]:
        index: dict[str, str] = {}
        for run_id, run in runs.items():
            if not isinstance(run, dict):
                continue
            qid = (run.get("quote") or {}).get("quoteId")
            if qid:
                index[str(qid)] = str(run_id)
        return index

    @classmethod
    def _merge_state_payload(cls, disk: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        raw_d_runs = disk.get("runs")
        raw_loc_runs = local.get("runs")
        d_runs: dict[str, Any] = raw_d_runs if isinstance(raw_d_runs, dict) else {}
        loc_runs: dict[str, Any] = raw_loc_runs if isinstance(raw_loc_runs, dict) else {}
        merged_runs = cls._merge_record_maps(d_runs, loc_runs, pick=cls._pick_winning_run)
        merged["runs"] = merged_runs

        for key in ("assemblies", "quotes", "spaces", "parametrics"):
            raw_d = disk.get(key)
            raw_loc = local.get(key)
            d: dict[str, Any] = raw_d if isinstance(raw_d, dict) else {}
            loc: dict[str, Any] = raw_loc if isinstance(raw_loc, dict) else {}
            merged[key] = cls._merge_record_maps(d, loc, pick=cls._pick_disk_on_conflict)

        merged["quoteRunIndex"] = cls._rebuild_quote_run_index(merged_runs)

        disk_rev = [r for r in (disk.get("revisions") or []) if isinstance(r, dict)]
        loc_rev = [r for r in (local.get("revisions") or []) if isinstance(r, dict)]
        seen: set[str] = set()
        revisions: list[dict[str, Any]] = []
        for rec in disk_rev + loc_rev:
            token = stable_hash(rec)
            if token in seen:
                continue
            seen.add(token)
            revisions.append(rec)
        merged["revisions"] = revisions
        return merged

    def _apply_payload(self, payload: dict[str, Any]) -> None:
        self.assemblies = {str(k): v for k, v in (payload.get("assemblies") or {}).items() if isinstance(v, dict)}
        self.quotes = {str(k): v for k, v in (payload.get("quotes") or {}).items() if isinstance(v, dict)}
        self.runs = {str(k): v for k, v in (payload.get("runs") or {}).items() if isinstance(v, dict)}
        self.revisions = [r for r in (payload.get("revisions") or []) if isinstance(r, dict)]
        self.spaces = {}
        for sid, item in (payload.get("spaces") or {}).items():
            if not isinstance(item, dict):
                continue
            try:
                self.spaces[str(sid)] = SpaceDigitalTwin.model_validate(item)
            except Exception:
                logger.warning("skipped invalid space record %s", sid)
        index = payload.get("quoteRunIndex")
        if isinstance(index, dict):
            self._quote_run_index = {str(k): str(v) for k, v in index.items()}
        else:
            self._rebuild_quote_index()
        parametrics = payload.get("parametrics") or {}
        if isinstance(parametrics, dict):
            target = getattr(self.platform, "parametrics", None)
            if isinstance(target, dict):
                for pid, rec in parametrics.items():
                    if isinstance(rec, dict):
                        target[str(pid)] = rec

    def _sync_from_disk(self) -> None:
        path = self._state_path()
        if not path or not path.exists():
            return
        lock = path.parent / "state.lock"
        with FileLock(lock):
            disk = self._read_state_file(path)
            if not disk:
                return
            with self._lock:
                local = self._snapshot_payload()
                merged = self._merge_state_payload(disk, local)
                self._apply_payload(merged)

    def load(self) -> None:
        path = self._state_path()
        if not path:
            return
        if not path.exists():
            self._rebuild_quote_index()
            return
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("factory state root must be an object")
        except (json.JSONDecodeError, ValueError, TypeError, OSError) as exc:
            backup = path.with_name(f"{path.name}.corrupt.{utcnow().strftime('%Y%m%dT%H%M%S')}.bak")
            try:
                path.replace(backup)
            except OSError:
                logger.warning("factory state corrupt; could not quarantine %s: %s", path, exc)
            else:
                logger.warning("factory state corrupt; quarantined to %s: %s", backup, exc)
            self._rebuild_quote_index()
            return

        with self._lock:
            self._apply_payload(payload)

    def persist(self) -> None:
        path = self._state_path()
        if not path:
            return
        lock = path.parent / "state.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(lock):
            with self._lock:
                local = self._snapshot_payload()
            disk = self._read_state_file(path) if path.exists() else {}
            merged = self._merge_state_payload(disk, local)
            atomic_write_json(path, merged)
            with self._lock:
                self._apply_payload(merged)

    def run_id_for_quote(self, quote_id: str, tenant_id: str) -> str:
        self._sync_from_disk()
        run_id = self._quote_run_index.get(quote_id)
        if not run_id:
            raise KeyError(quote_id)
        run = self.runs.get(run_id)
        if not run or run.get("tenantId") != tenant_id:
            raise KeyError(quote_id)
        return run_id

    def list_quote_summaries(self, tenant_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        self._sync_from_disk()
        lim = max(1, min(int(limit), 100))
        rows: list[tuple[str, dict[str, Any]]] = []
        for run in self.runs.values():
            if run.get("tenantId") != tenant_id:
                continue
            q = run.get("quote") or {}
            qid = q.get("quoteId")
            if not qid:
                continue
            stored_q = self.quotes.get(str(qid)) or q
            base_q = dict(stored_q)
            gate = run.get("gate") or {}
            space_info = run.get("space") or {}
            asm = run.get("assembly") or {}
            rows.append(
                (
                    str(run.get("createdAt") or ""),
                    {
                        **base_q,
                        "runId": run.get("runId"),
                        "createdAt": run.get("createdAt"),
                        "gateStatus": gate.get("status") or "WAITING_APPROVAL",
                        "approvedActor": gate.get("actor"),
                        "approvedAt": gate.get("approvedAt"),
                        "liveMachineControl": bool(gate.get("liveMachineControl", False)),
                        "wallName": space_info.get("wallName") or "N",
                        "spaceWidth": space_info.get("width"),
                        "spaceDepth": space_info.get("depth"),
                        "spaceHeight": space_info.get("height"),
                        "cabinetCount": asm.get("cabinetCount") or len(asm.get("cabinets") or []),
                        "previewLabel": run.get("previewLabel") or "SKIPPED",
                    },
                )
            )
        rows.sort(key=lambda pair: (pair[0], str((pair[1].get("quoteId") or ""))), reverse=True)
        return [item for _, item in rows[:lim]]

    def create_space(self, payload: dict[str, Any]) -> SpaceDigitalTwin:
        twin = self.platform.spaces.ingest(payload)
        self.spaces[twin.spaceId] = twin
        self.persist()
        return twin

    def default_room_3600(self, *, tenant_id: str) -> dict[str, Any]:
        return {
            "tenantId": tenant_id,
            "width": 3600,
            "depth": 3000,
            "height": 2600,
            "doors": [{"kind": "door", "width": 900, "height": 2100, "wallId": None, "startMm": 200, "position": [200.0, 0.0]}],
            "windows": [{"kind": "window", "width": 1200, "height": 1200, "sill": 900, "startMm": 400, "position": [400.0, 0.0]}],
            "columns": [{"width": 200, "depth": 200, "startMm": 0, "wallId": None}],
        }

    def solve_wall(self, space: SpaceDigitalTwin, wall_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        cands = self.solver.solve(space, wall_id, **kwargs)
        return [c.model_dump(mode="json") for c in cands]

    def run(
        self,
        *,
        tenant_id: str,
        space: dict[str, Any] | None = None,
        wall_name: str = "N",
        product_types: list[str] | None = None,
        text: str | None = None,
        render: bool = False,
        gap: float = 20,
        min_clearance: float = 10,
        symmetric: bool = True,
    ) -> dict[str, Any]:
        from fox3d.parametric import parse_design_intent

        self._sync_from_disk()
        intent = parse_design_intent(text, tenant_id=tenant_id) if text else None
        types = product_types or (
            [intent["kind"]] if intent and intent.get("kind") in self.types.list() else ["STORAGE_CABINET", "WARDROBE", "BOOKCASE"]
        )
        payload = dict(space or self.default_room_3600(tenant_id=tenant_id))
        payload["tenantId"] = tenant_id
        # Acceptance wall: 3600mm clear N wall; put door/window/column on other walls so N can host multi-cabinet.
        if not space:
            payload["doors"] = [{"kind": "door", "width": 900, "height": 2100, "startMm": 400, "position": [400.0, 0.0]}]
            payload["windows"] = [{"kind": "window", "width": 1000, "height": 1200, "sill": 900, "startMm": 800, "position": [800.0, 0.0]}]
            payload["columns"] = [{"width": 180, "depth": 180, "startMm": 200}]
        space_twin = self.create_space(payload)
        # Assign door/window/column keep-outs to E/S/W so N stays a 3600mm furniture wall.
        if not space:
            by_name = {w.name: w for w in space_twin.walls}
            for zone in space_twin.keepOuts:
                if zone.kind == "door" and "E" in by_name:
                    zone.wallId = by_name["E"].wallId
                elif zone.kind == "window" and "S" in by_name:
                    zone.wallId = by_name["S"].wallId
                elif zone.kind == "column" and "W" in by_name:
                    zone.wallId = by_name["W"].wallId
        wall = next((w for w in space_twin.walls if w.name == wall_name), space_twin.walls[0])
        layouts = self.solver.solve(
            space_twin,
            wall.wallId,
            product_types=types,
            gap=gap,
            min_clearance=min_clearance,
            symmetric=symmetric,
            count=10,
        )
        legal = [c for c in layouts if not c.rejected]
        chosen = legal[0] if legal else (layouts[0] if layouts else None)
        if chosen is None:
            return {"status": "failed", "error": "no layout candidates", "space": space_twin.model_dump(mode="json")}
        assembly = assembly_from_placements(
            tenant_id=tenant_id,
            wall_id=wall.wallId,
            space_id=space_twin.spaceId,
            placements=chosen.placements,
            cabinets=self.platform.cabinets,
            gap_mm=gap,
            clearance_mm=min_clearance,
            symmetric=symmetric,
        )
        assembly_violations = validate_assembly(assembly, space=space_twin)
        space_violations = self.constraints.validate(
            space_twin,
            [
                {
                    "wallId": c.wallId,
                    "startMm": c.startMm,
                    "width": c.spec.get("width"),
                    "height": c.spec.get("height"),
                    "originZ": c.originZ,
                }
                for c in assembly.cabinets
            ],
        )
        bom_engine = BOMEngine()
        merged_lines: list[dict[str, Any]] = []
        cabinet_records: list[dict[str, Any]] = []
        for placed in assembly.cabinets:
            spec = CabinetSpec.model_validate(placed.spec)
            rec = self.platform.parametrics.get(spec.productId)
            if not rec:
                rec = {
                    "spec": spec.model_dump(mode="json"),
                    "bom": bom_engine.build(spec),
                    "engineeringHash": spec.engineering_hash(),
                }
                self.platform.parametrics[spec.productId] = rec
            bom = rec["bom"]
            for line in bom["lines"]:
                item = dict(line)
                item["cabinetId"] = spec.productId
                merged_lines.append(item)
            pack = build_manufacturing_pack(spec, bom)
            cabinet_records.append(
                {
                    "placement": placed.model_dump(mode="json"),
                    "engineeringHash": spec.engineering_hash(),
                    "bomHash": bom.get("bomHash"),
                    "manufacturing": pack["manufacturing"],
                    "quote": pack["quote"],
                    "nestingHash": pack["nesting"]["nestingHash"],
                }
            )
        combined_bom = {
            "assemblyId": assembly.assemblyId,
            "engineeringHash": assembly.engineering_hash(),
            "lines": merged_lines,
            "bomHash": stable_hash(merged_lines),
        }
        nesting = NestingEngine().nest(combined_bom, material="WOOD_WHITE")
        # Quote against the first cabinet dimensions scaled by count — use combined BOM + nesting.
        lead_spec = CabinetSpec.model_validate(assembly.cabinets[0].spec)
        quote = QuoteEngine().quote(lead_spec, combined_bom, nesting)
        quote_dump = quote.model_dump(mode="json")
        self.quotes[quote.quoteId] = quote_dump

        gate = ManufacturingCandidateGate()
        gate.advance("COSTED")
        preview = None
        preview_label: Any = "SKIPPED"
        if render:
            preview = self.render_space_preview(tenant_id=tenant_id, space=space_twin, assembly=assembly)
            if preview.get("status") in {"completed", "succeeded"}:
                gate.advance("PREVIEWED")
                preview_label = "REAL" if preview.get("realBlender") else ("MOCK" if self.platform.mock_blender else "PARTIAL")
            elif preview.get("error") in {"BLOCKED_NO_BLENDER", "BLOCKED_NO_OPTIX"}:
                preview_label = preview.get("error")
            else:
                preview_label = "PARTIAL"
        gate.advance("WAITING_APPROVAL")

        created_at = utcnow().isoformat()
        run: dict[str, Any] = {
            "runId": new_id(),
            "tenantId": tenant_id,
            "createdAt": created_at,
            "pipeline": [
                "space",
                "layout",
                "furniture_variants",
                "engineering_validate",
                "bom",
                "nesting",
                "cost",
                "preview",
                "candidate",
            ],
            "intent": intent,
            "space": {
                "spaceId": space_twin.spaceId,
                "spaceHash": space_twin.space_hash(),
                "width": space_twin.width,
                "depth": space_twin.depth,
                "height": space_twin.height,
                "wallId": wall.wallId,
                "wallName": wall.name,
                "wallLength": wall.length,
            },
            "layouts": [c.model_dump(mode="json") for c in layouts],
            "legalLayoutCount": len(legal),
            "chosenLayout": chosen.model_dump(mode="json"),
            "assembly": {
                "assemblyId": assembly.assemblyId,
                "assemblyHash": assembly.engineering_hash(),
                "cabinetCount": len(assembly.cabinets),
                "cabinets": [c.model_dump(mode="json") for c in assembly.cabinets],
            },
            "assemblyViolations": assembly_violations,
            "spaceViolations": space_violations,
            "bom": combined_bom,
            "nesting": {k: nesting[k] for k in nesting if k != "svg"} | {"svgBytes": len(nesting.get("svg") or "")},
            "quote": quote_dump,
            "cabinets": cabinet_records,
            "gate": {
                "status": gate.state,
                "liveMachineControl": False,
                "HUMAN_APPROVAL_REQUIRED": True,
                "autoLiveCnc": False,
            },
            "preview": preview,
            "previewLabel": preview_label,
            "lineage": {
                "space": {"spaceId": space_twin.spaceId, "spaceHash": space_twin.space_hash()},
                "furniture": {"assemblyId": assembly.assemblyId, "assemblyHash": assembly.engineering_hash()},
            },
            "productTypes": self.types.list(),
        }
        self.assemblies[assembly.assemblyId] = run["assembly"]
        self.runs[run["runId"]] = run
        self._quote_run_index[str(quote.quoteId)] = str(run["runId"])
        self.persist()
        return run

    def render_space_preview(self, *, tenant_id: str, space: SpaceDigitalTwin, assembly: Any) -> dict[str, Any]:
        job = self.platform.submit_job(
            {
                "tenantId": tenant_id,
                "jobType": "SPACE_PREVIEW",
                "mode": "SPACE_PREVIEW",
                "space": space.model_dump(mode="json"),
                "assembly": {
                    "assemblyId": assembly.assemblyId,
                    "assemblyHash": assembly.engineering_hash(),
                    "cabinets": [c.model_dump(mode="json") for c in assembly.cabinets],
                },
                "render": {"width": 512, "height": 512, "engine": "CYCLES", "device": "OPTIX", "samples": 16},
                "timeoutSeconds": 600,
            }
        )
        return self.platform.execute_job(job)

    def revise_cabinet(self, product_id: str, *, tenant_id: str, **changes: Any) -> dict[str, Any]:
        return self.revise_cabinet_changes(product_id, tenant_id, changes)

    def revise_cabinet_changes(self, product_id: str, tenant_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        self._sync_from_disk()
        current = self.platform.parametrics.get(product_id)
        if not current:
            raise KeyError(product_id)
        spec = CabinetSpec.model_validate(current["spec"])
        if spec.tenantId != tenant_id:
            raise PermissionError("tenant isolation: parametric leakage blocked")
        if not changes:
            raise ValueError("at least one revision change is required")
        nxt, report, lineage = customer_revision(self.platform.cabinets, spec, **changes)
        bom = BOMEngine().build(nxt)
        pack = build_manufacturing_pack(nxt, bom)
        record = {
            "spec": nxt.model_dump(mode="json"),
            "report": report.model_dump(),
            "bom": bom,
            "quote": pack["quote"],
            "engineeringHash": nxt.engineering_hash(),
            "resizedFrom": product_id,
            "lineage": lineage,
        }
        self.platform.parametrics[nxt.productId] = record
        self.revisions.append(lineage)
        self.persist()
        return record

    def approve(self, run_id: str, *, actor: str) -> dict[str, Any]:
        self._sync_from_disk()
        run = self.runs.get(run_id)
        if not run:
            raise KeyError(run_id)
        gate = run.get("gate") or {}
        if gate.get("status") == "APPROVED":
            return run
        if gate.get("status") != "WAITING_APPROVAL":
            raise PermissionError("candidate is not waiting approval")
        approved_at = utcnow().isoformat()
        run = dict(run)
        run["gate"] = {
            "status": "APPROVED",
            "actor": actor,
            "approvedAt": approved_at,
            "liveMachineControl": False,
            "HUMAN_APPROVAL_REQUIRED": True,
            "autoLiveCnc": False,
            "note": "Approval is for manufacturing candidate only; LIVE_CNC remains blocked.",
        }
        self.runs[run_id] = run
        self.persist()
        return run

    def collision_fixture(self, *, tenant_id: str) -> dict[str, Any]:
        """Door / window / column rejection evidence (does not mutate factory happy-path)."""
        space = self.platform.spaces.ingest(
            {
                "tenantId": tenant_id,
                "width": 3600,
                "depth": 3000,
                "height": 2600,
                "doors": [{"kind": "door", "width": 900, "height": 2100, "startMm": 1200, "position": [1200.0, 0.0]}],
                "windows": [{"kind": "window", "width": 1000, "height": 1200, "sill": 900, "startMm": 2400, "position": [2400.0, 0.0]}],
                "columns": [{"width": 250, "depth": 250, "startMm": 200}],
            }
        )
        wall = next(w for w in space.walls if w.name == "N")
        door = self.constraints.validate(space, [{"wallId": wall.wallId, "startMm": 1250, "width": 800, "height": 1800, "originZ": 0}])
        window = self.constraints.validate(space, [{"wallId": wall.wallId, "startMm": 2450, "width": 800, "height": 1800, "originZ": 900}])
        column = self.constraints.validate(space, [{"wallId": wall.wallId, "startMm": 150, "width": 400, "height": 1800, "originZ": 0}])
        codes = {v["code"] for v in door + window + column}
        return {
            "spaceId": space.spaceId,
            "wallId": wall.wallId,
            "violations": door + window + column,
            "codes": sorted(codes),
            "doorRejected": any("DOOR" in v["code"] for v in door),
            "windowRejected": any("WINDOW" in v["code"] for v in window),
            "columnRejected": any("COLUMN" in v["code"] for v in column),
        }
