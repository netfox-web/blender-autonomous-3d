"""Source-backed product references for RecipeRegistry; never Engineering authority.

Supplier dimensions are transcriptions of labels, not pixel measurements. These
records remain EXPERIMENTAL until a separate, reviewed engineering implementation
and REAL render acceptance exist. No CabinetSpec defaults are applied here.
"""

from __future__ import annotations

import copy
import html
import json
import math
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fox3d.ids import stable_hash, sha256_bytes
from fox3d.infra import Recipe, RecipeRegistry


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Source(StrictRecord):
    sourceId: str = Field(min_length=1)
    url: str
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mediaType: Literal["image/jpeg", "text/html"]
    capturedAt: str

    @model_validator(mode="after")
    def validate_source(self) -> Source:
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or parsed.hostname != "home.sonaqueen.com.tw" or parsed.username or parsed.password or parsed.port:
            raise ValueError("source must be an HTTPS Sonaqueen public URL")
        if not re.fullmatch(r"sources/[^/\\:]+", self.path) or ".." in self.path:
            raise ValueError("source must be a file under sources/")
        from datetime import datetime

        if datetime.fromisoformat(self.capturedAt).tzinfo is None:
            raise ValueError("capturedAt must include timezone")
        return self


class Fact(StrictRecord):
    value: str | int | float | bool
    unit: Literal["mm", "count", "text", "boolean"]
    sourceIds: list[str] = Field(min_length=1)
    method: Literal["PAGE_TEXT", "LABEL_TRANSCRIPTION", "VISUAL_OBSERVATION"]
    observation: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_value(self) -> Fact:
        if self.unit in {"mm", "count"}:
            if type(self.value) not in {int, float} or not math.isfinite(self.value):
                raise ValueError("measurement must be finite and numeric")
            if self.value < 0 or (self.unit == "mm" and self.value == 0):
                raise ValueError("invalid measurement")
            if self.unit == "count" and type(self.value) is not int:
                raise ValueError("count must be integer")
            if self.unit == "mm" and self.method == "VISUAL_OBSERVATION":
                raise ValueError("pixel-inferred dimensions are not supplier measurements")
        if self.unit == "text" and not isinstance(self.value, str):
            raise ValueError("text fact must be a string")
        if self.unit == "boolean" and type(self.value) is not bool:
            raise ValueError("boolean fact must be a boolean")
        return self


FAMILIES = {
    "STAGGERED_OPEN_CUBBY": {
        "name": "交錯隔板開放格櫃",
        "requirements": ["segmented_dividers", "row_specific_cubby_layout"],
        "missing": ["panelThicknessMm", "backThicknessMm", "panelJoinery", "rowDividerCoordinates"],
    },
    "STACKED_HINGED_CABINET": {
        "name": "上下分層平開門櫃",
        "requirements": ["row_specific_doors", "per_door_hinge_pivots"],
        "missing": ["panelThicknessMm", "backThicknessMm", "doorThicknessMm", "doorGapsMm", "hingeSpecification"],
    },
    "ROW_SLIDING_CABINET": {
        "name": "分層滑門格櫃",
        "requirements": ["row_specific_sliding_doors", "slide_tracks_and_travel"],
        "missing": ["sidePanelThicknessMm", "backThicknessMm", "doorThicknessMm", "doorGapsMm", "trackSpecification", "slideTravelMm"],
    },
}


