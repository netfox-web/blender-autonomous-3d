"""Manufacturing release administration page."""
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from fox3d.admin_pages import page_response

FEATURES = {'releases': '/admin/releases'}


def router(_provider: Callable[[], Any]) -> APIRouter:
    r = APIRouter()

    @r.get('/admin/releases', response_class=HTMLResponse)
    def releases_page() -> HTMLResponse:
        return page_response('releases')

    return r
