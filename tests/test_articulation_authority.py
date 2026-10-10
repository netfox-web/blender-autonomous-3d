from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

import pytest

from fox3d.articulation_authority import (
    AuthorityBlocked, bind_articulation_cache_identity, load_articulation_source,
    make_authority_binding, resolve_articulation_authority, seal_articulation_spec,
    verify_articulation_spec,
)
from fox3d.content_factory import build_articulated_state, canonical_commerce_recipes
from fox3d.ids import stable_hash

FIXTURES = Path(__file__).parent / "fixtures" / "articulation"


@pytest.fixture
def context():
    d = json.loads((FIXTURES / "round2_product_definition.json").read_text())
    return dict(identity=d["identity"], engineering_identity=d["articulationBinding"],
                component_set=d["componentSet"], parent_ids=d["parentIds"],
                records=load_articulation_source(FIXTURES / "round2_authorities.json"))


def resolve(c):
    return resolve_articulation_authority(**c)


def cache(c, base=None):
    return bind_articulation_cache_identity(base or {"recipe": "DOOR_OPEN_8S", "artwork": "A"}, **c)


def unsealed(r):
    return {k: copy.deepcopy(v) for k, v in r.items() if k != "authorityHash"}


def test_valid_exact_fixture_and_source_provenance(context):
    resolved = resolve(context)
    assert resolved.authority_kind == "FIXTURE_AUTHORITY"
    assert len(resolved.to_dict()["components"]) == 4
    src = resolved.to_dict()["authoritySource"]
    assert src["sourceHash"] == hashlib.sha256((FIXTURES / "round2_authoring.txt").read_bytes()).hexdigest()
    assert all(r["openAngleDeg"] == 60 for r in resolved.to_dict()["components"])
    assert not hasattr(resolved, "physicalTruth")


def test_fixture_identity_is_accepted_round2_engineering_not_worker(context):
    d = json.loads((FIXTURES / "round2_product_definition.json").read_text())
    e = d["engineering"]
    assert stable_hash({k: v for k, v in e.items() if k != "productId"}) == context["identity"]["engineeringHash"]
    assert e["productId"] == context["identity"]["productId"]
    assert e["revision"] == context["identity"]["productVersion"]
    doors = {p["partId"]: p for p in e["components"] if p["role"] == "door"}
    assert set(doors) == {r["componentId"] for r in context["component_set"]}
    for row in context["component_set"]:
        part = doors[row["componentId"]]
        assert row["objectName"] == part["partName"]
        assert [row["closedLocalTransform"][i][3] for i in range(3)] == part["location"]


@pytest.mark.parametrize("field", ["tenantId", "productId", "sku", "productVersion", "engineeringHash"])
def test_wrong_consumer_identity(context, field):
    context["identity"][field] = 2 if field == "productVersion" else ("0"*64 if field == "engineeringHash" else "OTHER")
    with pytest.raises(AuthorityBlocked):
        resolve(context)


@pytest.mark.parametrize("field", ["tenantId", "productId", "sku", "productVersion", "engineeringHash"])
def test_resealed_cross_identity_candidate(context, field):
    r = unsealed(context["records"][0])
    r["identity"][field] = 2 if field == "productVersion" else ("0"*64 if field == "engineeringHash" else "OTHER")
    context["records"] = [seal_articulation_spec(r)]
    with pytest.raises(AuthorityBlocked, match="AUTHORITY_MISSING"):
        resolve(context)


@pytest.mark.parametrize("value", [None, "", " ", True, [], {}])
@pytest.mark.parametrize("field", ["tenantId", "productId", "sku", "engineeringHash", "productVersion"])
def test_missing_and_invalid_identity(context, field, value):
    context["identity"][field] = value
    with pytest.raises(AuthorityBlocked):
        resolve(context)


def test_legacy_missing_binding_and_empty_source(context):
    with pytest.raises(AuthorityBlocked, match="MISSING"):
        resolve({**context, "engineering_identity": None})
    with pytest.raises(AuthorityBlocked, match="MISSING"):
        resolve({**context, "records": []})


@pytest.mark.parametrize("kind", ["DERIVED_RENDER_STATE", "OBSERVATION", "VISION", "75.0", None, []])
def test_source_kind_cannot_promote_legacy_or_worker(context, kind):
    r = unsealed(context["records"][0])
    r["authoritySource"]["kind"] = kind
    with pytest.raises(AuthorityBlocked, match="SOURCE_KIND"):
        seal_articulation_spec(r)


def test_actual_legacy_helper_output_is_not_authority(context):
    d = json.loads((FIXTURES / "round2_product_definition.json").read_text())
    legacy = build_articulated_state(d["engineering"], "OPEN")
    assert legacy["articulationAngleDeg"] == 75
    assert canonical_commerce_recipes()["FRONT_OPEN"]["articulationAngleDeg"] == 75
    for candidate in [legacy, {"evidenceKind": "OBSERVATION", "transforms": legacy["transforms"]}]:
        with pytest.raises(AuthorityBlocked, match="NOT_ENGINEERING_AUTHORITY"):
            resolve({**context, "records": [candidate]})