class ProductSeed(StrictRecord):
    sku: str = Field(min_length=1)
    name: str = Field(min_length=1)
    pageUrl: str
    family: Literal["STAGGERED_OPEN_CUBBY", "STACKED_HINGED_CABINET", "ROW_SLIDING_CABINET"]
    sources: list[Source] = Field(min_length=1)
    facts: dict[str, Fact]
    notes: list[str]

    @model_validator(mode="after")
    def validate_links(self) -> ProductSeed:
        ids = [s.sourceId for s in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source id")
        if not any(s.url == self.pageUrl and s.mediaType == "text/html" for s in self.sources):
            raise ValueError("product page must have a captured HTML source")
        for name, fact in self.facts.items():
            if not set(fact.sourceIds).issubset(ids):
                raise ValueError(f"unknown source for {name}")
            expected = ("mm" if name.endswith("Mm") else "count" if name.endswith("Count")
                        else "text" if name == "material" else "boolean" if name == "handles" else None)
            if expected and fact.unit != expected:
                raise ValueError(f"wrong unit for {name}")
        for name in ("widthMm", "depthMm", "heightMm", "doorCount", "compartmentCount", "rowCount", "material"):
            if name not in self.facts:
                raise ValueError(f"missing required supplier fact: {name}")
        doors, compartments, rows = [self.facts[k].value for k in ("doorCount", "compartmentCount", "rowCount")]
        if rows <= 0 or compartments <= 0:
            raise ValueError("row and compartment counts must be positive")
        if self.family == "STAGGERED_OPEN_CUBBY" and doors != 0:
            raise ValueError("open cubby cannot have doors")
        if self.family == "STACKED_HINGED_CABINET" and not doors == compartments == rows:
            raise ValueError("stacked family requires one door and compartment per row")
        if self.family == "ROW_SLIDING_CABINET" and not (doors == rows and compartments == 2 * rows):
            raise ValueError("sliding family requires one door and two compartments per row")
        return self


class SeedLibrary(StrictRecord):
    schemaVersion: Literal[1]
    libraryId: Literal["sonaqueen-home"]
    products: list[ProductSeed] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_products(self) -> SeedLibrary:
        skus = [p.sku for p in self.products]
        if len(skus) != len(set(skus)):
            raise ValueError("duplicate SKU")
        return self


def verify_sources(library: SeedLibrary, root: Path) -> None:
    """Verify checked-in bytes on every import, including when used offline."""
    root = root.resolve()
    for product in library.products:
        page = next(s for s in product.sources if s.url == product.pageUrl and s.mediaType == "text/html")
        page_text = None
        for source in product.sources:
            path = (root / source.path).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError(f"missing/outside source: {product.sku}/{source.sourceId}")
            data = path.read_bytes()
            if not data or sha256_bytes(data) != source.sha256:
                raise ValueError(f"source hash mismatch: {product.sku}/{source.sourceId}")
            if source.mediaType == "image/jpeg" and not (data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9")):
                raise ValueError("invalid JPEG source")
            if source.mediaType == "text/html" and b"<html" not in data[:1024].lower():
                raise ValueError("invalid HTML source")
            if source.sourceId == page.sourceId:
                page_text = html.unescape(data.decode("utf-8"))
        if page_text is None or product.sku not in page_text or product.name not in page_text:
            raise ValueError(f"page identity mismatch: {product.sku}")
        for source in product.sources:
            if source.mediaType == "image/jpeg" and unquote(urlparse(source.url).path) not in unquote(page_text):
                raise ValueError(f"image is not referenced by product page: {source.sourceId}")


def load_library(path: Path) -> SeedLibrary:
    library = SeedLibrary.model_validate(json.loads(path.read_text(encoding="utf-8")))
    verify_sources(library, path.parent)
    return library


def reference_configuration(product: ProductSeed) -> dict[str, Any]:
    family = FAMILIES[product.family]
    missing = [key for key in family["missing"] if key not in product.facts]
    return {
        "purpose": "SUPPLIER_REFERENCE_ONLY",
        "sku": product.sku,
        "motherRecipeKey": f"sonaqueen.{product.family.lower()}.v1",
        "family": product.family,
        "supplierReference": product.model_dump(mode="json"),
        "missingMeasurements": missing,
        "requiredGeometryCapabilities": list(family["requirements"]),
        "engineeringReady": False,
        "renderReady": False,
        "productionReady": False,
        "blockers": [*[f"missing:{key}" for key in missing],
                     "geometry_adapter_not_validated", "engineering_not_verified", "real_render_not_verified"],
    }


def import_library(path: Path, registry: RecipeRegistry, *, tenant_id: str) -> list[Recipe]:
    """Import immutable reference versions; unchanged imports are idempotent.

    Existing approval state can never be overwritten by a website refresh.
    Planning the entire import before mutation also prevents partial imports.
    """
    if not tenant_id.strip() or tenant_id != tenant_id.strip() or tenant_id == "system":
        raise ValueError("an explicit non-system tenant is required")
    library = load_library(path)
    planned: list[tuple[Recipe, bool]] = []
    existing = registry.find(tenant_id=tenant_id)
    for product in library.products:
        config = reference_configuration(product)
        digest = stable_hash(config)
        key = f"sonaqueen.product.{product.sku}"
        recipe_id = "supplier_" + stable_hash({"tenant": tenant_id, "key": key, "hash": digest})
        found = registry.get(recipe_id)
        if found:
            if found.status != "EXPERIMENTAL" or found.configuration != config or found.tenant_id != tenant_id:
                raise ValueError("existing recipe is promoted or differs; cannot overwrite")
            planned.append((found, False))
            continue
        versions = [r.version for r in existing if r.recipe_key == key and r.tenant_id == tenant_id]
        recipe = Recipe(
            recipe_id=recipe_id, recipe_key=key, recipe_type="PRODUCT_REFERENCE",
            version=max(versions, default=0) + 1, status="EXPERIMENTAL",
            tenant_id=tenant_id, name=product.name, configuration=copy.deepcopy(config),
            tags=["sonaqueen", product.family, "supplier-reference"],
            compatible_capabilities=["CATALOG_REFERENCE"],
        )
        planned.append((recipe, True))
    for recipe, is_new in planned:
        if is_new:
            registry.upsert(recipe)
    return [recipe for recipe, _ in planned]


def catalog_summary(path: Path) -> dict[str, Any]:
    library = load_library(path)
    return {
        "libraryId": library.libraryId,
        "libraryHash": stable_hash(library.model_dump(mode="json")),
        "sourceIntegrityVerified": True,
        "productCount": len(library.products),
        "motherRecipes": [{"key": f"sonaqueen.{key.lower()}.v1", **copy.deepcopy(value)}
                          for key, value in FAMILIES.items() if any(p.family == key for p in library.products)],
        "products": [{"sku": p.sku, "name": p.name, **reference_configuration(p)} for p in library.products],
    }
