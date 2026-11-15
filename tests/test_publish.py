import copy
import json
import struct

import pytest

from fox3d.ids import sha256_bytes
from fox3d.pngutil import write_glb_stub
from fox3d.publish import CatalogRelease, ar_export_boundary, glb_publication, web3d_manifest

_JSON = 0x4E4F534A
_BIN = 0x004E4942
_BLOCKED_GLB = {"ok": False, "label": "BLOCKED", "error": "invalid_glb"}


def _chunk(payload: bytes, chunk_type: int) -> bytes:
    return struct.pack("<II", len(payload), chunk_type) + payload


def _json_chunk(document: object) -> bytes:
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    while len(payload) % 4:
        payload += b" "
    return _chunk(payload, _JSON)


def _glb(*chunks: bytes, version: int = 2, length: int | None = None) -> bytes:
    body = b"".join(chunks)
    total = 12 + len(body) if length is None else length
    return struct.pack("<4sII", b"glTF", version, total) + body


def _minimal_glb(version: str = "2.0") -> bytes:
    return _glb(_json_chunk({"asset": {"version": version}}))


def _with_header_u32(data: bytes, offset: int, value: int) -> bytes:
    raw = bytearray(data)
    struct.pack_into("<I", raw, offset, value)
    return bytes(raw)


def _unaligned_json() -> bytes:
    payload = json.dumps({"asset": {"version": "2.0"}}, separators=(",", ":")).encode("utf-8")
    payload += b" "
    while len(payload) % 4 != 1:
        payload += b" "
    return _glb(_chunk(payload, _JSON))


def _overrun_json() -> bytes:
    chunk = _json_chunk({"asset": {"version": "2.0"}})
    chunk_len, chunk_type = struct.unpack_from("<II", chunk, 0)
    return _glb(struct.pack("<II", chunk_len + 8, chunk_type) + chunk[8:])


def _tab_padded_json() -> bytes:
    payload = json.dumps({"asset": {"version": "2.0"}}, separators=(",", ":")).encode("utf-8")
    while len(payload) % 4:
        payload += b"\t"
    if payload.endswith(b"}"):
        payload += b"\t" * 4
    return _glb(_chunk(payload, _JSON))


def _json_with_bom() -> bytes:
    payload = b"\xef\xbb\xbf" + json.dumps({"asset": {"version": "2.0"}}, separators=(",", ":")).encode("utf-8")
    while len(payload) % 4:
        payload += b" "
    return _glb(_chunk(payload, _JSON))


def _null_padded_json() -> bytes:
    payload = json.dumps({"asset": {"version": "2.0"}}, separators=(",", ":")).encode("utf-8")
    while len(payload) % 4:
        payload += b" "
    payload += b"\x00" * 4
    return _glb(_chunk(payload, _JSON))


def _trailing_incomplete() -> bytes:
    return _with_header_u32(_minimal_glb() + b"\x00\x00\x00\x00", 8, len(_minimal_glb()) + 4)


def _declared_length_short() -> bytes:
    json_chunk = _json_chunk({"asset": {"version": "2.0"}})
    body = json_chunk + _chunk(b"\x00\x01\x02\x03", _BIN)
    return struct.pack("<4sII", b"glTF", 2, 12 + len(json_chunk)) + body


_INVALID_GLB = [
    pytest.param(b"", id="empty"),
    pytest.param(b"glTF", id="magic-only"),
    pytest.param(b"xxxx" + bytes(8), id="bad-magic"),
    pytest.param(b"glTF" + bytes(7), id="truncated-header"),
    pytest.param(struct.pack("<4sII", b"glTF", 99, 999), id="version-99-length-999"),
    pytest.param(struct.pack("<4sII", b"glTF", 2, 12), id="header-only"),
    pytest.param(_glb(_json_chunk({"asset": {"version": "2.0"}}), version=99), id="version-99"),
    pytest.param(_with_header_u32(_minimal_glb(), 8, len(_minimal_glb()) + 99), id="declared-longer"),
    pytest.param(_declared_length_short(), id="declared-shorter"),
    pytest.param(_glb(_chunk(b"\x00\x01\x02\x03", _BIN)), id="bin-before-json"),
    pytest.param(_overrun_json(), id="chunk-overrun"),
    pytest.param(_unaligned_json(), id="unaligned-chunk"),
    pytest.param(_glb(_chunk(b"{" + b" " * 15, _JSON)), id="invalid-json"),
    pytest.param(_glb(_json_chunk({"scenes": []})), id="missing-asset"),
    pytest.param(_glb(_json_chunk({"asset": "2.0"})), id="asset-not-object"),
    pytest.param(_glb(_json_chunk({"asset": {}})), id="missing-asset-version"),
    pytest.param(_glb(_json_chunk({"asset": {"version": ""}})), id="empty-asset-version"),
    pytest.param(_glb(_json_chunk({"asset": {"version": "1.0"}})), id="asset-version-1"),
    pytest.param(_glb(_json_chunk({"asset": {"version": 2}})), id="asset-version-number"),
    pytest.param(_glb(_json_chunk([{"asset": {"version": "2.0"}}])), id="json-array"),
    pytest.param(
        _glb(_json_chunk({"asset": {"version": "2.0"}}), _json_chunk({"asset": {"version": "2.0"}})),
        id="second-json",
    ),
    pytest.param(
        _glb(_json_chunk({"asset": {"version": "2.0"}}), _chunk(b"EXT1", 1), _chunk(b"\x00\x01\x02\x03", _BIN)),
        id="bin-not-second",
    ),
    pytest.param(_trailing_incomplete(), id="trailing-incomplete-chunk"),
    pytest.param(_tab_padded_json(), id="tab-padding"),
    pytest.param(_null_padded_json(), id="null-padding"),
    pytest.param(_json_with_bom(), id="json-bom"),
]


