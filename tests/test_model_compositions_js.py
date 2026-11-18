"""Static guards: model-compositions.js / print-workspace.js keep API strings out of HTML parsing (#502)."""
from __future__ import annotations

from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "fox3d" / "static"


@pytest.mark.parametrize("name", ["model-compositions.js", "print-workspace.js", "fox3d-pagination.js"])
def test_no_html_string_sinks(name: str) -> None:
    js = (STATIC / name).read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in js, f"{name} uses {sink}"


def test_fetch_all_pages_extracted_to_shared_module() -> None:
    shared = (STATIC / "fox3d-pagination.js").read_text(encoding="utf-8")
    assert "async function fetchAllPages(api, path)" in shared
    assert "window.fox3dFetchAllPages = fetchAllPages" in shared
    for name in ("print-workspace.js", "product-models.js", "model-compositions.js"):
        js = (STATIC / name).read_text(encoding="utf-8")
        assert "fox3dFetchAllPages" in js, f"{name} must use shared fox3dFetchAllPages"
        assert "async function fetchAllPages" not in js, f"{name} still duplicates async function fetchAllPages"


def test_model_compositions_artwork_options_are_dom_nodes() -> None:
    js = (STATIC / "model-compositions.js").read_text(encoding="utf-8")
    assert 'value="${a.id}"' not in js
    assert "new Option(" in js
    assert "option(a.name??'',a.id)" in js


def test_preview_urls_encode_api_ids() -> None:
    pw = (STATIC / "print-workspace.js").read_text(encoding="utf-8")
    assert "encodeURIComponent(s.generationId)" in pw
    mc = (STATIC / "model-compositions.js").read_text(encoding="utf-8")
    assert "encodeURIComponent(assetId)" in mc
