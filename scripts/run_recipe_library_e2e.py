"""Clean-CODE acceptance for live supplier sources and reference recipe import.

This verifies HTTP/source evidence only. It never emits Blender/Engineering
acceptance and does not update any existing phase readiness documents.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fox3d.catalog_recipes import catalog_summary, import_library, load_library  # noqa: E402
from fox3d.evidence import inspect_repo_lineage  # noqa: E402
from fox3d.ids import new_id, sha256_bytes  # noqa: E402
from fox3d.infra import RecipeRegistry, utcnow  # noqa: E402


def run(expected_commit: str) -> dict:
    lineage = inspect_repo_lineage(ROOT)
    if lineage["evidenceCodeCommit"] != expected_commit:
        raise ValueError("expected CODE commit differs from HEAD")
    catalog = ROOT / "data/recipe_library/sonaqueen/catalog.json"
    library = load_library(catalog)
    results = []
    for product in library.products:
        for source in product.sources:
            request = Request(source.url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=25) as response:
                if response.status != 200 or response.url != source.url:
                    raise ValueError(f"unexpected HTTP response/redirect: {source.url}")
                data = response.read(10_000_001)
                if not data or len(data) > 10_000_000:
                    raise ValueError("empty or oversized source")
                mime = response.headers.get_content_type()
            if mime != source.mediaType:
                raise ValueError(f"MIME mismatch: {source.url}")
            digest = sha256_bytes(data)
            if source.mediaType == "image/jpeg":
                if digest != source.sha256:
                    raise ValueError(f"supplier image changed; review required: {source.url}")
                comparison = "EXACT_SNAPSHOT_BYTES"
            else:
                text = html.unescape(data.decode("utf-8"))
                if product.name not in text or product.sku not in text:
                    raise ValueError(f"supplier page identity changed: {product.sku}")
                comparison = "SKU_AND_NAME_ONLY_DYNAMIC_PAGE"
            results.append({"sku": product.sku, "sourceId": source.sourceId, "url": source.url,
                            "sha256": digest, "snapshotSha256": source.sha256,
                            "sizeBytes": len(data), "mediaType": mime, "comparison": comparison,
                            "checkedAt": utcnow().isoformat()})
    registry = RecipeRegistry()
    recipes = import_library(catalog, registry, tenant_id="sonaqueen-home")
    if any(r.status != "EXPERIMENTAL" or r.configuration["renderReady"] for r in recipes):
        raise ValueError("supplier references escalated to render-ready")
    summary = catalog_summary(catalog)
    return {"ok": True, "generationId": new_id(), "generatedAt": utcnow().isoformat(),
            "evidenceCodeCommit": expected_commit, "workingTreeClean": True,
            "executionMode": "LIVE_HTTP", "scope": "SUPPLIER_REFERENCE_LIBRARY_ONLY",
            "sourceChecks": results, "libraryHash": summary["libraryHash"],
            "productCount": len(recipes), "recipeIds": [r.recipe_id for r in recipes],
            "realBlenderAcceptance": False, "engineeringReady": False,
            "commercialAssetProductionReady": False, "globalProductionReady": False,
            "products": [{"sku": p["sku"], "blockers": p["blockers"]} for p in summary["products"]]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args(argv)
    try:
        report = run(args.expected_commit)
        output = ROOT / ".fox3d-data/recipe-library-acceptance" / report["generationId"] / "report.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "report": str(output), "generationId": report["generationId"]}))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
