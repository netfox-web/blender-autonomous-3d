"""Regenerate committed Golden Product schema and manifest from live code (data/golden_product only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.golden_product import SKUS, VERSIONS, GoldenRecipe, build_golden, package_plan  # noqa: E402

GOLDEN_DIR = ROOT / "data" / "golden_product"
SCHEMA_PATH = GOLDEN_DIR / "recipe.schema.json"
MANIFEST_PATH = GOLDEN_DIR / "three_tier_manifest.json"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def build_manifest() -> dict:
    golden = build_golden()
    return {
        "recipe": GoldenRecipe().model_dump(mode="json"),
        "engineeringHash": golden["engineeringHash"],
        "historicalArtwork": [package_plan(sku, "HISTORICAL_PENDING", golden) for sku in SKUS],
        "fixtureVersions": [v for v in VERSIONS if v.startswith("FIXTURE")],
        "fixtureNotice": "Synthetic calibration images only; not historical artwork",
    }


def main() -> None:
    _write_json(SCHEMA_PATH, GoldenRecipe.model_json_schema())
    _write_json(MANIFEST_PATH, build_manifest())
    print(f"Wrote {SCHEMA_PATH.relative_to(ROOT)}")
    print(f"Wrote {MANIFEST_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
