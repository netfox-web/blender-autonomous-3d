from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .engine import analyze_case
from .fixtures import case_from_fixture
from .models import canonical_hash
from .store import JsonCaseStore


class BatchInterrupted(RuntimeError):
    pass


class FixtureBatchRunner:
    """Restartable local fixture preview; it has no external connectors."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir.resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = self.state_dir / "checkpoint.json"
        self.output_path = self.state_dir / "results.json"
        self.case_store = JsonCaseStore(self.state_dir / "cases")

    def run(self, manifest: dict[str, Any], *, resume: bool = False, stop_after: int | None = None) -> dict[str, Any]:
        manifest_hash = canonical_hash(manifest)
        checkpoint = self._load_checkpoint() if resume else None
        if checkpoint is not None:
            if checkpoint["manifest_hash"] != manifest_hash:
                raise ValueError("checkpoint manifest hash mismatch")
            next_index = int(checkpoint["next_index"])
            results = list(checkpoint["results"])
        else:
            next_index = 0
            results = []
            self._write_checkpoint(manifest_hash, next_index, results, "RUNNING")
        processed = 0
        cases = list(manifest["cases"])
        for index in range(next_index, len(cases)):
            case = case_from_fixture(cases[index])
            result = analyze_case(case)
            self.case_store.save_result(case.tenant_id, result)
            results.append({
                "case_id": case.case_id,
                "input_hash": result.input_hash,
                "candidate_set_id": result.candidate_set_id,
                "status": result.status,
                "expected_status": cases[index]["expected_status"],
            })
            next_index = index + 1
            processed += 1
            self._write_checkpoint(manifest_hash, next_index, results, "RUNNING")
            if stop_after is not None and processed >= stop_after and next_index < len(cases):
                raise BatchInterrupted(f"fixture batch interrupted after {processed} cases")
        output = {
            "schema_version": "fox3d.after-sales-visual.fixture-batch.v1",
            "manifest_hash": manifest_hash,
            "status": "COMPLETE",
            "case_count": len(cases),
            "results": results,
            "live_model_used": False,
            "external_write_performed": False,
        }
        self._atomic(self.output_path, output)
        self._write_checkpoint(manifest_hash, len(cases), results, "COMPLETE")
        return output

    def cancel(self, manifest: dict[str, Any]) -> dict[str, Any]:
        manifest_hash = canonical_hash(manifest)
        checkpoint = self._load_checkpoint() or {
            "manifest_hash": manifest_hash, "next_index": 0, "results": [], "status": "RUNNING"
        }
        if checkpoint["manifest_hash"] != manifest_hash:
            raise ValueError("checkpoint manifest hash mismatch")
        self._write_checkpoint(manifest_hash, checkpoint["next_index"], checkpoint["results"], "CANCELLED")
        return {**checkpoint, "status": "CANCELLED", "evidence_preserved": True}

    def _load_checkpoint(self) -> dict[str, Any] | None:
        if not self.checkpoint_path.exists():
            return None
        return json.loads(self.checkpoint_path.read_text(encoding="utf-8"))

    def _write_checkpoint(self, manifest_hash: str, next_index: int, results: list[dict], status: str) -> None:
        self._atomic(self.checkpoint_path, {
            "schema_version": "fox3d.after-sales-visual.fixture-checkpoint.v1",
            "manifest_hash": manifest_hash,
            "next_index": next_index,
            "results": results,
            "status": status,
        })

    @staticmethod
    def _atomic(path: Path, value: dict[str, Any]) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
