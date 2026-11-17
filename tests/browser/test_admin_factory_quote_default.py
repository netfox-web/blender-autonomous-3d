"""Factory admin page: default quote detail must track the newest list item."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Generator
from typing import Any

import httpx
import pytest
import uvicorn
from playwright.sync_api import Browser

from fox3d.api import create_app
from fox3d.platform import Platform
from tests.browser.conftest import TENANT, _make_platform

pytestmark = pytest.mark.browser


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def factory_quote_server(tmp_path) -> Generator[dict[str, Any], None, None]:  # noqa: ANN001
    data_root = tmp_path / "data"
    platform = _make_platform(data_root)
    platform.tenants.ensure(TENANT)
    port = _free_port()
    config = uvicorn.Config(create_app(platform), host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="factory-quote-uvicorn", daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/health", timeout=1.0).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        pytest.fail("factory quote uvicorn did not become ready")
    try:
        yield {"base_url": base, "platform": platform}
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _open_factory(page, base_url: str) -> None:  # noqa: ANN001
    page.goto(f"{base_url}/admin/factory", wait_until="domcontentloaded")
    page.wait_for_selector(".fx-side", timeout=20_000)
    page.wait_for_load_state("networkidle")


def _wait_detail_quote_id(page, quote_id: str) -> None:  # noqa: ANN001
    page.wait_for_function(
        "(qid) => {"
        "  const el = document.getElementById('qd-summary');"
        "  return el && !el.closest('[hidden]') && (el.innerText || '').includes(qid);"
        "}",
        arg=quote_id,
        timeout=25_000,
    )


def _seed_many_quotes(platform: Platform, count: int, *, tenant: str = TENANT) -> str:
    fac = platform.factory
    newest_id = ""
    for idx in range(count):
        stamp = f"2030-07-01T00:{idx // 60:02d}:{idx % 60:02d}+00:00"
        qid = f"ui-quote-{idx:03d}"
        rid = f"ui-run-{idx:03d}"
        fac.quotes[qid] = {"quoteId": qid, "estimatedCost": 1000 + idx, "suggestedPrice": 1200 + idx}
        fac.runs[rid] = {
            "runId": rid,
            "tenantId": tenant,
            "createdAt": stamp,
            "quote": {"quoteId": qid},
            "gate": {"status": "WAITING_APPROVAL"},
            "space": {"wallName": "N"},
            "assembly": {"cabinetCount": 1},
        }
        fac._quote_run_index[qid] = rid
        newest_id = qid
    fac.persist()
    return newest_id


def test_factory_page_defaults_detail_to_newest_of_three(
    browser_instance: Browser,
    factory_quote_server: dict[str, Any],
) -> None:
    base = factory_quote_server["base_url"]
    headers = {"X-Tenant-Id": TENANT}

    newest = ""
    with httpx.Client(base_url=base, headers=headers, timeout=60.0) as client:
        for _ in range(3):
            res = client.post(
                "/api/factory/run",
                json={"text": "鞋櫃", "render": False},
            )
            assert res.status_code == 200
            newest = res.json()["quote"]["quoteId"]
        listed = client.get("/api/factory/quotes")
        assert listed.status_code == 200
        items = listed.json()["items"]
        assert items[0]["quoteId"] == newest

    context = browser_instance.new_context(locale="zh-TW", viewport={"width": 1280, "height": 900})
    context.add_init_script(
        f"""
        try {{
          localStorage.setItem('fox3d.tenant', '{TENANT}');
        }} catch (e) {{ /* storage blocked */ }}
        """
    )
    page = context.new_page()
    try:
        _open_factory(page, base)
        _wait_detail_quote_id(page, newest)
        selected = page.locator("#fc-quotes-tbody tr.selected code").first
        assert selected.count() == 1
        assert selected.inner_text() == newest
    finally:
        context.close()


def test_factory_page_defaults_detail_when_over_quote_limit(
    browser_instance: Browser,
    factory_quote_server: dict[str, Any],
) -> None:
    platform: Platform = factory_quote_server["platform"]
    base = factory_quote_server["base_url"]
    newest = _seed_many_quotes(platform, 105)

    context = browser_instance.new_context(locale="zh-TW", viewport={"width": 1280, "height": 900})
    context.add_init_script(
        f"""
        try {{
          localStorage.setItem('fox3d.tenant', '{TENANT}');
        }} catch (e) {{ /* storage blocked */ }}
        """
    )
    page = context.new_page()
    try:
        _open_factory(page, base)
        _wait_detail_quote_id(page, newest)
        rows = page.locator("#fc-quotes-tbody tr")
        assert rows.count() == 100
        assert rows.first.locator("code").inner_text() == newest
        assert "selected" in (rows.first.get_attribute("class") or "")
    finally:
        context.close()