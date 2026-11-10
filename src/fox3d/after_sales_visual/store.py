from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .models import AfterSalesResult, HumanDecision, canonical_hash

SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class JsonCaseStore:
    """Append-only review state for isolated demos and tests, never ERP storage."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: str, case_id: str) -> Path:
        if not SAFE.fullmatch(tenant_id) or not SAFE.fullmatch(case_id):
            raise ValueError("unsafe store identity")
        return self.root / tenant_id / f"{case_id}.json"

    def save_result(self, tenant_id: str, result: AfterSalesResult) -> dict:
        path = self._path(tenant_id, result.case_id)
        if path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
            if current["result"]["input_hash"] != result.input_hash:
                raise ValueError("case input changed; create a new revision instead of overwriting evidence")
            return current
        envelope = {"result": result.model_dump(mode="json"), "review_events": [], "content_hash": ""}
        envelope["content_hash"] = canonical_hash({"result": envelope["result"], "review_events": []})
        self._atomic(path, envelope)
        return envelope

    def append_decision(self, tenant_id: str, case_id: str, decision: HumanDecision) -> dict:
        path = self._path(tenant_id, case_id)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        event = decision.model_dump(mode="json")
        event["event_id"] = canonical_hash({"case": case_id, "decision": event})[:24]
        if all(existing["event_id"] != event["event_id"] for existing in envelope["review_events"]):
            envelope["review_events"].append(event)
        envelope["content_hash"] = canonical_hash({"result": envelope["result"], "review_events": envelope["review_events"]})
        self._atomic(path, envelope)
        return envelope

    @staticmethod
    def _atomic(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