def _assert_real(path, content: bytes, dimensions: dict) -> None:
    path.write_bytes(content)
    result = glb_publication({"dimensions": dimensions}, path)
    assert result["ok"] is True
    assert result["label"] == "REAL"
    assert result["size"] == len(content)
    assert result["hash"] == sha256_bytes(content)
    assert result["path"] == str(path)
    assert result["store"] == "DAM"


def test_glb_publication_valid_and_missing(tmp_path):
    path = tmp_path / "model.glb"
    assert glb_publication({}, path) == {"ok": False, "label": "BLOCKED", "error": "missing_glb"}
    content = _minimal_glb()
    _assert_real(path, content, {"width": 1, "height": 2, "depth": 3})
    assert glb_publication({"dimensions": {"width": 1, "height": 2, "depth": 3}}, path)["dimsValid"] is True


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(_minimal_glb(), id="json-only"),
        pytest.param(_minimal_glb("2"), id="asset-version-2"),
        pytest.param(_minimal_glb("2.1"), id="asset-version-2-1"),
        pytest.param(
            _glb(_json_chunk({"asset": {"version": "2.0"}}), _chunk(b"\x00\x01\x02\x03", _BIN)),
            id="json-bin",
        ),
        pytest.param(_glb(_json_chunk({"asset": {"version": "2.0"}}), _chunk(b"EXT1", 1)), id="json-unknown"),
        pytest.param(
            _glb(
                _json_chunk({"asset": {"version": "2.0"}}),
                _chunk(b"\x00\x01\x02\x03", _BIN),
                _chunk(b"EXT1", 1),
            ),
            id="json-bin-unknown",
        ),
    ],
)
def test_readable_glb_is_real(tmp_path, content):
    _assert_real(tmp_path / "model.glb", content, {"width": 1, "height": 1, "depth": 1})


def test_directory_path_is_blocked(tmp_path):
    path = tmp_path / "model.glb"
    path.mkdir()
    assert glb_publication({"dimensions": {"width": 1, "height": 2, "depth": 3}}, path) == _BLOCKED_GLB


def test_project_glb_stub_is_real(tmp_path):
    path = tmp_path / "model.glb"
    write_glb_stub(path, name="Chair")
    _assert_real(path, path.read_bytes(), {"width": 1, "height": 1, "depth": 1})


@pytest.mark.parametrize("content", _INVALID_GLB)
def test_invalid_glb_is_blocked(tmp_path, content):
    path = tmp_path / "model.glb"
    path.write_bytes(content)
    assert glb_publication({"dimensions": {"width": 1, "height": 2, "depth": 3}}, path) == _BLOCKED_GLB


@pytest.mark.parametrize("dimensions", [
    {}, {"width": 1, "height": 2}, {"width": 0, "height": 2, "depth": 3},
    {"width": -1, "height": 2, "depth": 3}, {"width": float("nan"), "height": 2, "depth": 3},
    {"width": float("inf"), "height": 2, "depth": 3}, {"width": "1", "height": 2, "depth": 3},
    {"width": True, "height": 2, "depth": 3},
])
def test_invalid_dimensions(tmp_path, dimensions):
    path = tmp_path / "model.glb"
    path.write_bytes(_minimal_glb())
    result = glb_publication({"dimensions": dimensions}, path)
    assert result["ok"] is True and result["label"] == "REAL"
    assert result["dimsValid"] is False


def _catalog_state(catalog: CatalogRelease) -> tuple[dict, dict]:
    return copy.deepcopy(catalog.releases), copy.deepcopy(catalog.skus)


