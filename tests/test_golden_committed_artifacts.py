"""Lock committed Golden Product schema and manifest against live GoldenRecipe authority."""
from __future__ import annotations

import json
from pathlib import Path

from fox3d.golden_product import SKUS, VERSIONS, GoldenRecipe, build_golden, package_plan

GOLDEN_DIR = Path("data/golden_product")
SCHEMA_PATH = GOLDEN_DIR / "recipe.schema.json"
MANIFEST_PATH = GOLDEN_DIR / "three_tier_manifest.json"
REGENERATE_HINT = (
    "Committed Golden artifacts drifted from code. "
    "If the code change is intentional, regenerate with: "
    "python scripts/regenerate_golden_artifacts.py"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_committed_recipe_schema_matches_model():
    committed = _load_json(SCHEMA_PATH)
    live = GoldenRecipe.model_json_schema()
    assert committed == live, REGENERATE_HINT


def test_committed_manifest_recipe_matches_default_dump():
    manifest = _load_json(MANIFEST_PATH)
    assert manifest["recipe"] == GoldenRecipe().model_dump(mode="json"), REGENERATE_HINT


def test_committed_manifest_engineering_hash_matches_build_golden():
    manifest = _load_json(MANIFEST_PATH)
    assert manifest["engineeringHash"] == build_golden()["engineeringHash"], REGENERATE_HINT


def test_committed_manifest_historical_artwork_blocked_without_verified():
    manifest = _load_json(MANIFEST_PATH)
    rows = manifest["historicalArtwork"]
    sku_set = {row["sku"] for row in rows}
    assert sku_set == set(SKUS), f"missing SKU slots; expected {SKUS}, got {sorted(sku_set)}"
    for row in rows:
        assert row["truth"] == "BLOCKED", f"{row['sku']}: historical artwork must stay BLOCKED"
        assert row["version"] == "HISTORICAL_PENDING", f"{row['sku']}: version must stay HISTORICAL_PENDING"
        assert row["ready"] is False
        assert "VERIFIED" not in json.dumps(row), f"{row['sku']}: must not claim VERIFIED artwork"


def test_committed_manifest_historical_artwork_matches_package_plan():
    golden = build_golden()
    manifest = _load_json(MANIFEST_PATH)
    expected = [package_plan(sku, "HISTORICAL_PENDING", golden) for sku in SKUS]
    assert manifest["historicalArtwork"] == expected, REGENERATE_HINT


def test_committed_manifest_fixture_metadata():
    manifest = _load_json(MANIFEST_PATH)
    fixture_versions = [v for v in VERSIONS if v.startswith("FIXTURE")]
    assert manifest["fixtureVersions"] == fixture_versions
    assert manifest["fixtureNotice"] == "Synthetic calibration images only; not historical artwork"
