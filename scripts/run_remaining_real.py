from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.e2e import run_real_acceptance  # noqa: E402


def main() -> int:
    report = run_real_acceptance(ROOT)
    print(json.dumps({"productionReady": report["productionReady"], "rows": report["rows"]}, indent=2, default=str), flush=True)
    if report["productionReady"]:
        return 0
    if any(r["status"] == "BLOCKED" for r in report["rows"]):
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
