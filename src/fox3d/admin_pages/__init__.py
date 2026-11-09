"""Plug-in admin pages: drop a module here, it is mounted automatically.

Each module in this package exposes ``router(provider) -> APIRouter`` and serves its page
from ``static/pages/<name>.html``; its own JS/CSS go in ``static/pages/`` and are served by
``/admin/pages/assets/{name}``. A module also declares ``FEATURES = {"<feature id>": "/admin/<name>", ...}``:
the feature directory then shows those features as pages with that link. New pages therefore
add files only and never edit shared wiring or fox3d/features.py, so several pages can be
built in parallel without merge conflicts.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

PAGES_DIR = Path(__file__).resolve().parent.parent / "static" / "pages"
PAGE_CSP = "default-src 'self'; img-src 'self' blob: data:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"
_ASSET = re.compile(r"^[a-z0-9][a-z0-9-]*\.(js|css)$")


def page_response(name: str) -> HTMLResponse:
    """Serve static/pages/<name>.html with the admin CSP."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        raise HTTPException(404)
    return HTMLResponse((PAGES_DIR / f"{name}.html").read_text(encoding="utf-8"), headers={"Content-Security-Policy": PAGE_CSP})


def assets_router() -> APIRouter:
    router = APIRouter()

    @router.get("/admin/pages/assets/{name}")
    def page_asset(name: str) -> FileResponse:
        path = PAGES_DIR / name
        if not _ASSET.fullmatch(name) or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="text/css" if name.endswith(".css") else "application/javascript")

    return router


def _modules() -> list[Any]:
    return [importlib.import_module(f"{__name__}.{m.name}") for m in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name)]


def page_routers(provider: Callable[[], Any]) -> list[APIRouter]:
    routers = [assets_router()]
    for module in _modules():
        factory = getattr(module, "router", None)
        if callable(factory):
            routers.append(factory(provider))
    return routers


def page_features() -> dict[str, str]:
    """feature id -> page href, as declared by plug-in page modules."""
    found: dict[str, str] = {}
    for module in _modules():
        for feature_id, href in (getattr(module, "FEATURES", None) or {}).items():
            if feature_id in found:
                raise ValueError(f"feature {feature_id} claimed by two pages")
            found[str(feature_id)] = str(href)
    return found
