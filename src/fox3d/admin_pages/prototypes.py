"""Admin page: prototype validation board and unit floor operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from fox3d.admin_pages import page_response

FEATURES = {"prototypes": "/admin/prototypes"}


def router(_provider: Callable[[], Any]) -> APIRouter:
    r = APIRouter()

    @r.get("/admin/prototypes")
    def prototypes_admin() -> Any:
        return page_response("prototypes")

    return r