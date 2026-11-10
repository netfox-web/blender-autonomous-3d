"""Pilot workbench page."""
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from fox3d.admin_pages import page_response

FEATURES = {"pilot": "/admin/pilot"}


def router(provider: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    @router.get("/admin/pilot", response_class=HTMLResponse)
    def page() -> HTMLResponse:
        return page_response("pilot")

    return router
