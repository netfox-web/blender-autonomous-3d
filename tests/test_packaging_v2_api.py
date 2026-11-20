"""Packaging Engineering V2 HTTP API and kd-packaging admin panel contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fox3d.api import create_app
from fox3d.packaging import dieline_primitives

PAGES = Path(__file__).resolve().parents[1] / "src/fox3d/static/pages"
_FORBIDDEN = re.compile(r"\b(REAL|CERTIFIED)\b")


def _no_forbidden_labels(payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    assert not _FORBIDDEN.search(text), text


@pytest.fixture()
def client(platform):  # noqa: ANN001
    return TestClient(create_app(platform))


def _good_compression_body() -> dict[str, Any]:
    return {
        "grade": "KRAFT_B_ECT32",
        "safetyFactor": 3.0,
        "inner": {"length": 300, "width": 200, "height": 150},
        "productWeightKg": 2.0,
        "stackCount": 6,
    }


def test_board_grades_list(client: TestClient) -> None:
    res = client.get("/api/packaging/v2/board-grades")
    assert res.status_code == 200
    body = res.json()
    _no_forbidden_labels(body)
    assert len(body["items"]) >= 2
    for row in body["items"]:
        assert row["source"] == "CONFIG"
        assert row["certification"] is False
        assert row["sku"]


def test_compression_happy_path_and_deterministic(client: TestClient) -> None:
    body = _good_compression_body()
    a = client.post("/api/packaging/v2/compression", json=body)
    b = client.post("/api/packaging/v2/compression", json=body)
    assert a.status_code == 200 and b.status_code == 200
    assert a.json() == b.json()
    _no_forbidden_labels(a.json())
    comp = a.json()["compression"]
    assert comp["source"] == "ENGINEERING_ESTIMATE"
    assert comp["certification"] is False
    stack = a.json()["stack"]
    assert stack["label"] == "ENGINEERING_ESTIMATE"
    assert isinstance(stack["ok"], bool)


@pytest.mark.parametrize(
    "patch",
    [
        {"inner": {"length": 0, "width": 200, "height": 150}},
        {"inner": {"length": 300, "width": -1, "height": 150}},
        {"inner": {"length": "NaN", "width": 200, "height": 150}},
        {"inner": {"length": "Infinity", "width": 200, "height": 150}},
        {"inner": {"length": 5001, "width": 200, "height": 150}},
        {"safetyFactor": 0},
        {"safetyFactor": "NaN"},
        {"grade": "NO_SUCH_GRADE"},
        {"productWeightKg": 1, "stackCount": None},
        {"productWeightKg": -1, "stackCount": 3},
        {"productWeightKg": 1, "stackCount": 0},
    ],
)
def test_compression_validation_422(client: TestClient, patch: dict[str, Any]) -> None:
    body = _good_compression_body()
    body.update(patch)
    if "inner" in patch:
        body["inner"] = patch["inner"]
    res = client.post("/api/packaging/v2/compression", json=body)
    assert res.status_code == 422
    assert "KeyError" not in res.text


@pytest.mark.parametrize("body", [None, [], "x", 1])
def test_compression_malformed_body_422(client: TestClient, body: Any) -> None:
    res = client.post("/api/packaging/v2/compression", json=body)
    assert res.status_code == 422


def test_dieline_validate_ok_and_deterministic(client: TestClient) -> None:
    die = dieline_primitives("RSC_CARTON", {"length": 120, "width": 80, "height": 40})
    a = client.post("/api/packaging/v2/dieline/validate", json=die)
    b = client.post("/api/packaging/v2/dieline/validate", json=die)
    assert a.status_code == 200 and a.json() == b.json()
    _no_forbidden_labels(a.json())
    assert a.json()["ok"] is True


def test_dieline_too_many_panels_422(client: TestClient) -> None:
    panels = [{"id": f"p{i}", "w": 20, "h": 20} for i in range(65)]
    res = client.post("/api/packaging/v2/dieline/validate", json={"panels": panels})
    assert res.status_code == 422


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        (None, None),
        ("bad", None),
        ({"panels": "x"}, "panels 須為陣列"),
        ({"panels": ["a"]}, "panels[0] 須為物件"),
        ({"panels": [{"id": "ok", "w": 20, "h": 20}, "a"]}, "panels[1] 須為物件"),
        ({"panels": [{"id": {"x": 1}, "w": 10, "h": 10}]}, "panels[0].id 須為字串或整數"),
        ({"panels": [{"id": 1.5, "w": 20, "h": 20}]}, "panels[0].id 須為字串或整數"),
        ({"panels": [{"id": True, "w": 20, "h": 20}]}, "panels[0].id 須為字串或整數"),
        ({"panels": [{"id": "ok", "w": 20, "h": 20}], "glue": "nope"}, "glue 須為陣列"),
        ({"panels": [{"id": "ok", "w": 20, "h": 20}], "crease": 1}, "crease 須為陣列"),
        ({"dieline": {"panels": ["a"]}}, "panels[0] 須為物件"),
    ],
)
def test_dieline_malformed_422(client: TestClient, body: Any, detail: str | None) -> None:
    res = client.post("/api/packaging/v2/dieline/validate", json=body)
    assert res.status_code == 422
    assert "Traceback" not in res.text
    assert "AttributeError" not in res.text
    assert "unhashable" not in res.text
    if detail is not None:
        assert res.json()["detail"] == detail


def test_dieline_scalar_id_and_feature_lists_ok(client: TestClient) -> None:
    body = {
        "panels": [{"id": 7, "w": 20, "h": 20}, {"id": "flap", "w": 20, "h": 20}],
        "glue": [{"a": 7, "b": "flap"}],
        "crease": [{"a": 7, "b": "flap"}],
    }
    res = client.post("/api/packaging/v2/dieline/validate", json=body)
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_bleed_validate_happy(client: TestClient) -> None:
    body = {"zones": [{"name": "main", "bleedMm": 3, "safeMm": 5}]}
    res = client.post("/api/packaging/v2/bleed/validate", json=body)
    assert res.status_code == 200
    _no_forbidden_labels(res.json())
    assert res.json()["ok"] is True


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"zones": 5}, "zones 須為陣列"),
        ({"zones": ["x"]}, "zones[0] 須為物件"),
        ({"zones": [None]}, "zones[0] 須為物件"),
        ({"zones": [{"bleedMm": "abc"}]}, "zones[0].bleedMm 必須是有限數值"),
        ({"zones": [{"safeMm": "abc"}]}, "zones[0].safeMm 必須是有限數值"),
        ({"zones": [{"bleedMm": True}]}, "zones[0].bleedMm 必須是有限數值"),
        ({"zones": [{"safeMm": False}]}, "zones[0].safeMm 必須是有限數值"),
        ({"bleed": {"zones": 5}}, "zones 須為陣列"),
    ],
)
def test_bleed_malformed_422(client: TestClient, body: Any, detail: str) -> None:
    res = client.post("/api/packaging/v2/bleed/validate", json=body)
    assert res.status_code == 422
    assert res.json()["detail"] == detail
    for leaked in ("Traceback", "AttributeError", "TypeError", "ValueError", "unhashable"):
        assert leaked not in res.text


def test_bleed_overflow_number_422(client: TestClient) -> None:
    res = client.post(
        "/api/packaging/v2/bleed/validate",
        content=b'{"zones":[{"bleedMm":1e309,"safeMm":5}]}',
        headers={"content-type": "application/json"},
    )
    assert res.status_code == 422
    assert res.json()["detail"] == "zones[0].bleedMm 必須是有限數值"


def test_bleed_zero_mm_is_result_not_422(client: TestClient) -> None:
    res = client.post(
        "/api/packaging/v2/bleed/validate",
        json={"zones": [{"name": "main", "bleedMm": 0, "safeMm": 0}]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "bleed:main" in body["errors"]
    assert "safe:main" in body["errors"]


def test_bleed_null_mm_is_result_not_422(client: TestClient) -> None:
    res = client.post(
        "/api/packaging/v2/bleed/validate",
        json={"zones": [{"name": "main", "bleedMm": None, "safeMm": None}]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "bleed:main" in body["errors"]
    assert "safe:main" in body["errors"]


def test_bleed_zone_count_limit(client: TestClient) -> None:
    zone = {"name": "main", "bleedMm": 3, "safeMm": 5}
    ok = client.post("/api/packaging/v2/bleed/validate", json={"zones": [dict(zone) for _ in range(64)]})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True
    over = client.post("/api/packaging/v2/bleed/validate", json={"zones": [dict(zone) for _ in range(65)]})
    assert over.status_code == 422
    assert over.json()["detail"] == "zones 最多 64 項"


def test_barcode_zone_happy(client: TestClient) -> None:
    res = client.post("/api/packaging/v2/barcode-zone", json={"panel": {"w": 120, "h": 80}})
    assert res.status_code == 200
    _no_forbidden_labels(res.json())
    assert res.json()["label"] == "PARTIAL"


@pytest.mark.parametrize(
    "panel",
    [
        {"w": 0, "h": 10},
        {"w": 10, "h": -1},
        {"w": "NaN", "h": 10},
        {"w": 6000, "h": 10},
    ],
)
def test_barcode_zone_invalid_panel_422(client: TestClient, panel: dict[str, float]) -> None:
    res = client.post("/api/packaging/v2/barcode-zone", json={"panel": panel})
    assert res.status_code == 422


def test_carton_optimize_happy_and_deterministic(client: TestClient) -> None:
    body = {
        "grade": "KRAFT_C_ECT44",
        "product": {"width": 120, "height": 80, "depth": 40},
        "weightKg": 0.4,
    }
    a = client.post("/api/packaging/v2/carton-optimize", json=body)
    b = client.post("/api/packaging/v2/carton-optimize", json=body)
    assert a.status_code == 200
    assert a.json() == b.json()
    _no_forbidden_labels(a.json())
    assert a.json()["chosen"]["family"]
    assert len(a.json()["candidates"]) >= 1


@pytest.mark.parametrize(
    "product",
    [
        {"width": 0, "height": 80, "depth": 40},
        {"width": 120, "height": "Infinity", "depth": 40},
        {"width": 99999, "height": 80, "depth": 40},
    ],
)
def test_carton_optimize_bad_dims_422(client: TestClient, product: dict[str, float]) -> None:
    res = client.post(
        "/api/packaging/v2/carton-optimize",
        json={"grade": "KRAFT_B_ECT32", "product": product},
    )
    assert res.status_code == 422


def test_unknown_grade_never_500(client: TestClient) -> None:
    for path, body in (
        ("/api/packaging/v2/compression", _good_compression_body() | {"grade": "UNKNOWN_X"}),
        ("/api/packaging/v2/carton-optimize", {"grade": "UNKNOWN_X", "product": {"width": 1, "height": 1, "depth": 1}}),
    ):
        res = client.post(path, json=body)
        assert res.status_code == 422
        assert "KeyError" not in res.text


def test_kd_page_includes_packaging_script(client: TestClient) -> None:
    res = client.get("/admin/kd")
    assert res.status_code == 200
    assert "/admin/pages/assets/kd-packaging.js" in res.text
    assert "包裝工程檢查" in res.text


def test_kd_packaging_asset_served(client: TestClient) -> None:
    res = client.get("/admin/pages/assets/kd-packaging.js")
    assert res.status_code == 200
    assert b"innerHTML" not in res.content


def test_kd_packaging_js_safety() -> None:
    js = (PAGES / "kd-packaging.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js
    assert "textContent" in js
    assert "btn.disabled = true" in js
    assert ".finally(" in js
    assert "網路錯誤" in js