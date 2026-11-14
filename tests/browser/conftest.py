"""Playwright admin smoke: live uvicorn on a mock Platform fixture."""

from __future__ import annotations

import os
import socket
import threading
import time
import types
from collections.abc import Callable, Generator
from typing import Any, cast

import httpx
import pytest
import uvicorn
from playwright.sync_api import Browser, sync_playwright

from fox3d.api import create_app
from fox3d.features import resolved_features
from fox3d.platform import Platform

TENANT = "sonaqueen-home"
XSS_PROBE = 'browser-xss-38'
XSS_STRING = f'<img src=x onerror="window.__fox3dXss=1">-{XSS_PROBE}'


def _gpu(name: str, vram: float) -> dict[str, Any]:
    return {
        "blender": True,
        "blenderVersion": "mock-4.2",
        "cuda": True,
        "optix": True,
        "gpuCount": 1,
        "gpuName": name,
        "vramGb": vram,
        "driver": "mock",
        "gpus": [{"gpuIndex": 0, "name": name, "vramGb": vram, "freeVramGb": vram}],
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _make_platform(root) -> Platform:  # noqa: ANN001
    plat = Platform(root=root, mock_blender=True)
    plat.register_node(target_key="5080-1", name="RTX 5080 #1", detected=_gpu("NVIDIA GeForce RTX 5080", 16))
    plat.register_node(target_key="5090-1", name="RTX 5090 #1", detected=_gpu("NVIDIA GeForce RTX 5090", 32))
    return plat


def seed_xss_fixture(platform: Platform, tenant: str = TENANT) -> Callable[[], None]:
    """Strings that must render as text on admin pages, never execute."""
    platform.tenants.ensure(tenant)
    platform.pilot.receiving.import_receipt(
        {
            "material": XSS_STRING,
            "quantity": 1,
            "thickness": 18,
            "supplierLot": f"{XSS_PROBE}-lot",
            "source": "MANUAL",
        },
        tenant_id=tenant,
        actor="browser-xss",
        source="MANUAL",
        idempotency_key=f"{tenant}-{XSS_PROBE}-receipt",
    )
    platform.lots.create(
        tenant_id=tenant,
        material="WOOD_WHITE",
        thickness=18,
        sheet_count=1,
        supplier_lot=XSS_STRING,
    )

    platform.submit_job(
        {
            "tenantId": tenant,
            "jobType": XSS_STRING,
            "render": {"mode": "preview"},
        }
    )

    import fox3d.kd as kd_mod
    import fox3d.readiness as readiness_mod

    orig_flatpack = kd_mod.FLATPACK_PRODUCT_TYPES
    if XSS_STRING not in orig_flatpack:
        cast(Any, kd_mod).FLATPACK_PRODUCT_TYPES = tuple((*orig_flatpack, XSS_STRING))
    rec = platform.kd.build_sku(tenant_id=tenant, kind="OPEN_SHELF", render=False)
    spec = rec["spec"]
    spec["productId"] = XSS_STRING
    platform.parametrics[XSS_STRING] = {
        "spec": spec,
        "report": rec["report"],
        "bom": rec["bom"],
        "engineeringHash": rec["engineeringHash"],
    }

    run = platform.factory.run(tenant_id=tenant, render=False, wall_name="N")
    if run.get("runId"):
        stored = platform.factory.runs.get(run["runId"])
        if stored and stored.get("space"):
            stored["space"]["wallName"] = XSS_STRING

    _orig_kd_readiness = platform.kd.readiness

    def _kd_readiness(self, *, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        matrix = _orig_kd_readiness(evidence=evidence)
        matrix.setdefault("requiredChecks", {})["coreFactoryE2EReady"] = [XSS_STRING]
        return matrix

    setattr(platform.kd, "readiness", types.MethodType(_kd_readiness, platform.kd))

    _orig_scoped_readiness = readiness_mod.scoped_readiness

    def _scoped_readiness(*, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        matrix = _orig_scoped_readiness(evidence=evidence)
        matrix[f"{XSS_PROBE}Ready"] = {"label": XSS_STRING, "ready": False, "note": XSS_PROBE}
        return matrix

    readiness_mod.scoped_readiness = _scoped_readiness

    platform.pilot.stations.register(
        tenant_id=tenant,
        capabilities=["ASSEMBLY_MANUAL"],
        station_id=XSS_STRING,
        actor=XSS_STRING,
    )
    platform.pilot.identity.register_operator(
        tenant_id=tenant,
        display_name=XSS_STRING,
        operator_id=f"{XSS_PROBE}-operator",
    )

    def _restore_globals() -> None:
        cast(Any, kd_mod).FLATPACK_PRODUCT_TYPES = orig_flatpack
        readiness_mod.scoped_readiness = _orig_scoped_readiness

    return _restore_globals


def admin_page_features() -> list[dict[str, Any]]:
    return [f for f in resolved_features() if f.get("kind") == "page" and f.get("href")]


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "browser: Playwright Chromium smoke (skipped when FOX3D_SKIP_BROWSER=1 or Chromium unavailable)",
    )


def _chromium_usable() -> bool:
    require = os.environ.get("FOX3D_REQUIRE_LEGACY_BROWSER") == "1"
    if os.environ.get("FOX3D_SKIP_BROWSER") == "1" and not require:
        return False
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception as exc:
        if require:
            pytest.fail(f"Chromium is required for browser tests: {exc}")
        return False


@pytest.fixture(scope="session")
def browser_available() -> bool:
    return _chromium_usable()


@pytest.fixture(scope="module")
def admin_server(tmp_path_factory: pytest.TempPathFactory) -> Generator[dict[str, Any], None, None]:
    data_root = tmp_path_factory.mktemp("browser-admin")
    platform = _make_platform(data_root / "data")
    restore_globals = seed_xss_fixture(platform)
    port = _free_port()
    config = uvicorn.Config(create_app(platform), host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="admin-browser-uvicorn", daemon=True)
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
        pytest.fail("admin uvicorn did not become ready")
    try:
        yield {"base_url": base, "platform": platform, "port": port}
    finally:
        restore_globals()
        server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser_instance(browser_available: bool) -> Generator[Browser, None, None]:
    if not browser_available:
        if os.environ.get("FOX3D_REQUIRE_LEGACY_BROWSER") == "1":
            pytest.fail("Chromium is required for browser tests (FOX3D_REQUIRE_LEGACY_BROWSER=1)")
        pytest.skip("Chromium not available (set FOX3D_SKIP_BROWSER=1 to skip explicitly)")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def admin_page(browser_instance: Browser, admin_server: dict[str, Any]) -> Generator[Any, None, None]:
    context = browser_instance.new_context(
        locale="zh-TW",
        viewport={"width": 1280, "height": 900},
    )
    context.add_init_script(
        f"""
        try {{
          localStorage.setItem('fox3d.tenant', '{TENANT}');
        }} catch (e) {{ /* storage blocked */ }}
        window.__fox3dXss = 0;
        """
    )
    page = context.new_page()
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(str(exc)))
    page._fox3d_console_errors = console_errors  # type: ignore[attr-defined]
    yield page
    context.close()
