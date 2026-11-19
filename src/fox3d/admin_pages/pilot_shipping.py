"""Admin page /admin/pilot-shipping: pallets, shipments, carrier quotes, carton labels, handoff."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from fox3d.admin_pages import page_response

FEATURES = {"pilot-shipping": "/admin/pilot-shipping"}


def router(_provider: Callable[[], Any]) -> APIRouter:
    r = APIRouter()

    @r.get("/admin/pilot-shipping", response_class=HTMLResponse)
    def pilot_shipping_page() -> HTMLResponse:
        return page_response("pilot-shipping")

    return r