@pytest.mark.parametrize("value", [True, False, None, "1", math.nan, math.inf, -math.inf, 10**400])
@pytest.mark.parametrize("field", ["pivot", "axis", "openAngleDeg", "closedAngleDeg", "openMinDeg", "openMaxDeg"])
def test_non_numeric_or_nonfinite_authority(context, field, value):
    r = unsealed(context["records"][0]); row = r["components"][0]
    if field in ("pivot", "axis"):
        row[field][0] = value
    else:
        row[field] = value
    with pytest.raises(AuthorityBlocked):
        seal_articulation_spec(r)


@pytest.mark.parametrize("field,value", [
    ("axis", [0,0,0]), ("axis", [0,0,2]), ("axis", [0,0,-1.01]),
    ("axis", [0,0]), ("pivot", []), ("pivotSpace", "WORLD"),
    ("rotationConvention", "LEFT_HANDED"), ("rotationOrder", "XYZ"),
    ("openMinDeg", 100), ("openMaxDeg", -1), ("openAngleDeg", 95),
    ("openAngleDeg", 0), ("closedAngleDeg", -5), ("componentId", ""),
    ("objectName", " "), ("parentComponentId", None), ("parentComponentId", "door_1"),
    ("role", "shelf"),
])
def test_invalid_component_semantics(context, field, value):
    r = unsealed(context["records"][0]); r["components"][0][field] = value
    with pytest.raises(AuthorityBlocked):
        seal_articulation_spec(r)


@pytest.mark.parametrize("field", ["componentId", "objectName", "parentComponentId"])
def test_resealed_wrong_component_identity(context, field):
    r = unsealed(context["records"][0]); r["components"][0][field] = "UNKNOWN"
    context["records"] = [seal_articulation_spec(r)]
    with pytest.raises(AuthorityBlocked):
        resolve(context)


@pytest.mark.parametrize("field", ["componentId", "objectName", "parentComponentId", "role"])
def test_expected_component_set_tamper(context, field):
    context["component_set"][0][field] = "UNKNOWN"
    with pytest.raises(AuthorityBlocked):
        resolve(context)


def test_unknown_root_and_nested_moving_parent(context):
    with pytest.raises(AuthorityBlocked, match="UNKNOWN_PARENT"):
        resolve({**context, "parent_ids": ["OTHER_ROOT"]})
    r = unsealed(context["records"][0]); r["components"][0]["parentComponentId"] = "door_2"
    with pytest.raises(AuthorityBlocked, match="MOVING_PARENT_UNSUPPORTED"):
        seal_articulation_spec(r)


@pytest.mark.parametrize("field", ["components", "identity", "authoritySource", "schema"])
def test_missing_schema_fields(context, field):
    del context["records"][0][field]
    with pytest.raises(AuthorityBlocked):
        resolve(context)


def test_duplicate_rows_and_sources(context):
    r = unsealed(context["records"][0]); r["components"].append(copy.deepcopy(r["components"][0]))
    with pytest.raises(AuthorityBlocked, match="DUPLICATE_COMPONENT"):
        seal_articulation_spec(r)
    context["records"] *= 2
    with pytest.raises(AuthorityBlocked, match="AMBIGUOUS"):
        resolve(context)


@pytest.mark.parametrize("field,value", [("authorityRevision", True), ("authorityRevision", 0),
                                        ("authorityRevision", 1.0), ("authorityHash", "a"*64)])
def test_revision_and_hash_tamper(context, field, value):
    context["records"][0][field] = value
    with pytest.raises(AuthorityBlocked):
        resolve(context)


@pytest.mark.parametrize("field", ["pivot", "axis", "openAngleDeg"])
def test_mutation_after_seal(context, field):
    row = context["records"][0]["components"][0]
    if field in ("pivot", "axis"):
        row[field][0] += 0.01
    else:
        row[field] += 1
    with pytest.raises(AuthorityBlocked):
        cache(context)


def test_semantically_valid_mutation_still_invalidates_seal(context):
    context["records"][0]["components"][0]["openMaxDeg"] = 100
    with pytest.raises(AuthorityBlocked, match="HASH_MISMATCH"):
        resolve(context)


def test_revision_advancement_and_stale_pin(context):
    old = context["records"][0]; r = unsealed(old); r["authorityRevision"] = 2
    r["components"][0]["openMaxDeg"] = 100
    new = seal_articulation_spec(r, previous=old)
    with pytest.raises(AuthorityBlocked, match="STALE_AUTHORITY_REVISION"):
        resolve({**context, "records": [new]})
    updated = {**context, "records": [new], "engineering_identity": make_authority_binding(new, context["component_set"])}
    assert cache(updated)["cacheIdentityHash"] != cache(context)["cacheIdentityHash"]
    assert new["identity"]["engineeringHash"] == old["identity"]["engineeringHash"]
    assert updated["engineering_identity"]["productAuthorityHash"] != context["engineering_identity"]["productAuthorityHash"]
    with pytest.raises(AuthorityBlocked, match="STALE_AUTHORITY_REVISION"):
        resolve({**updated, "records": [old]})
    for revision in [1, 3, 0, True]:
        r["authorityRevision"] = revision
        with pytest.raises(AuthorityBlocked):
            seal_articulation_spec(r, previous=old)


