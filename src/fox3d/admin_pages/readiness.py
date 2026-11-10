"""Admin page: scoped readiness, release gates, physical OS, commerce import."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from fox3d.admin_pages import page_response

FEATURES = {
    "readiness": "/admin/readiness",
    "physical-os": "/admin/readiness#physical-os",
    "commerce": "/admin/readiness#commerce",
}


def router(_provider: Callable[[], Any]) -> APIRouter:
    r = APIRouter()

    @r.get("/admin/readiness")
    def readiness_page() -> Any:
        return page_response("readiness")

    return r
