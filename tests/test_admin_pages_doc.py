"""Keep the documented page inventory in sync with the feature directory."""

from pathlib import Path

from fox3d.features import resolved_features


def test_admin_pages_are_documented() -> None:
    doc = (Path(__file__).resolve().parents[1] / "docs" / "ADMIN_PAGES.md").read_text(encoding="utf-8")
    # Match the complete first table cell so a nested path cannot cover its parent.
    cells = {line.split("|", 2)[1].strip().strip("`") for line in doc.splitlines() if line.startswith("|")}
    pages = {
        feature["href"]
        for feature in resolved_features()
        if feature["kind"] == "page" and feature.get("href", "").startswith("/admin")
    }
    assert pages, "feature directory contains no admin pages"
    assert not (pages - cells), f"admin pages missing from docs/ADMIN_PAGES.md: {sorted(pages - cells)}"
