# Articulation Engineering Authority Source V1 — Round 3A

Instruction: `4fb4f14a36e505255479397b905d18de13e1da8a`.

The missing upstream engineering authority now has an additive schema, durable source, independent verifier, exact resolver and explicit product-definition binding. There is no new physical articulation evidence. PR #13 DOOR_OPEN remains on hold until this prerequisite is reviewed and present on main.

## Contract and trust boundary

`src/fox3d/articulation_authority.py` requires exact tenant/product/SKU/version/engineering identity, unique door/component/object/parent IDs, parent-local metre pivot, normalized axis, finite authorized angles, right-handed axis-angle convention, rigid canonical closed/open local matrices, source kind/reference/digest, revision and seal. V1 rejects nested moving parents, scale/shear, alternate coordinate spaces and rotation conventions.

Closed pose is the authored reference angle. Open transform is independently checked as T(pivot) R(openAngle-closedAngle) T(-pivot) M_closed, in the static parent coordinate frame. The root token PRODUCT_ROOT denotes the product-local identity frame, not an invented Blender object.

The old engineering hash remains byte-for-byte compatible. A separately reviewed product definition pins authorityRevision, articulationAuthorityHash, authorityKind and componentSetHash in a composite productAuthorityHash. Consumers must supply that trusted definition and exact component/parent set. The resolver has no latest-version fallback, cannot upgrade missing legacy bindings, and rejects stale or re-sealed candidates against the pinned definition.

The hash is an integrity seal, not a cryptographic approval signature. Neither the source nor binding should be accepted from arbitrary worker/request data. `seal_articulation_spec` and `make_authority_binding` are explicit engineering-authoring functions, not consumer fallbacks. Revisions start at 1 and advance by one with a verified previous source; publishing the new trusted binding is a separate reviewed engineering change.

`bind_articulation_cache_identity` re-resolves source bytes and binds the complete caller cache identity plus product authority, revision, seal and provenance. This is the additive boundary for a later video consumer; no existing PR13 video path is enabled by this prerequisite.

## Synthetic reference source

Three version-controlled files under `tests/fixtures/articulation` preserve the accepted Round 2 engineering identity and closed geometry. The authoring text supplies explicit fixture pivots, negative-Z axes, 0-degree closed pose, [0,90] ranges and a 60-degree canonical open pose. The four IDs remain door_1..door_4 / DOOR_1..DOOR_4. No motion field is read from worker observations or convenience helpers at runtime.

The fixture contains no measured hardware, collision-clearance or physical print authority. Changing its authority requires a new seal/binding/cache identity. Fixture relabeling is rejected against the original product binding. Other measured/CAD/approved source classifications share the schema; their compatibility tests are not proof of actual physical data.

Legacy build_articulated_state output is DERIVED_RENDER_STATE; worker helper output is OBSERVATION. Their runtime behavior is unchanged, and neither output satisfies the new authority schema. Legacy products remain ARTICULATION_AUTHORITY_MISSING.

## Validation and scope

CODE SHA: `791bf084caa05ad6369ebd1422f0a400e533f44c`. CODE CI: [34917002099](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/34917002099), exact-head Ubuntu and Windows SUCCESS. Each job passed 953 tests (953 passed-dot progress markers in each double-quiet pytest log); Ubuntu job 104216707968, Windows job 104216708120. Full local regression: 953 passed, 1 dependency deprecation warning, 1090.02 seconds. Focused authority tests: 166 passed.

Clean-CODE acceptance generation: `4173c17c-479d-404f-b69a-841ebfa7f2db`, observed `2026-09-15T01:46:46.902924+00:00`, workingTreeClean=true, status=PASS. All 18 adversarial probes passed. Raw results, classifications and CI metadata are preserved in `ARTICULATION_AUTHORITY_ACCEPTANCE.json`.

PR [#14](https://github.com/netfox-web/blender-autonomous-3d/pull/14) targets main directly. This is the separate DOCS/evidence commit; its exact SHA and dual CI run are to be verified and published in the final Issue handoff after this commit is pushed. No DOCS CI success is claimed at document authoring time. The clean-CODE acceptance runner executes REAL_LOGIC checks against FIXTURE_AUTHORITY and records 18 fail-closed probes. No Blender execution is required by the Round 3A instruction; Mock Blender in full regression/CI is regression evidence only.

| Class | Scope |
|---|---|
| REAL | No new physical articulation or Blender render claim |
| REAL_LOGIC | Schema, canonicalization, verifier, exact resolver, product/cache binding, adversarial rejection |
| FIXTURE_AUTHORITY | Explicit synthetic four-door source, not physical truth |
| PARTIAL | Future video integration and measured/CAD engineering imports require separate implementation/acceptance; legacy OPEN is convenience behavior |
| BLOCKED | DOOR_OPEN_REAL, DOOR_OPEN_GROUND_TRUTH_READY, authoritative assembly/exploded motion, live providers, Final Commerce Video, physical machines/print, Supervisor LIVE, globalProductionReady, fullAutonomousFactoryReady |

CODE and DOCS are gated separately. After the exact DOCS CI succeeds, final handoff will report both immutable SHA/run identities to Issue #6 and Issue #1. STOP for Supervisor Re-Gate; no automatic merge or PR13 continuation.

## Consumer example

```python
# These inputs come from the reviewed engineering definition, not a worker/client.
from fox3d.articulation_authority import load_articulation_source, resolve_articulation_authority
resolved = resolve_articulation_authority(
    definition["identity"], definition["articulationBinding"], definition["componentSet"],
    parent_ids=definition["parentIds"], records=load_articulation_source(authority_path),
)
```

A missing binding or invalid source raises `AuthorityBlocked` with status `BLOCKED_ARTICULATION_AUTHORITY` and a specific reason. Authoring APIs are intentionally separate from resolution. No live engineering import or operator-approval UI is added in this prerequisite.
