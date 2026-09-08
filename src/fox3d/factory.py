"""Autonomous furniture factory orchestration.

Space → layout → furniture variants → BOM → nesting → cost → preview → WAITING_APPROVAL.
Does not rewrite Scheduler / Queue / DAM / Recipe Registry / TwinStore.
"""

from __future__ import annotations

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
    build_drilling_manifest,
    build_manufacturing_pack,
)
from fox3d.parametric import BOMEngine, CabinetSpec
from fox3d.space import SpaceConstraintEngine, SpaceDigitalTwin, WallFitSolver


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

    def create_space(self, payload: dict[str, Any]) -> SpaceDigitalTwin:
        twin = self.platform.spaces.ingest(payload)
        self.spaces[twin.spaceId] = twin
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

        intent = parse_design_intent(text, tenant_id=tenant_id) if text else None
        types = product_types or (
            [intent["kind"]] if intent and intent.get("kind") in self.types.list() else ["STORAGE_CABINET", "WARDROBE", "BOOKCASE"]
        )
        payload = dict(space or self.default_room_3600(tenant_id=tenant_id))
        payload["tenantId"] = tenant_id
        # Acceptance wall: 3600mm clear N wall; put door/window/column on other walls so N can host multi-cabinet.
        if not space:
            n_len = float(payload["width"])
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
        preview_label = "SKIPPED"
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

        run = {
            "runId": new_id(),
            "tenantId": tenant_id,
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
        current = self.platform.parametrics.get(product_id)
        if not current:
            raise KeyError(product_id)
        spec = CabinetSpec.model_validate(current["spec"])
        if spec.tenantId != tenant_id:
            raise PermissionError("tenant isolation: parametric leakage blocked")
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
        return record

    def approve(self, run_id: str, *, actor: str) -> dict[str, Any]:
        run = self.runs.get(run_id)
        if not run:
            raise KeyError(run_id)
        if run["gate"]["status"] != "WAITING_APPROVAL":
            raise PermissionError("candidate is not waiting approval")
        run = dict(run)
        run["gate"] = {
            "status": "APPROVED",
            "actor": actor,
            "liveMachineControl": False,
            "HUMAN_APPROVAL_REQUIRED": True,
            "autoLiveCnc": False,
            "note": "Approval is for manufacturing candidate only; LIVE_CNC remains blocked.",
        }
        self.runs[run_id] = run
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
