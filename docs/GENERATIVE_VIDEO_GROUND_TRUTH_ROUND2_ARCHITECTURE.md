# Issue #6 Round 2 architecture

Continue PR #13; no stacked PR, no merge authorization, no dependencies on unmerged #7–#12. Existing Scheduler/Queue/DAM/Product Truth/geometry interpreter remain unchanged.

## Durable attempts

Before a retry, idempotent replay or preview publication, every prior journal goes through `_load_attempt`. A separately persisted `.attempt-set.json` references a DAM snapshot of the exact set of keys, sequential numbers, journal byte hashes and QA asset descriptors. Missing, extra, renamed, duplicated, corrupt or unverified journals block further attempts; any verified PASS locks the lineage. Damaged journals are not repaired or overwritten.

QA asset bytes/hash, saved body and required fields are checked. Candidate descriptors bind tenant, kind, path, asset ID, identity, generation, manifest, source Blender job, frame and role. The live DAM index is compared when present; restart verifies saved descriptors and actual bytes. QA is recomputed before publication. Corrupt history cannot create any new candidate/QA/index asset. An interrupted write between journal and index fails closed on the next operation.

This local index/DAM arrangement is not an OS trust boundary or a defense against an actor rewriting/deleting all journals, index anchors and DAM data together. Historical V1 sets without an index are blocked, not silently migrated. Existing generic DAM was not rewritten.

## Independent sequence controls

HERO, ARTWORK_DETAIL and SMALL_ROOM share one frozen source Product Truth pack, engineering geometry and artwork identity. Only camera/scene/video recipes and per-sequence job/generation change. Video recipe and authority hashes enter the existing render cache key, preventing reuse of a different sequence or generation. Worker progress reports each actual render pass as it begins.

Detail target is independently bound to the canonical artwork-bearing object. Room floor/back are SceneRecipe context, separately observed with object index 2 and material index 0, and never included among product parts. An extra context mask per room frame has its own bytes/hash/path/DAM/job lineage; it must be nonempty and disjoint from ProductMask and ArtworkMask. ProductMask remains object index 1 and ArtworkMask material index 8. Room geometry, pass assignments and sampled reopened context are checked against SceneRecipe-derived expectations. Six product controls remain separate from this extra scene-control artifact.

The runner verifies persisted manifests, actual bytes/matrices/masks/EXR/job lineage, first/middle/last BLEND reopen, same product identities across three recipes, and different deterministic HERO/room SceneRecipe hashes. Provider packages remain network-blocked contracts. Deterministic candidate pixel/metadata QA remains a proxy, not semantic Vision or physical authority.
