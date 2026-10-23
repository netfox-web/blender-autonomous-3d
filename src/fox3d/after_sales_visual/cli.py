from __future__ import annotations

import json

from .engine import analyze_case
from .fixtures import case_from_fixture, load_fixture_manifest


def main() -> int:
    manifest = load_fixture_manifest()
    rows = []
    for item in manifest["cases"]:
        result = analyze_case(case_from_fixture(item))
        rows.append({"case_id": item["case_id"], "expected": item["expected_status"], "actual": result.status})
    print(json.dumps({"evidence_class": "MOCK_REGRESSION", "live_model_used": False, "cases": rows}, ensure_ascii=False, indent=2))
    return 0 if all(row["expected"] == row["actual"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
