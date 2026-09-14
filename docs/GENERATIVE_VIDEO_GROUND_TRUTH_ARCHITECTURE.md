# Generative Video Ground Truth V1

Issue #6 adds a provider-neutral video control layer to existing main. It reuses CabinetSpec, Artwork Placement, Product Truth Render Pack, Platform submission/execution, Scheduler/Queue, BlenderRuntime and DAM. PR #7–#12 are not dependencies and remain unmerged. No existing core was rewritten.

## Authority and recipes

`video_recipe.py` defines HERO_ORBIT_8S, ARTWORK_DETAIL_6S and SMALL_ROOM_10S deterministic plans; DOOR_OPEN_8S and ASSEMBLY_EXPLODE_10S fail closed because current main has no independent hinge/assembly authority. A guessed pivot, axis, component name or ready flag cannot enable animation.

Recipes bind duration, integer fps/resolution/frame count, camera optics/sensor/clipping/look-at, smoothstep angle/dolly keyframes, static product transform timeline, articulation timeline, exact lighting/world/room policy and Camera/Scene/Video hashes. Numeric bool/string/NaN/Inf coercion and hash/body contradictions are rejected. Frame indices start at zero; timestamp is index/fps; the final sampled camera key is (frameCount−1)/fps and its pose holds through the last frame interval.

`freeze_authority` independently resolves the canonical source placement, artwork bytes and CabinetSpec engineering identity from existing stores, validates the Product Truth pack, and freezes input before any video worker runs. It binds tenant, SKU/product ID/version, Product Truth pack hash/generation, EngineeringHash, Artwork ID/hash/version/SHA, PlacementHash, surface/component/object identity and finalUvHash. Explicit fixture geometry is frozen before its engineering hash is calculated.

Host geometry expectations are independently re-derived from the frozen engineering input through the existing main geometry interpreter using a data-only box sink. Worker output never supplies the expected matrices or identities. The real worker observes camera/object matrices, dimensions/topology, applied artwork, actual optics and world/lights, and reopens its saved BLEND at first/middle/last keyed frames.

## Outputs and persisted validation

`blender_video_job.py` is a narrow BlenderRuntime worker, reusing the existing cabinet/artwork/compositor helpers. One execution path produces Beauty PNG, linear metre Depth float32 EXR, world-space XYZ Normal float32 EXR, ProductMask PNG, ArtworkMask PNG and Alpha PNG per frame. Control passes use Raw color management; exposure affects beauty only. ArtworkMask uses the actual FRONT face artwork material index and scene occlusion; it is never an alias for ProductMask. The worker decodes EXRs, checks finite values and records size/channel/range observations. The host checks image dimensions, hashes/bytes, distinct role paths and artwork-mask containment.

Frame artifacts are ingested through existing DAM into `video_ground_truth` with tenant, job, frame, role and full identity metadata. Existing Platform also records its normal job/output lineage. A controller receipt seals the observed frames and DAM descriptors before the final manifest is written. `VIDEO_GROUND_TRUTH_MANIFEST.json` contains every frame timestamp, matrix, object/articulation observation and artifact path/SHA/size/DAM lineage plus instruction/CODE/generation identity and deterministic manifest hash.

`reopen_sequence` requires externally held authority and receipt hashes; a manifest cannot supply its own expected values. Reload independently checks recipe semantics, frozen geometry, observation identities, frame order/count/timestamps, matrices, bytes and persisted DAM descriptors. In-process validation additionally checks the live DAM index. The existing local DAM index is in memory; after process restart persisted sealed descriptors and actual DAM bytes are checked without rewriting that core. These are trusted local-controller hash anchors, not digital signatures or an OS security boundary.

## Provider / QA / retries

`H3MaxAdapter`, `LTX25Adapter` and the future adapter contract build packages only from a verified persisted sequence, including all frame controls, camera metadata, style brief and product-lock constraints. Submit returns BLOCKED_PROVIDER_RUNTIME with networkExecuted=false. No credential/runtime/provider success is fabricated.

`qa_candidate` performs deterministic pixel/metadata proxies: silhouette/artwork IoU, bounds drift, component metadata equality, panel-edge agreement, artwork-region pixel difference, camera/timestamp consistency and temporal brightness-residual change. Results are PASS, RETRY or REJECT. These proxies cannot prove hidden topology, physical dimensions or semantic logo fidelity. Provider control images are evidence, not independent Vision observations. visionQaReady=false and humanReviewRequired=true always.

`VideoCandidateStore` revalidates the trusted sequence, stores provider/model/modelVersion/seed/config and immutable attempts with idempotency keys, retry limits/reasons, SHA/bytes and QA evidence in existing DAM (`video_provider_candidate`, `video_qa_accepted`, `video_qa_rejected`). Accepted lineage cannot be overwritten. Preview publication rechecks sealed QA and candidate bytes; REJECT/RETRY cannot publish. Final Commerce Video remains BLOCKED without live provider evidence and final review. Current candidate execution evidence is explicitly FIXTURE_COPY, never a generated provider result.

## Execution and limits

Run `python scripts/run_video_ground_truth_e2e.py --instruction-sha <actual instruction commit> --expected-commit <clean CODE SHA>` only after that CODE's exact Ubuntu/Windows CI succeeds. The runner verifies actual git instruction/CODE identity and clean state before and after execution. Raw evidence is isolated under `.fox3d-work/video-e2e/<generation>/`; historical acceptance files are untouched. `--allow-dirty` is development-only and cannot promote video readiness.

Required REAL scope is HERO_ORBIT_8S at 128×128, 12 fps, 96 frames. This is a small ground-truth control preview, not commerce-quality video, print proof or physical validation. DETAIL and SMALL_ROOM have deterministic plans/worker paths but no dedicated REAL acceptance in this handoff. No video UI was added; the existing local model workbench remains on its separate user branch.
