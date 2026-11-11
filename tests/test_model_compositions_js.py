"""Static guards on model-compositions.js — API strings must not bypass esc()."""
from __future__ import annotations

from pathlib import Path


def test_model_compositions_escapes_asset_ids_in_artwork_options() -> None:
    js = (
        Path(__file__).resolve().parents[1] / "src" / "fox3d" / "static" / "model-compositions.js"
    ).read_text(encoding="utf-8")
    assert 'value="${a.id}"' not in js
    assert 'value="${esc(a.id)}"' in js
