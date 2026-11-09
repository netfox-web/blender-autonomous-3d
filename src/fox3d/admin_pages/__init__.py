"""Plug-in admin pages: drop a module here, it is mounted automatically.

Each module in this package exposes ``router(provider) -> APIRouter`` and serves its page
from ``static/pages/<name>.html``; its own JS/CSS go in ``static/pages/`` and are served by
``/admin/pages/assets/{name}``. New pages therefore add files only (plus their own entry in
fox3d/features.py) and never edit shared wiring, so several pages can be built in parallel
without merge conflicts.
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


def page_routers(provider: Callable[[], Any]) -> list[APIRouter]:
    routers = [assets_router()]
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{__name__}.{info.name}")
        factory = getattr(module, "router", None)
        if callable(factory):
            routers.append(factory(provider))
    return routers
