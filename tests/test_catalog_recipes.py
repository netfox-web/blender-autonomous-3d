"""Supplier evidence remains reviewable without masquerading as Engineering."""
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fox3d.catalog_recipes import Fact, SeedLibrary, catalog_summary, import_library, load_library
from fox3d.infra import RecipeRegistry

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data/recipe_library/sonaqueen/catalog.json"


@pytest.fixture
def catalog(tmp_path):
    destination = tmp_path / "library"
    shutil.copytree(CATALOG.parent, destination)
    return destination / "catalog.json"


def update(catalog, edit):
    data = json.loads(catalog.read_text(encoding="utf-8"))
    edit(data)
    catalog.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_three_supplier_dimensions_and_unsupported_geometry():
    library = load_library(CATALOG)
    assert [(p.sku, *(p.facts[k].value for k in ("widthMm", "depthMm", "heightMm"))) for p in library.products] == [
        ("MY-012", 602, 300, 1802), ("LI-D40", 415, 300, 1196), ("LI-PU63D-免組裝", 785, 300, 785)
    ]
    assert library.products[0].facts["labelledNarrowOpeningWidthMm"].value == 181.5
    assert library.products[2].facts["doorCount"].value == 3
    assert library.products[2].facts["compartmentCount"].value == 6
    summary = catalog_summary(CATALOG)
    assert summary["sourceIntegrityVerified"] is True
    assert len(summary["motherRecipes"]) == 3
    for p in summary["products"]:
        assert p["missingMeasurements"]
        assert p["requiredGeometryCapabilities"]
        assert not p["engineeringReady"] and not p["renderReady"] and not p["productionReady"]
    assert "sidePanelThicknessMm" in summary["products"][2]["missingMeasurements"]


def test_import_is_idempotent_and_tenant_isolated():
    registry = RecipeRegistry()
    first = import_library(CATALOG, registry, tenant_id="shop-a")
    again = import_library(CATALOG, registry, tenant_id="shop-a")
    other = import_library(CATALOG, registry, tenant_id="shop-b")
    assert [r.recipe_id for r in first] == [r.recipe_id for r in again]
    assert all(r.version == 1 for r in again)
    assert not set(r.recipe_id for r in first) & set(r.recipe_id for r in other)
    assert all(r.status == "EXPERIMENTAL" and r.compatible_capabilities == ["CATALOG_REFERENCE"] for r in first)
    assert len(registry.find(tenant_id="shop-a")) == 3


@pytest.mark.parametrize("status", ["CANDIDATE", "APPROVED", "PRODUCTION"])
def test_promoted_reference_is_never_overwritten(status):
    registry = RecipeRegistry()
    rows = import_library(CATALOG, registry, tenant_id="shop")
    registry.promote(rows[-1].recipe_id, status)
    with pytest.raises(ValueError, match="cannot overwrite"):
        import_library(CATALOG, registry, tenant_id="shop")
    assert rows[-1].status == status
    assert all(r.version == 1 for r in rows)


def test_revised_reference_creates_version_preserving_production(catalog):
    registry = RecipeRegistry()
    old = import_library(catalog, registry, tenant_id="shop")
    registry.promote(old[0].recipe_id, "PRODUCTION")
    old_config = copy.deepcopy(old[0].configuration)
    update(catalog, lambda d: d["products"][0]["notes"].append("Added review note."))
    new = import_library(catalog, registry, tenant_id="shop")
    assert new[0].recipe_id != old[0].recipe_id
    assert new[0].version == 2 and new[0].status == "EXPERIMENTAL"
    assert old[0].configuration == old_config and old[0].status == "PRODUCTION"


def test_preflight_refusal_does_not_partially_import(catalog):
    registry = RecipeRegistry()
    original = import_library(catalog, registry, tenant_id="shop")
    registry.promote(original[-1].recipe_id, "PRODUCTION")
    update(catalog, lambda d: d["products"][0]["notes"].append("Changed first product."))
    with pytest.raises(ValueError):
        import_library(catalog, registry, tenant_id="shop")
    assert len(registry.find(tenant_id="shop")) == 3


