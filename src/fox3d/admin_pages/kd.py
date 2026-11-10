"""Admin page: KD flat-pack catalog and structure generation (retail / packaging / acrylic)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from fox3d.admin_pages import page_response

FEATURES = {"kd": "/admin/kd", "structures": "/admin/kd#structures"}


def router(provider: Callable[[], Any]) -> APIRouter:
    _ = provider
    r = APIRouter()

    @r.get("/admin/kd")
    def kd_admin_page() -> Any:
        return page_response("kd")

    return r
