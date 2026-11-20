"""Admin page: KD SKU portfolio planning."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from fox3d.admin_pages import page_response

FEATURES = {"portfolio": "/admin/portfolio"}


def router(_provider: Callable[[], Any]) -> APIRouter:
    r = APIRouter()

    @r.get("/admin/portfolio")
    def portfolio_page() -> Any:
        return page_response("portfolio")

    return r