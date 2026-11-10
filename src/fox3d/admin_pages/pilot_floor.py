"""Admin page for pilot-floor: stations, dispatch, scan, exceptions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from fox3d.admin_pages import page_response

FEATURES = {"pilot-floor": "/admin/pilot-floor"}


def router(_provider: Callable[[], Any]) -> APIRouter:
    r = APIRouter()

    @r.get("/admin/pilot-floor")
    def pilot_floor_page() -> Any:
        return page_response("pilot-floor")

    return r
