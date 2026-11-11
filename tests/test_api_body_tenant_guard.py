"""POST routes must not let body tenantId override X-Tenant-Id; count bounds; resize/360 404."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app

HDR = "t1"
OTHER = "other"
HEADERS = {"X-Tenant-Id": HDR}


def _client(platform) -> TestClient:  # noqa: ANN001
    return TestClient(create_app(platform))


def _product_id(platform) -> str:  # noqa: ANN001
    created = platform.create_parametric({"tenantId": HDR, "kind": "STORAGE_CABINET", "width": 800})
    return created["spec"]["productId"]


def _twin_id(platform) -> str:  # noqa: ANN001
    twin = platform.create_twin({"tenantId": HDR, "sku": "guard-sku", "dimensions": {"width": 100, "height": 100, "depth": 50}})
    return twin["twinId"]


RouteCase = tuple[str, str, dict[str, Any] | None, Callable[[dict[str, Any]], str]]


def _no_cross_tenant_leak(platform) -> Callable[[dict[str, Any]], str]:  # noqa: ANN001
    def _check(_j: dict[str, Any]) -> str:
        leaked = [r["spec"]["tenantId"] for r in platform.parametrics.values() if r["spec"]["tenantId"] == OTHER]
        assert not leaked, f"parametric created under {OTHER}: {leaked}"
        return HDR

    return _check


def _cases(platform) -> list[RouteCase]:  # noqa: ANN001
    pid = _product_id(platform)
    catalog_tenant = lambda j: platform.parametrics[j["catalog"][0]["productId"]]["spec"]["tenantId"]  # noqa: E731
    return [
        (
            "jobs",
            "/api/3d/jobs",
            {"jobType": "BLENDER_PREVIEW", "scene": "WHITE_STUDIO"},
            lambda j: j["tenantId"],
        ),
        (
            "digital-twins",
            "/api/digital-twins",
            {"sku": "T-GUARD", "dimensions": {"width": 100, "height": 100, "depth": 40}},
            lambda j: j["tenantId"],
        ),
        (
            "parametric-products",
            "/api/parametric/products",
            {"kind": "SHOE_CABINET", "width": 800},
            lambda j: j["spec"]["tenantId"],
        ),
        (
            "variants",
            f"/api/parametric/products/{pid}/variants",
            {"text": "變體", "render": False},
            lambda j: j["baseSpec"]["tenantId"],
        ),
        (
            "render-preview",
            "/api/render/preview",
            {"scene": "WHITE_STUDIO"},
            lambda j: j["tenantId"],
        ),
        (
            "render-final",
            "/api/render/final",
            {"scene": "BLACK_LUXURY"},
            lambda j: j["tenantId"],
        ),
        (
            "product-rd",
            "/api/product-rd/generate",
            {"text": "書櫃 80cm"},
            lambda j: j["baseSpec"]["tenantId"],
        ),
        (
            "factory-spaces",
            "/api/factory/spaces",
            {"width": 3600, "depth": 3000, "height": 2600},
            lambda j: j["tenantId"],
        ),
        (
            "kd-skus",
            "/api/kd/skus",
            {"kind": "BEDSIDE_CABINET", "render": False},
            lambda j: j["spec"]["tenantId"],
        ),
        (
            "kd-catalog",
            "/api/kd/catalog",
            {"count": 2, "render": False},
            catalog_tenant,
        ),
        (
            "nesting-benchmarks",
            "/api/nesting/benchmarks",
            {},
            _no_cross_tenant_leak(platform),
        ),
        (
            "kd-candidates",
            "/api/kd/candidates",
            {"count": 2},
            _no_cross_tenant_leak(platform),
        ),
        (
            "retail-fixtures",
            "/api/retail/fixtures",
            {"family": "RISER_DISPLAY", "render": False},
            lambda j: j["tenantId"],
        ),
        (
            "packaging-structures",
            "/api/packaging/structures",
            {"family": "RSC_CARTON", "render": False},
            lambda j: j["tenantId"],
        ),
        (
            "acrylic-products",
            "/api/acrylic/products",
            {"kind": "MENU_STAND", "render": False},
            lambda j: j["tenantId"],
        ),
    ]


@pytest.fixture
def route_cases(platform):  # noqa: ANN001
    return _cases(platform)


@pytest.mark.parametrize("idx", range(15))
def test_post_body_other_tenant_forbidden(route_cases, platform, idx: int) -> None:  # noqa: ANN001
    _name, path, body, _tenant_of = route_cases[idx]
    client = _client(platform)
    payload = {**(body or {}), "tenantId": OTHER}
    res = client.post(path, json=payload, headers=HEADERS)
    assert res.status_code == 403, res.text


@pytest.mark.parametrize("idx", range(15))
def test_post_without_body_tenant_uses_header(route_cases, platform, idx: int) -> None:  # noqa: ANN001
    _name, path, body, tenant_of = route_cases[idx]
    client = _client(platform)
    res = client.post(path, json=body, headers=HEADERS)
    assert res.status_code == 200, res.text
    assert tenant_of(res.json()) == HDR


@pytest.mark.parametrize(
    ("path", "extra"),
    [
        ("/api/parametric/products/pid-placeholder/variants", {}),
        ("/api/kd/catalog", {}),
        ("/api/kd/candidates", {}),
    ],
)
@pytest.mark.parametrize("bad_count", [0, 101, "abc"])
def test_count_out_of_range_returns_422(platform, path: str, extra: dict, bad_count: object) -> None:  # noqa: ANN001
    client = _client(platform)
    if "pid-placeholder" in path:
        path = f"/api/parametric/products/{_product_id(platform)}/variants"
    res = client.post(path, json={**extra, "count": bad_count}, headers=HEADERS)
    assert res.status_code == 422


def test_resize_missing_or_foreign_product_is_404_chinese(platform) -> None:  # noqa: ANN001
    client = _client(platform)
    pid = _product_id(platform)
    missing = client.post(f"/api/parametric/products/no-such-id/resize", json={"width": 900, "render": False}, headers=HEADERS)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "找不到參數化商品"

    foreign = client.post(f"/api/parametric/products/{pid}/resize", json={"width": 900, "render": False}, headers={"X-Tenant-Id": OTHER})
    assert foreign.status_code == 404
    assert foreign.json()["detail"] == "找不到參數化商品"


def test_twin_360_missing_or_foreign_is_404_chinese(platform) -> None:  # noqa: ANN001
    client = _client(platform)
    twin_id = _twin_id(platform)
    missing = client.post(f"/api/digital-twins/no-such-twin/360", headers=HEADERS)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "找不到數位分身"

    foreign = client.post(f"/api/digital-twins/{twin_id}/360", headers={"X-Tenant-Id": OTHER})
    assert foreign.status_code == 404
    assert foreign.json()["detail"] == "找不到數位分身"