@pytest.mark.parametrize("tenant", ["", "  ", "system"])
def test_explicit_tenant_required(tenant):
    with pytest.raises(ValueError, match="tenant"):
        import_library(CATALOG, RecipeRegistry(), tenant_id=tenant)


@pytest.mark.parametrize("damage", ["missing", "tampered", "empty"])
def test_source_integrity_failures(catalog, damage):
    source = catalog.parent / "sources/MY-012-detail-09.jpg"
    if damage == "missing":
        source.unlink()
    else:
        source.write_bytes(b"corruption" if damage == "tampered" else b"")
    registry = RecipeRegistry()
    with pytest.raises(ValueError, match="source"):
        import_library(catalog, registry, tenant_id="shop")
    assert registry.find(tenant_id="shop") == []


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), 0, -1, "602"])
def test_invalid_mm_values_rejected(value):
    with pytest.raises(ValueError):
        Fact(value=value, unit="mm", sourceIds=["s"], method="LABEL_TRANSCRIPTION", observation="label")


def test_pixel_estimates_cannot_be_measurements():
    with pytest.raises(ValueError, match="pixel"):
        Fact(value=602, unit="mm", sourceIds=["s"], method="VISUAL_OBSERVATION", observation="estimated")


@pytest.mark.parametrize("edit", [
    lambda d: d["products"].append(copy.deepcopy(d["products"][0])),
    lambda d: d["products"][0]["sources"].append(copy.deepcopy(d["products"][0]["sources"][0])),
    lambda d: d["products"][0]["sources"][0].update(path="../outside.html"),
    lambda d: d["products"][0]["sources"][0].update(path="sources/C:escape.html"),
    lambda d: d["products"][0]["sources"][0].update(url="https://example.com/file"),
    lambda d: d["products"][0]["facts"]["widthMm"].update(sourceIds=["foreign"]),
    lambda d: d["products"][0]["facts"]["widthMm"].update(unit="count"),
    lambda d: d["products"][0].update(productionReady=True),
    lambda d: d["products"][0]["facts"].pop("widthMm"),
    lambda d: d["products"][2]["facts"]["doorCount"].update(value=6),
    lambda d: d["products"][0]["facts"]["doorCount"].update(value=1),
    lambda d: d["products"][1]["facts"]["rowCount"].update(value=2),
])
def test_malformed_catalog_is_rejected(catalog, edit):
    update(catalog, edit)
    with pytest.raises(ValueError):
        load_library(catalog)


def test_foreign_page_identity_fails_even_with_matching_hash(catalog):
    update(catalog, lambda d: d["products"][0].update(sku="OTHER-SKU"))
    with pytest.raises(ValueError, match="identity"):
        load_library(catalog)


def test_cli_export_and_unknown_sku(tmp_path):
    export = tmp_path / "recipes.json"
    cmd = [sys.executable, str(ROOT / "scripts/inspect_recipe_library.py")]
    run = subprocess.run(cmd + ["--sku", "LI-D40", "--export", str(export)], capture_output=True, text=True, encoding="utf-8", env=_utf8_env())
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["productCount"] == 1
    rows = json.loads(export.read_text(encoding="utf-8"))
    assert len(rows) == 1 and rows[0]["configuration"]["sku"] == "LI-D40"
    assert rows[0]["status"] == "EXPERIMENTAL"
    bad = subprocess.run(cmd + ["--sku", "nonexistent"], capture_output=True, text=True, encoding="utf-8", env=_utf8_env())
    assert bad.returncode == 1 and "SKU not found" in bad.stderr
    protected = subprocess.run(cmd + ["--export", str(CATALOG)], capture_output=True, text=True, encoding="utf-8", env=_utf8_env())
    assert protected.returncode == 1 and "outside" in protected.stderr


def _utf8_env():
    import os
    # Simulate a legacy Windows console; CLI output must still be UTF-8.
    return {**os.environ, "PYTHONIOENCODING": "cp950"}
