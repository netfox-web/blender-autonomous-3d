"""Additive engineering articulation contract (no Blender or geometry inference).

Trust boundary: callers obtain the binding and component set from a reviewed
engineering/product definition, never from a render request or worker response.
SHA256 is an integrity seal, NOT an approval signature. Publishing a new binding
is an engineering authoring operation; resolution cannot upgrade a legacy product.
Legacy engineering hashes are untouched. Future motion/cache consumers MUST use
the composite productAuthorityHash and bind_articulation_cache_identity().
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


SCHEMA = "ARTICULATION_SPEC_V1"
ROOT_PARENT = "PRODUCT_ROOT"
CONVENTION = "RIGHT_HANDED_AXIS_ANGLE_DEGREES"
ORDER = "PARENT_PIVOT_DELTA_PREMULTIPLY_CLOSED"
SOURCE_KINDS = {
    "FIXTURE_AUTHORITY", "CAD_AUTHORITY", "MEASURED_AUTHORITY",
    "APPROVED_ENGINEERING_AUTHORITY",
}
IDENTITY_KEYS = {"tenantId", "productId", "sku", "productVersion", "engineeringHash"}
ROW_KEYS = {
    "componentId", "objectName", "role", "parentComponentId", "pivotSpace",
    "pivot", "axis", "closedAngleDeg", "openMinDeg", "openMaxDeg", "openAngleDeg",
    "rotationConvention", "rotationOrder", "closedLocalTransform", "openLocalTransform",
}
COMPONENT_KEYS = {"componentId", "objectName", "role", "parentComponentId", "closedLocalTransform"}
BINDING_KEYS = {
    "schema", "identity", "authorityRevision", "articulationAuthorityHash",
    "authorityKind", "componentSetHash", "productAuthorityHash",
}


class AuthorityBlocked(ValueError):
    """Typed fail-closed result; never a partially usable authority."""

    def __init__(self, reason: str):
        self.status = "BLOCKED_ARTICULATION_AUTHORITY"
        self.reason = reason
        super().__init__(f"{self.status}: {reason}")


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise AuthorityBlocked(reason)


def _text(value: Any) -> bool:
    return type(value) is str and bool(value.strip()) and value == value.strip()


def _sha(value: Any) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _keys(value: Any, keys: set[str], reason: str) -> None:
    _require(type(value) is dict and set(value) == keys, reason)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, OverflowError) as exc:
        raise AuthorityBlocked("NON_CANONICAL_JSON") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _identity(identity: Any) -> None:
    _keys(identity, IDENTITY_KEYS, "INVALID_PRODUCT_IDENTITY")
    _require(all(_text(identity[k]) for k in ("tenantId", "productId", "sku")), "BLANK_PRODUCT_IDENTITY")
    _require(type(identity["productVersion"]) is int and identity["productVersion"] > 0,
             "INVALID_PRODUCT_VERSION")
    _require(_sha(identity["engineeringHash"]), "INVALID_ENGINEERING_HASH")


def _matrix(value: Any) -> None:
    _require(type(value) is list and len(value) == 4 and all(
        type(row) is list and len(row) == 4 and all(_number(x) for x in row) for row in value
    ), "INVALID_TRANSFORM")
    _require(value[3] == [0, 0, 0, 1], "NON_AFFINE_TRANSFORM")
    # Rigid, right-handed transforms only; scale/shear require a later contract.
    r = value
    for i in range(3):
        for j in range(3):
            dot = sum(r[k][i] * r[k][j] for k in range(3))
            _require(abs(dot - (1 if i == j else 0)) < 1e-8, "NON_RIGID_TRANSFORM")
    det = (r[0][0] * (r[1][1]*r[2][2]-r[1][2]*r[2][1])
           - r[0][1] * (r[1][0]*r[2][2]-r[1][2]*r[2][0])
           + r[0][2] * (r[1][0]*r[2][1]-r[1][1]*r[2][0]))
    _require(abs(det - 1) < 1e-8, "REFLECTED_TRANSFORM")


def _open_transform(row: dict) -> list[list[float]]:
    # Parent-space hinge rotation relative to the authored closed pose.
    x, y, z = row["axis"]
    a = math.radians(row["openAngleDeg"] - row["closedAngleDeg"])
    c, s, t = math.cos(a), math.sin(a), 1 - math.cos(a)
    r = [[t*x*x+c, t*x*y-s*z, t*x*z+s*y],
         [t*x*y+s*z, t*y*y+c, t*y*z-s*x],
         [t*x*z-s*y, t*y*z+s*x, t*z*z+c]]
    pivot, closed = row["pivot"], row["closedLocalTransform"]
    result = [[sum(r[i][k]*closed[k][j] for k in range(3)) for j in range(3)]
              + [pivot[i] + sum(r[i][k]*(closed[k][3]-pivot[k]) for k in range(3))]
              for i in range(3)]
    return result + [[0.0, 0.0, 0.0, 1.0]]


def _row(row: Any) -> None:
    _keys(row, ROW_KEYS, "INVALID_COMPONENT_AUTHORITY_SCHEMA")
    _require(all(_text(row[k]) for k in ("componentId", "objectName", "parentComponentId")),
             "BLANK_COMPONENT_IDENTITY")
    _require(row["role"] == "door", "NON_DOOR_AUTHORITY")
    _require(row["parentComponentId"] != row["componentId"], "SELF_PARENT")
    _require(row["pivotSpace"] == "PARENT_LOCAL_METRES", "UNSUPPORTED_PIVOT_SPACE")
    _require(row["rotationConvention"] == CONVENTION and row["rotationOrder"] == ORDER,
             "UNSUPPORTED_ROTATION_SEMANTICS")
    for field in ("pivot", "axis"):
        v = row[field]
        _require(type(v) is list and len(v) == 3 and all(_number(x) for x in v), "INVALID_" + field.upper())
    _require(abs(math.hypot(*row["axis"]) - 1) < 1e-10, "AXIS_NOT_NORMALIZED")
    angles = [row[k] for k in ("closedAngleDeg", "openMinDeg", "openMaxDeg", "openAngleDeg")]
    _require(all(_number(x) and abs(x) <= 360 for x in angles), "INVALID_ANGLE")
    closed, low, high, opened = angles
    _require(low <= closed <= high and low <= opened <= high and low < high and opened != closed,
             "INVALID_ANGLE_RANGE")
    _matrix(row["closedLocalTransform"])
    _matrix(row["openLocalTransform"])
    expected = _open_transform(row)
    _require(all(_number(expected[i][j]) and abs(expected[i][j]-row["openLocalTransform"][i][j]) < 1e-8
                 for i in range(4) for j in range(4)), "OPEN_TRANSFORM_CONTRADICTION")


def _normalized_record(record: Any, *, sealed: bool) -> dict:
    keys = {"schema", "identity", "authorityRevision", "authoritySource", "components"}
    if sealed:
        keys.add("authorityHash")
    _keys(record, keys, "NOT_ENGINEERING_AUTHORITY")
    _require(record["schema"] == SCHEMA, "NOT_ENGINEERING_AUTHORITY")
    _identity(record["identity"])
    _require(type(record["authorityRevision"]) is int and record["authorityRevision"] > 0, "INVALID_REVISION")
    source = record["authoritySource"]
    _keys(source, {"kind", "reference", "sourceHash"}, "INVALID_AUTHORITY_SOURCE")
    _require(type(source["kind"]) is str and source["kind"] in SOURCE_KINDS, "UNTRUSTED_SOURCE_KIND")
    _require(_text(source["reference"]) and _sha(source["sourceHash"]), "INVALID_SOURCE_PROVENANCE")
    rows = record["components"]
    _require(type(rows) is list and len(rows) > 0, "MISSING_COMPONENT_AUTHORITY")
    for row in rows:
        _row(row)
    _require(len({r['componentId'] for r in rows}) == len(rows), "DUPLICATE_COMPONENT_AUTHORITY")
    _require(len({r['objectName'] for r in rows}) == len(rows), "DUPLICATE_OBJECT_AUTHORITY")
    # No coupled/nested moving parents in V1; explicit static parent IDs remain valid.
    moving = {r['componentId'] for r in rows}
    _require(all(r['parentComponentId'] not in moving for r in rows), "MOVING_PARENT_UNSUPPORTED")
    result = copy.deepcopy(record)
    result.pop("authorityHash", None)
    result["components"].sort(key=lambda r: r["componentId"])
    # Integers/floats and negative zero in physical quantities have one canonical form.
    for r in result["components"]:
        for k in ("pivot", "axis"):
            r[k] = [0.0 if v == 0 else float(v) for v in r[k]]
        for k in ("closedAngleDeg", "openMinDeg", "openMaxDeg", "openAngleDeg"):
            r[k] = 0.0 if r[k] == 0 else float(r[k])
        for k in ("closedLocalTransform", "openLocalTransform"):
            r[k] = [[0.0 if v == 0 else float(v) for v in line] for line in r[k]]
    return result


def verify_articulation_spec(record: Any) -> dict:
    """Independently validate semantics and recompute seal; return a detached snapshot."""
    normalized = _normalized_record(record, sealed=True)
    seal = _hash(normalized)
    _require(_sha(record["authorityHash"]) and seal == record["authorityHash"], "AUTHORITY_HASH_MISMATCH")
    return {**normalized, "authorityHash": seal}


def seal_articulation_spec(record: Any, *, previous: dict | None = None) -> dict:
    """Explicit engineering authoring only. Never infer fields or auto-upgrade a product.

    Revisions start at 1 and advance exactly once relative to a verified previous
    source. The reviewed product binding pins the current revision during reads.
    """
    normalized = _normalized_record(record, sealed=False)
    if previous is None:
        _require(normalized["authorityRevision"] == 1, "INITIAL_REVISION_MUST_BE_ONE")
    else:
        old = verify_articulation_spec(previous)
        _require(old["identity"] == normalized["identity"], "REVISION_IDENTITY_CHANGED")
        _require(normalized["authorityRevision"] == old["authorityRevision"] + 1, "NON_MONOTONIC_REVISION")
    return {**normalized, "authorityHash": _hash(normalized)}


def load_articulation_source(path: str | Path) -> list[dict]:
    """Load a durable, version-controlled authority set. Duplicate JSON keys block."""
    def unique(pairs: list) -> dict:
        obj = {}
        for k, v in pairs:
            _require(k not in obj, "DUPLICATE_JSON_KEY")
            obj[k] = v
        return obj
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, AuthorityBlocked):
            raise
        raise AuthorityBlocked("SOURCE_UNREADABLE") from exc
    _require(type(value) is list, "INVALID_SOURCE_CONTAINER")
    return [verify_articulation_spec(record) for record in value]


def _components(components: Any) -> list[dict]:
    _require(type(components) is list and bool(components), "MISSING_EXPECTED_COMPONENTS")
    for row in components:
        _keys(row, COMPONENT_KEYS, "INVALID_EXPECTED_COMPONENT")
        _require(all(_text(row[k]) for k in COMPONENT_KEYS - {"closedLocalTransform"}), "BLANK_EXPECTED_COMPONENT")
        _require(row["role"] == "door" and row["componentId"] != ROOT_PARENT,
                 "INVALID_EXPECTED_DOOR")
        _matrix(row["closedLocalTransform"])
    _require(len({r['componentId'] for r in components}) == len(components), "DUPLICATE_EXPECTED_COMPONENT")
    _require(len({r['objectName'] for r in components}) == len(components), "DUPLICATE_EXPECTED_OBJECT")
    result = copy.deepcopy(sorted(components, key=lambda r: r["componentId"]))
    for r in result:
        r['closedLocalTransform'] = [[0.0 if x == 0 else float(x) for x in line]
                                     for line in r['closedLocalTransform']]
    return result


def make_authority_binding(record: dict, components: list[dict]) -> dict:
    """Author an explicit product-definition upgrade for review; not a resolver fallback.

    Persist this binding with the product definition. Do not compute it from an
    untrusted candidate at consumption time, or a resealed substitution could pass.
    """
    spec = verify_articulation_spec(record)
    expected = _components(components)
    actual = [{k: r[k] for k in COMPONENT_KEYS} for r in spec["components"]]
    _require(actual == expected, "COMPONENT_SET_MISMATCH")
    b = {"schema": "PRODUCT_ARTICULATION_BINDING_V1", "identity": spec["identity"],
         "authorityRevision": spec["authorityRevision"],
         "articulationAuthorityHash": spec["authorityHash"],
         "authorityKind": spec["authoritySource"]["kind"], "componentSetHash": _hash(expected)}
    return {**b, "productAuthorityHash": _hash(b)}


@dataclass(frozen=True)
class ResolvedArticulation:
    """Immutable verified snapshot. Readiness is logic/source classification only."""

    canonical_source: bytes
    product_authority_hash: str

    def to_dict(self) -> dict:
        return json.loads(self.canonical_source)

    @property
    def authority_kind(self) -> str:
        return self.to_dict()["authoritySource"]["kind"]


def resolve_articulation_authority(
    identity: dict, engineering_identity: dict | None, component_set: list[dict],
    *, records: list[dict], parent_ids: list[str],
) -> ResolvedArticulation:
    """Exact pinned resolution or AuthorityBlocked; no best-match/latest fallback.

    identity, engineering_identity, component_set and parent_ids are independently
    trusted product-definition inputs. records are untrusted source candidates.
    V1 resolves the entire authorized moving-door set, not an arbitrary subset.
    """
    _identity(identity)
    if engineering_identity is None:
        raise AuthorityBlocked("ARTICULATION_AUTHORITY_MISSING")
    b = engineering_identity
    _keys(b, BINDING_KEYS, "INVALID_ENGINEERING_BINDING")
    _identity(b["identity"])
    _require(b["schema"] == "PRODUCT_ARTICULATION_BINDING_V1" and b["identity"] == identity,
             "ENGINEERING_IDENTITY_MISMATCH")
    _require(type(b["authorityRevision"]) is int and b["authorityRevision"] > 0, "INVALID_PINNED_REVISION")
    _require(type(b["authorityKind"]) is str and b["authorityKind"] in SOURCE_KINDS, "INVALID_PINNED_SOURCE_KIND")
    _require(all(_sha(b[k]) for k in ("articulationAuthorityHash", "componentSetHash", "productAuthorityHash")),
             "INVALID_BINDING_HASH")
    _require(b["productAuthorityHash"] == _hash({k: v for k, v in b.items() if k != "productAuthorityHash"}),
             "PRODUCT_AUTHORITY_HASH_MISMATCH")
    expected = _components(component_set)
    _require(_hash(expected) == b["componentSetHash"], "COMPONENT_BINDING_MISMATCH")
    _require(type(parent_ids) is list and bool(parent_ids) and all(_text(v) for v in parent_ids)
             and len(set(parent_ids)) == len(parent_ids), "INVALID_PARENT_SET")
    _require(all(r["parentComponentId"] in parent_ids for r in expected), "UNKNOWN_PARENT")
    _require(type(records) is list, "INVALID_SOURCE_CONTAINER")
    checked = [verify_articulation_spec(r) for r in records]
    matched = [r for r in checked if r["identity"] == identity]
    _require(bool(matched), "ARTICULATION_AUTHORITY_MISSING")
    _require(len(matched) == 1, "AMBIGUOUS_AUTHORITY_SET")
    record = matched[0]
    _require(record["authorityRevision"] == b["authorityRevision"], "STALE_AUTHORITY_REVISION")
    _require(record["authorityHash"] == b["articulationAuthorityHash"], "PINNED_AUTHORITY_HASH_MISMATCH")
    _require(make_authority_binding(record, expected) == b, "AUTHORITY_BINDING_MISMATCH")
    return ResolvedArticulation(_canonical(record), b["productAuthorityHash"])


def bind_articulation_cache_identity(
    base_identity: dict, identity: dict, engineering_identity: dict | None,
    component_set: list[dict], *, records: list[dict], parent_ids: list[str],
) -> dict:
    """Future video/cache boundary: re-resolve then bind ALL caller cache dimensions.

    No API accepts a caller-supplied ready flag or a worker's ResolvedArticulation.
    Existing static/legacy caches are not changed. DOOR_OPEN stays gated in PR13.
    """
    _require(type(base_identity) is dict and bool(base_identity), "EMPTY_CACHE_IDENTITY")
    resolved = resolve_articulation_authority(identity, engineering_identity, component_set,
                                             records=records, parent_ids=parent_ids)
    record = resolved.to_dict()
    payload = {"schema": "ARTICULATED_CACHE_IDENTITY_V1", "baseIdentity": copy.deepcopy(base_identity),
               "identity": record["identity"], "productAuthorityHash": resolved.product_authority_hash,
               "articulationAuthorityHash": record["authorityHash"],
               "authorityRevision": record["authorityRevision"], "authorityKind": resolved.authority_kind}
    return {**payload, "cacheIdentityHash": _hash(payload)}
