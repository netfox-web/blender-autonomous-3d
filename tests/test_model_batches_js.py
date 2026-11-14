"""model-batches.js history and progress must keep API strings out of innerHTML."""

from __future__ import annotations

from pathlib import Path


def test_model_batches_history_and_progress_use_dom_nodes() -> None:
    js = (
        Path(__file__).resolve().parents[1] / "src" / "fox3d" / "static" / "model-batches.js"
    ).read_text(encoding="utf-8")
    compact = js.replace(" ", "")
    assert "innerHTML" not in js
    assert "insertAdjacentHTML" not in js
    assert "a.href=" in compact
    assert "a.download=" in compact
    assert "textContent=" in compact
