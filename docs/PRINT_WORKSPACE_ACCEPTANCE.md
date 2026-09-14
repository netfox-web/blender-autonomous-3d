# Artwork / UV print workspace acceptance

The Chinese workbench supports read-only source import, physical-size PDF proof and manual-release packages, and real Blender previews for three doors and a single flat panel. NetFox live integration is not complete. The user reports image imposition works; the inspected PHP proxy backend was unavailable, so the working entry still needs to be matched. The unused job backend is not a prerequisite for the local workbench.

## Evidence

- CODE: `a8a9def4750135ab38e33499fe1c543ad601aacd`.
- CODE Actions: [34825977605](https://github.com/netfox-web/blender-autonomous-3d/actions/runs/34825977605), exact head SHA, Ubuntu and Windows SUCCESS; **849 passed on each OS**. CI uses MOCK/FIXTURE and proves regression logic only.
- Formal local evidence: `de87a0b9-1610-454c-be93-e2dab2f5ea71`, clean CODE, `developmentOnly=false`, status PASS.
- Actual source PDF-compatible AI SHA-256: `c6fa3b337cc1066e7f888c2cd0f728df5cf03dea4775c2595f9de74dbea1598b`. Originals, proof PDFs and images stay local, outside Git.
- THREE_DOOR and FLAT: real Blender 5.2.1 OptiX, HTTP download hashes, stored geometry/observed UV validation, reopened `.blend` packed texture/UV validation, and HTTP service restart PASS.
- PDF MediaBox/TrimBox verified against generated files: about 401 × 286 mm full page / 395 × 280 mm trim after clockwise 90 degrees. Actual physical parts are not measured by this evidence.
- 21 new print tests; 62 focused print + Golden tests. Negative coverage includes path escape, tenant mismatch, invalid numbers, orientation/size rules, missing checks, stale proof/release, and artifact/metadata tampering. Positive human-release tests use synthetic data only.
- Browser verification: created DN067301, selected pages 1/2/6, saved, generated real preview and proof download, searched source inventory and reopened the saved job. No actual human sign-off was fabricated.
- DOCS CI is pending this separate documentation commit. Final exact DOCS SHA/run verification is recorded in the Issue #1 handoff after Actions finishes.

## Truth matrix

| Area | Status | Boundary |
|---|---|---|
| Source files and PDF layout dimensions | REAL | User-provided originals; no physical measurement claim |
| Native PDF output and human release checks | REAL_LOGIC | SHA/size/page/trim validation; synthetic positive release test |
| Three-door / flat Blender render and reopen | REAL | Geometry and packed textures verified from delivered files |
| Cabinet frame, depth, thickness and gaps | PARTIAL | Configured visualization; unverified manufacturing geometry |
| Source inventory | REAL | 4,451 supported files, not 4,451 ready products |
| CI / synthetic human acceptance | FIXTURE | No actual production approval |
| RIP color, white/clear ink, jig/holes | BLOCKED | Requires measured physical setup and test print |
| NetFox live API integration | BLOCKED | Source/API inspected; 5050 backend had no listener, HTTP 000 |
| Machine controls and production readiness | BLOCKED | No machine or hot-folder dispatch |

## Handoff

PR #8 is stacked on PR #7. Supervisor accepted Issue #4 with scope in comment 5660998477; PR #7 is not authorized for automatic merge. Instruction `7f8126144c6d26996b0f91843a4023748e466b79` queues Issue #6 after this active user artwork task. The video implementation must start from main generic Product Truth interfaces and must not copy unmerged Golden Product implementation.

User operations and the inspected NetFox file/API contract are in [PRINT_WORKSPACE.md](PRINT_WORKSPACE.md). Machine-readable evidence is in [PRINT_WORKSPACE_ACCEPTANCE.json](PRINT_WORKSPACE_ACCEPTANCE.json).
