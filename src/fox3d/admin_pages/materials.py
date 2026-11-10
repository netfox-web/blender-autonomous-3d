"""Admin page: materials, remnants, nesting benchmarks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from fox3d.admin_pages import page_response

FEATURES = {"materials": "/admin/materials"}


def router(_provider: Callable[[], Any]) -> APIRouter:
    r = APIRouter()

    @r.get("/admin/materials")
    def materials_admin() -> Any:
        return page_response("materials")

    return r
