"""System health and host discovery page."""
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from fox3d.admin_pages import page_response

FEATURES = {"system": "/admin/system"}


def router(_provider: Callable[[], Any]) -> APIRouter:
    r = APIRouter()

    @r.get("/admin/system", response_class=HTMLResponse)
    def system_page() -> HTMLResponse:
        return page_response("system")

    return r