def test_resealed_same_revision_substitution_still_blocked(context):
    r = unsealed(context["records"][0]); r["components"][0]["openMaxDeg"] = 100
    with pytest.raises(AuthorityBlocked, match="PINNED_AUTHORITY_HASH_MISMATCH"):
        resolve({**context, "records": [seal_articulation_spec(r)]})


@pytest.mark.parametrize("field", ["closedLocalTransform", "openLocalTransform"])
@pytest.mark.parametrize("mutation", ["scale", "reflect", "affine", "bool", "nan", "ragged"])
def test_invalid_matrices(context, field, mutation):
    r = unsealed(context["records"][0]); m = r["components"][0][field]
    if mutation == "scale": m[0][0] = 2
    if mutation == "reflect": m[2][2] = -1
    if mutation == "affine": m[3][0] = 1
    if mutation == "bool": m[0][0] = True
    if mutation == "nan": m[0][3] = math.nan
    if mutation == "ragged": m.pop()
    with pytest.raises(AuthorityBlocked): seal_articulation_spec(r)


def test_forged_rigid_open_transform(context):
    r = unsealed(context["records"][0]); r["components"][0]["openLocalTransform"][0][3] += .01
    with pytest.raises(AuthorityBlocked, match="OPEN_TRANSFORM_CONTRADICTION"):
        seal_articulation_spec(r)


def test_general_axis_and_nonzero_closed_angle_have_independent_analytic_oracle(context):
    r = unsealed(context["records"][0]); row = r["components"][0]
    # 120 degrees about (1,1,1) cycles x -> y -> z. This oracle doesn't call module math.
    row.update(axis=[1/math.sqrt(3)]*3, pivot=[1,2,3], closedAngleDeg=10,
               openMinDeg=0, openMaxDeg=180, openAngleDeg=130,
               closedLocalTransform=[[1,0,0,2],[0,1,0,2],[0,0,1,3],[0,0,0,1]],
               openLocalTransform=[[0,0,1,1],[1,0,0,3],[0,1,0,3],[0,0,0,1]])
    assert verify_articulation_spec(seal_articulation_spec(r))["components"][0]["openAngleDeg"] == 130


def test_canonical_order_and_numeric_representation(context):
    r = unsealed(context["records"][0]); r["components"].reverse()
    for row in r["components"]:
        row["axis"] = [0, -0.0, -1]
        row["closedAngleDeg"] = 0
    assert seal_articulation_spec(r)["authorityHash"] == context["records"][0]["authorityHash"]


def test_snapshot_is_detached_and_cache_reresolves(context):
    resolved = resolve(context); detached = resolved.to_dict(); detached["components"].clear()
    assert len(resolved.to_dict()["components"]) == 4
    context["records"][0]["authorityHash"] = "0"*64
    with pytest.raises(AuthorityBlocked): cache(context)


def test_cache_preserves_all_dimensions_and_provenance(context):
    a = cache(context); b = cache(context, {"recipe": "DOOR_OPEN_8S", "artwork": "B"})
    assert a["cacheIdentityHash"] != b["cacheIdentityHash"]
    assert a["authorityKind"] == "FIXTURE_AUTHORITY"
    assert a["articulationAuthorityHash"] == context["records"][0]["authorityHash"]


def test_fixture_cannot_promote_to_physical_by_flag_or_relabel(context):
    r = unsealed(context["records"][0]); r["physicalTruth"] = True
    with pytest.raises(AuthorityBlocked): seal_articulation_spec(r)
    r.pop("physicalTruth"); r["authoritySource"]["kind"] = "MEASURED_AUTHORITY"
    candidate = seal_articulation_spec(r)
    with pytest.raises(AuthorityBlocked): resolve({**context, "records": [candidate]})


@pytest.mark.parametrize("kind", ["CAD_AUTHORITY", "MEASURED_AUTHORITY", "APPROVED_ENGINEERING_AUTHORITY"])
def test_future_source_kinds_accept_same_contract_only_after_explicit_rebinding(context, kind):
    # Schema compatibility only, not real CAD/measurement evidence.
    r = unsealed(context["records"][0]); r["authoritySource"]["kind"] = kind
    r["authoritySource"]["reference"] = "test-only schema compatibility"
    candidate = seal_articulation_spec(r)
    context.update(records=[candidate], engineering_identity=make_authority_binding(candidate, context["component_set"]))
    assert resolve(context).authority_kind == kind


@pytest.mark.parametrize("body", ['[{"schema":"a","schema":"b"}]', '[NaN]', '{}', '{', '[null]'])
def test_durable_source_malformed_or_duplicate_json_blocks(tmp_path, body):
    p = tmp_path / "bad.json"; p.write_text(body)
    with pytest.raises(AuthorityBlocked): load_articulation_source(p)


def test_missing_source_blocks(tmp_path):
    with pytest.raises(AuthorityBlocked): load_articulation_source(tmp_path / "missing.json")
