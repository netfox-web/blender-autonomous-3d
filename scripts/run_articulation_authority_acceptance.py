"""Authority-only REAL_LOGIC acceptance; never invokes Blender or a provider."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fox3d.articulation_authority import (  # noqa: E402
    AuthorityBlocked, bind_articulation_cache_identity, load_articulation_source,
    make_authority_binding, resolve_articulation_authority, seal_articulation_spec,
)
from fox3d.ids import stable_hash  # noqa: E402


def evaluate() -> dict:
    fixture = ROOT / "tests" / "fixtures" / "articulation"
    definition = json.loads((fixture / "round2_product_definition.json").read_text())
    records = load_articulation_source(fixture / "round2_authorities.json")
    context = dict(identity=definition["identity"], engineering_identity=definition["articulationBinding"],
                   component_set=definition["componentSet"], parent_ids=definition["parentIds"], records=records)
    resolved = resolve_articulation_authority(**context)
    assert resolved.authority_kind == "FIXTURE_AUTHORITY"
    e = definition["engineering"]
    assert stable_hash({k: v for k, v in e.items() if k != "productId"}) == context["identity"]["engineeringHash"]
    assert records[0]["authoritySource"]["sourceHash"] == hashlib.sha256((fixture / "round2_authoring.txt").read_bytes()).hexdigest()
    probes = {}

    def blocked(name, c):
        try:
            resolve_articulation_authority(**c)
        except AuthorityBlocked as exc:
            probes[name] = {"passed": True, "status": exc.status, "reason": exc.reason}
        else:
            raise RuntimeError(f"Fail-closed probe unexpectedly resolved: {name}")

    blocked("legacy_missing_binding", {**context, "engineering_identity": None})
    blocked("missing_source", {**context, "records": []})
    blocked("duplicate_source", {**context, "records": records * 2})
    for key in ("tenantId", "productId", "sku", "productVersion", "engineeringHash"):
        c = copy.deepcopy(context)
        c["identity"][key] = 2 if key == "productVersion" else ("0"*64 if key == "engineeringHash" else "OTHER")
        blocked("wrong_" + key, c)
    for key, value in [("pivot", [0,0,0]), ("axis", [0,0,0]), ("openAngleDeg", True),
                       ("authorityRevision", 2), ("authorityHash", "0"*64)]:
        c = copy.deepcopy(context)
        target = c["records"][0] if key.startswith("authority") else c["records"][0]["components"][0]
        target[key] = value
        blocked("tamper_" + key, c)
    blocked("observation_not_authority", {**context, "records": [{"kind": "OBSERVATION", "angleDeg": 75}]})
    blocked("unknown_parent", {**context, "parent_ids": ["UNKNOWN"]})
    c = copy.deepcopy(context); c["records"][0]["components"][0]["openLocalTransform"][0][3] += .02
    blocked("contradictory_open_transform", c)
    old = records[0]; new_input = {k: copy.deepcopy(v) for k, v in old.items() if k != "authorityHash"}
    new_input["authorityRevision"] = 2
    new_input["components"][0]["openMaxDeg"] = 100
    new = seal_articulation_spec(new_input, previous=old)
    blocked("new_revision_old_pin", {**context, "records": [new]})
    new_context = {**context, "records": [new], "engineering_identity": make_authority_binding(new, context["component_set"])}
    blocked("stale_source_new_pin", {**new_context, "records": records})
    base = {"videoRecipe": "DOOR_OPEN_8S", "artworkHash": "fixture-only"}
    cache1 = bind_articulation_cache_identity(base, **context)
    cache2 = bind_articulation_cache_identity(base, **new_context)
    assert cache1["cacheIdentityHash"] != cache2["cacheIdentityHash"]
    return {
        "status": "PASS", "evidenceClass": "REAL_LOGIC + FIXTURE_AUTHORITY",
        "identity": context["identity"], "authorityHash": old["authorityHash"],
        "authorityRevision": 1, "productAuthorityHash": resolved.product_authority_hash,
        "fixtureSourceHash": old["authoritySource"]["sourceHash"],
        "doorComponents": [r["componentId"] for r in old["components"]],
        "adversarialProbeCount": len(probes), "adversarialProbes": probes,
        "revisionChangesCacheIdentity": True, "cacheIdentities": [cache1["cacheIdentityHash"], cache2["cacheIdentityHash"]],
        "articulationAuthorityLogicReady": True, "fixtureAuthorityReady": True,
        "realBlender": False, "blenderInvoked": False, "physicalArticulationTruth": False,
        "doorOpenReal": False, "doorOpenGroundTruthReady": False, "liveProviderReady": False,
        "globalProductionReady": False, "fullAutonomousFactoryReady": False,
        "limits": ["Synthetic authority is not measured hardware truth.",
                   "Binding must come from a trusted reviewed product definition, not the candidate.",
                   "Integrity hash is not an approval signature.",
                   "Future video integration and REAL DOOR_OPEN acceptance remain gated."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--instruction-sha", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.instruction_sha):
        parser.error("instruction SHA must be an exact 40-character commit")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if dirty:
        raise RuntimeError("Acceptance requires clean exact CODE checkout")
    result = evaluate()
    result.update(generationId=str(uuid.uuid4()), observedAt=datetime.now(timezone.utc).isoformat(),
                  instructionSha=args.instruction_sha, codeSha=head, workingTreeClean=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "adversarialProbes"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
