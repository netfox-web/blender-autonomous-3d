"""Validate and inspect supplier recipes without creating Engineering defaults."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.catalog_recipes import catalog_summary, import_library  # noqa: E402
from fox3d.infra import RecipeRegistry  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=ROOT / "data/recipe_library/sonaqueen/catalog.json")
    parser.add_argument("--sku", help="Show one SKU")
    parser.add_argument("--export", type=Path, help="Export verified reference recipes as JSON")
    parser.add_argument("--tenant", default="sonaqueen-home")
    args = parser.parse_args(argv)
    try:
        summary = catalog_summary(args.library)
        if args.sku:
            summary["libraryProductCount"] = summary["productCount"]
            summary["products"] = [p for p in summary["products"] if p["sku"] == args.sku]
            if not summary["products"]:
                raise ValueError(f"SKU not found: {args.sku}")
            summary["productCount"] = len(summary["products"])
        if args.export:
            if args.export.resolve().is_relative_to(args.library.resolve().parent):
                raise ValueError("export must be outside the source library directory")
            recipes = import_library(args.library, RecipeRegistry(), tenant_id=args.tenant)
            if args.sku:
                recipes = [r for r in recipes if r.configuration["sku"] == args.sku]
            args.export.parent.mkdir(parents=True, exist_ok=True)
            args.export.write_text(json.dumps([asdict(r) for r in recipes], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