def test_catalog_integrity():
    catalog = CatalogRelease()
    sku = catalog.add_sku({"productId": "sku", "engineeringHash": "hash"}, family="chair")
    assert catalog.add_sku({"productId": "sku", "engineeringHash": "hash"}, family="chair") == sku
    with pytest.raises(ValueError):
        catalog.add_sku({"productId": "sku", "engineeringHash": "other"}, family="chair")
    assert catalog.skus["sku"] == sku
    with pytest.raises(KeyError):
        catalog.release(name="bad", sku_ids=["sku", "unknown"])
    assert not catalog.releases
    first = catalog.release(name="first", sku_ids=["sku"])
    second = catalog.release(name="second", sku_ids=["sku"])
    before = _catalog_state(catalog)
    with pytest.raises(KeyError):
        catalog.supersede(first["releaseId"], successor="unknown")
    assert _catalog_state(catalog) == before
    assert first["status"] == "active" and first["supersededBy"] is None and "stale" not in first
    catalog.supersede(first["releaseId"], successor=second["releaseId"])
    assert first["status"] == "superseded" and first["supersededBy"] == second["releaseId"]
    assert first["stale"] is True and second["status"] == "active"
    before = _catalog_state(catalog)
    with pytest.raises(ValueError, match="is already superseded"):
        catalog.supersede(first["releaseId"], successor=second["releaseId"])
    assert _catalog_state(catalog) == before


def test_supersede_rejects_self_and_cycles():
    catalog = CatalogRelease()
    catalog.add_sku({"productId": "sku", "engineeringHash": "hash"}, family="chair")
    first = catalog.release(name="first", sku_ids=["sku"])
    second = catalog.release(name="second", sku_ids=["sku"])
    third = catalog.release(name="third", sku_ids=["sku"])

    before = _catalog_state(catalog)
    with pytest.raises(ValueError, match="cannot supersede itself"):
        catalog.supersede(first["releaseId"], successor=first["releaseId"])
    assert _catalog_state(catalog) == before
    assert first["status"] == "active" and first["supersededBy"] is None and "stale" not in first

    with pytest.raises(KeyError):
        catalog.supersede(third["releaseId"], successor="")
    with pytest.raises(KeyError):
        catalog.supersede("missing", successor=third["releaseId"])
    assert _catalog_state(catalog) == before

    catalog.supersede(first["releaseId"], successor=second["releaseId"])
    assert first["supersededBy"] == second["releaseId"] and first["stale"] is True
    assert second["status"] == "active" and second["supersededBy"] is None and "stale" not in second

    before = _catalog_state(catalog)
    with pytest.raises(ValueError, match=r"Successor .+ is already superseded"):
        catalog.supersede(second["releaseId"], successor=first["releaseId"])
    assert _catalog_state(catalog) == before

    with pytest.raises(ValueError, match=r"Successor .+ is already superseded"):
        catalog.supersede(third["releaseId"], successor=first["releaseId"])
    assert _catalog_state(catalog) == before

    catalog.supersede(second["releaseId"], successor=third["releaseId"])
    assert second["status"] == "superseded" and second["supersededBy"] == third["releaseId"]
    assert first["supersededBy"] == second["releaseId"]
    assert third["status"] == "active" and third["supersededBy"] is None

    before = _catalog_state(catalog)
    with pytest.raises(ValueError, match=r"Successor .+ is already superseded"):
        catalog.supersede(third["releaseId"], successor=second["releaseId"])
    assert _catalog_state(catalog) == before
    with pytest.raises(ValueError, match=r"Successor .+ is already superseded"):
        catalog.supersede(third["releaseId"], successor=first["releaseId"])
    assert _catalog_state(catalog) == before
    with pytest.raises(ValueError, match="cannot supersede itself"):
        catalog.supersede(third["releaseId"], successor=third["releaseId"])
    assert _catalog_state(catalog) == before

    before = _catalog_state(catalog)
    with pytest.raises(ValueError, match="is already superseded"):
        catalog.supersede(first["releaseId"], successor=first["releaseId"])
    assert _catalog_state(catalog) == before
    assert first["supersededBy"] == second["releaseId"] and first["stale"] is True


def test_manifest_and_ar_boundary(tmp_path):
    manifest = web3d_manifest(twin={"dimensions": {"width": 1}}, glb=None)
    assert manifest["glbRef"] is None and manifest["glbHash"] is None
    assert manifest["arRuntime"] == "PARTIAL"
    for result in (None, {"usdz": str(tmp_path / "missing.usdz")}):
        boundary = ar_export_boundary(result)
        assert boundary["label"] == "PARTIAL" and boundary["usdzProduced"] is False
        assert "artifact" not in boundary and "usdz" not in boundary
    path = tmp_path / "model.usdz"
    path.write_bytes(b"fixture")
    assert ar_export_boundary({"usdz": str(path)}) == {"label": "REAL", "artifact": str(path)}
    assert web3d_manifest(twin={}, glb={"path": "model.glb", "hash": "hash"}, variants=["red"])["variantIds"] == ["red"]
