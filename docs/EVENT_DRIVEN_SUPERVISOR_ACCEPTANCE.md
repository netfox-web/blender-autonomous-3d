# Event-Driven Autonomous Supervisor Acceptance Report

**Repo**: `netfox-web/blender-autonomous-3d`  
**Date**: 2026-09-14  
**Implementation**: Event-Driven Autonomous Supervisor Control Plane V1 (`services/supervisor/`) — Re-Gate Round 6 Blocker Corrections  
**Phase 1 CODE Commit**: `2bc44acdd985b5d29ac3a1a3a40fa63d21fc244f`  
**CODE Actions Run ID**: `34783581901` — **Ubuntu + Windows DUAL-PLATFORM SUCCESS**  
- `unit (ubuntu-latest)`: `103794888701` (20m 42s)  
- `unit (windows-latest)`: `103794888628` (16m 00s)  
**Test Suite**: `tests/test_supervisor.py` (64 passed, 100% green)  
**Full Regression Suite**: 762 passed (100% green)  
**Clean-Tree E2E Evidence Run**: `generation: 50a84d04-85c2-429d-8c12-641006ac95f1`  

---

## 1. Truth Boundaries & Readiness Declarations

> [!IMPORTANT]
> In strict accordance with Specification Section 18:
> - **`eventDrivenSupervisorReady=false`**
> - **`webhookRealE2e=false`**
> - **`liveProviderReady=false`**
> - Production readiness is **HELD** until verified by a live end-to-end GitHub Webhook delivery triggering live Re-Gate execution. Mock and local integration tests do not constitute production readiness.
> - Prior Phase 901–960 Product Content Round 2 blockers remain open; Phase 961+ remains **HOLD**.
> - Truth boundaries remain: `liveFactoryExecutionReady=false`, `fullAutonomousFactoryReady=false`, `commercialAssetProductionReady=false`, `physicalPrintValidated=false`, `liveMachineControl=false`.

---

## 2. Re-Gate Round 6 Blockers Resolution Summary

### Blocker A — Window B1 Exact Lineage Recovery & Digest Authority
- **Unconditional 6-Trailer Enforcement**: `_verify_instruction_candidate()` unconditionally requires exact match on all 6 trailers (`Reviewed-Code-Sha`, `Reviewed-Docs-Sha`, `Reviewed-Instruction-Sha`, `Reviewed-Evidence-Id`, `Supervisor-Decision`, `Supervisor-Review-Id`). All short-SHA fallbacks and optional trailer checks have been removed; missing any trailer fails closed.
- **Fail-Closed Remote Blob Read**: Remote `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md` blob retrieval fails closed on any exception, 404, or empty content (`except: pass` eliminated).
- **Exact Remote Blob Identity Marker**: Candidate remote blob must contain the complete 6-identity marker (`CODE_SHA`, `DOCS_SHA`, `INSTRUCTION_SHA`, `EVIDENCE_GENERATION_ID`, `DECISION`, `REVIEW_ID`).
- **Durable Pre-Write Content Digest Authority**: The full SHA256 digest of intended instruction content is durably persisted in SQLite `reviews.intended_instruction_sha256` before write; candidate adoption strictly asserts `blob_digest == intended_digest`.
- **Durable Staged Commit Verification**: Commits stored in SQLite `staged_commit_sha` are re-verified through `_verify_instruction_candidate()` before adoption.
- **Review ID Continuity in Recovery**: `SupervisorEngine` reuses the existing `review_id` across crashes for the same contract `(code_sha, evidence_generation_id)` to maintain unbroken trailer and blob marker identity.

### Blocker B — REAL Blender Mandatory Acceptance Evidence vs Product Truth Fallback Rejection
- **Mandatory REAL_E2E Acceptance**: When `real_blender=true and not used_mock`, `docs/REAL_E2E_ACCEPTANCE.md @ DOCS_SHA` is strictly mandatory. If missing (404), empty, timed out, or fetching fails, the engine immediately halts with `CHANGES_REQUIRED` before calling the AI provider.
- **No Acceptance Fallback**: `docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.md` is strictly auxiliary and cannot substitute for the mandatory Real Blender acceptance report.
- **Distinct Evidence Tracking**: Fetch statuses for both `docs/REAL_E2E_ACCEPTANCE.md` and `docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.md` are recorded distinctly in `fetch_statuses` and provider prompt sections.

### Blocker C — Independent Authoritative Changed-Files & Split Diff Ranges
- **Independent Git Authority**: `GitHubClientInterface.get_changed_files_between()` queries `git diff --name-status` (with GitHub compare API fallback) to provide independent authoritative changed files. Manifest paths and diff items are validated against this external authority rather than self-comparison.
- **Manifest Tamper & Spoof Detection**: Compares manifest items against authoritative changes; fails closed on omitted files, phantom files, status spoofing (`M` vs `A`/`D`/`R`), or rename old/new path mismatches.
- **Split Diff Ranges with Exact Provenance**: Prompt splits diff evidence into two distinct bounded sections:
  - **`CODE DIFF`**: ref range `INSTRUCTION_SHA..CODE_SHA`, tracked under `path="git diff"`
  - **`DOCS DIFF`**: ref range `CODE_SHA..DOCS_SHA`, tracked under `path="git diff DOCS"`
- **Diff Contamination Prevention**: Prevents files from the DOCS commit from appearing in the CODE diff; fails closed if contaminated. Each section maintains independent SHA256 digest and completeness tracking.

### Blocker D — Strict DOCS_CI_RUN_ID Parser Boundary & Provider Request ID Audit
- **Parser Boundary Validation**: `ReadyForReGateContract.validate_strict(is_live=True)` and `parse_from_text(..., strict=True)` unconditionally require `DOCS_CI_RUN_ID` to be present and a positive integer before any GitHub API calls. Legacy `CI_RUN_ID` is disallowed from substituting for `DOCS_CI_RUN_ID` in strict mode.
- **Structured Provider Request ID Capture**: `_call_provider_endpoint` returns a structured tuple `(raw_text, provider_request_id)` capturing the provider's request/message ID:
  - OpenAI: `data.get("id")`
  - Anthropic: `data.get("id")`
  - Gemini: `data.get("responseId")` or `data.get("id")`
  - Returns `None` explicitly if not returned by provider (never forged).
- **Comprehensive Audit Trail**: Records `provider`, `model`, `provider_request_id`, `review_id`, `reviewed_code_sha`, `reviewed_docs_sha`, `reviewed_instruction_sha`, `reviewed_evidence_generation_id`, and `timestamp`. Strictly suppresses API keys and Authorization headers.

---

## 3. Comprehensive Verification Matrix (64 Scenarios)

| # | Test Scenario | Verified Behavior | Verdict |
|---|---|---|---|
| 1 | **Invalid webhook signature rejected** | `POST /webhooks/github` without valid `X-Hub-Signature-256` returns HTTP 401. | ✅ PASS |
| 2 | **Duplicate delivery deduplication** | Webhook with identical `X-GitHub-Delivery` ID is acknowledged without reprocessing (`IGNORED_DUPLICATE_DELIVERY`). | ✅ PASS |
| 3 | **Duplicate READY contract idempotent** | Duplicate contract with identical `CODE_SHA` and `EVIDENCE_GENERATION_ID` returns idempotent status. | ✅ PASS |
| 4 | **Wrong repository rejected** | Contracts specifying wrong repo return `REJECTED`. | ✅ PASS |
| 5 | **Wrong issue rejected** | Contracts posted to issues other than Issue #1 return `REJECTED`. | ✅ PASS |
| 6 | **CI pending waits** | CI run in progress raises verification error and refuses progression. | ✅ PASS |
| 7 | **CI failure blocks** | CI run conclusion failure raises verification error and rejects progression. | ✅ PASS |
| 8 | **CODE SHA not on main rejected** | Commits not reachable from `main` fail verification closed. | ✅ PASS |
| 9 | **DOCS SHA not on main rejected** | Unmerged documentation commits fail verification closed. | ✅ PASS |
| 10 | **ACCEPT with scope -> single commit** | Advances phase with instruction commit and posts `SUPERVISOR_REVIEW_COMPLETE`. | ✅ PASS |
| 11 | **CHANGES REQUIRED -> correction only** | Updates instruction file for correction-only without advancing phase. | ✅ PASS |
| 12 | **BLOCKED guardrail -> human approval** | Physical machinery instructions (`LIVE_CNC`, `LIVE_LASER`, `PLC`) trigger `BLOCKED` verdict. | ✅ PASS |
| 13 | **Supervisor own commit -> no loop** | Push events from supervisor instruction commits do not trigger recursive review. | ✅ PASS |
| 14 | **Supervisor own issue comment -> no loop** | Comments posted by supervisor are ignored (`IGNORED_SUPERVISOR_OWN_COMMENT`). | ✅ PASS |
| 15 | **Concurrent READY contracts serialized** | Second contract during active review is serialized safely. | ✅ PASS |
| 16 | **Crash during review resumes safely** | Interrupted reviews transition to `FAILED` and release locks for clean recovery. | ✅ PASS |
| 17 | **Crash before GitHub write retries** | Failures prior to git commit leave contract eligible for retry. | ✅ PASS |
| 18 | **Crash after GitHub write no duplicate** | Completed reviews do not create duplicate commits on subsequent triggers. | ✅ PASS |
| 19 | **Antigravity watcher auto-claim & no duplicate** | Watcher claims new instruction SHA and prevents execution loops. | ✅ PASS |
| 20 | **Blocker A: Outsider commenter rejected (403)** | Comment from non-collaborator returns HTTP 403 Forbidden. | ✅ PASS |
| 21 | **Blocker A: Wrong repo payload ignored** | Webhook payload for other repository returns `IGNORED_WRONG_REPOSITORY`. | ✅ PASS |
| 22 | **Blocker A: Edited/deleted comment ignored** | Comment edits/deletions return `IGNORED_UNSUPPORTED_ACTION`. | ✅ PASS |
| 23 | **Blocker B: Delivery lifecycle & retryable failure** | Delivery transitions through 5-state lifecycle with safe retry. | ✅ PASS |
| 24 | **Blocker B: Push-success/comment-failure recovery** | Recovers using staged commit SHA without duplicate commit. | ✅ PASS |
| 25 | **Blocker C: Live mode push failure fail-closed** | Git push failure raises `GitHubVerificationError` and is never swallowed. | ✅ PASS |
| 26 | **Blocker C: Unauthorized instruction path rejected** | Refuses commits targeting paths outside authorized instructions. | ✅ PASS |
| 27 | **Blocker D: Semantic evidence adversarial rejection** | Rejects contracts claiming REAL when diffs or acceptance indicate mock execution. | ✅ PASS |
| 28 | **Blocker E: Live config fails closed** | Live mode refuses startup if token, secret, or provider are invalid. | ✅ PASS |
| 29 | **Blocker E: Admin auth protects observability** | Endpoints `/supervisor/status` and `/supervisor/reviews` require admin key in live mode. | ✅ PASS |
| 30 | **Blocker A: Missing/null repository envelope fails closed** | Webhook missing `repository` or `full_name` returns HTTP 400 Bad Request. | ✅ PASS |
| 31 | **Blocker A: Live mode requires delivery ID** | Missing `X-GitHub-Delivery` header in live mode returns HTTP 400 Bad Request. | ✅ PASS |
| 32 | **Blocker B: Window B1 remote commit adoption** | Adopts remote instruction commit on crash recovery without duplicate commit. | ✅ PASS |
| 33 | **Blocker B: Window B2 comment marker adoption** | Adopts existing Issue #1 comment with deterministic marker without duplicate comment. | ✅ PASS |
| 34 | **Blocker C: Git preflight rejections** | Rejects dirty tree, staged changes, detached HEAD, and diverged local HEAD. | ✅ PASS |
| 35 | **Blocker D/E: Provider factory & stale lineage rejection** | Factory enforces API keys; stale progress report and empty diff fail closed. | ✅ PASS |
| 36 | **Blocker A: OpenAI provider real HTTP request** | Real HTTP POST dispatched to OpenAI endpoint, response parsed to schema. | ✅ PASS |
| 37 | **Blocker A: Anthropic provider real HTTP request** | Real HTTP POST dispatched to Anthropic messages endpoint, parsed to schema. | ✅ PASS |
| 38 | **Blocker A: Gemini provider real HTTP request** | Real HTTP POST dispatched to Gemini generateContent endpoint, parsed to schema. | ✅ PASS |
| 39 | **Blocker A: Malformed provider JSON fails closed** | Invalid JSON response from provider fails closed with `CHANGES_REQUIRED`. | ✅ PASS |
| 40 | **Blocker A: Provider HTTP 500 error fails closed** | Upstream 5xx error fails closed with `CHANGES_REQUIRED`. | ✅ PASS |
| 41 | **Blocker A: Preflight rejection skips provider** | Safety preflight failure fails closed without calling provider. | ✅ PASS |
| 42 | **Blocker D: Mock promotion to REAL downgraded** | Provider claiming REAL when contract used mock is downgraded to `CHANGES_REQUIRED`. | ✅ PASS |
| 43 | **Blocker C: Dual-CI contract validation** | Verifies `CODE_CI_RUN_ID` and `DOCS_CI_RUN_ID` matching head SHAs and dual-platform success. | ✅ PASS |
| 44 | **Blocker B: Pinned stale vs exact progress report** | Stale lineage in progress report rejected; exact current lineage accepted. | ✅ PASS |
| 45 | **Round 4 Blocker A: Quadruple reviewed identity verification** | Missing or mismatched `reviewedDocsSha` or `reviewedInstructionSha` fails closed. | ✅ PASS |
| 46 | **Round 4 Blocker B: Exact instruction, diff manifest & prompt metadata** | Prompt bundles exact instruction text, changed files list, and section metadata. | ✅ PASS |
| 47 | **Round 4 Blocker C: SupervisorEngine logger initialization** | Warnings logged without `NameError` on fail-closed paths. | ✅ PASS |
| 48 | **Round 4 Blocker E: Idempotent BLOCKED issue comments** | Window B2 marker adoption check prevents duplicate comments for BLOCKED decisions. | ✅ PASS |
| 49 | **Round 4 Blocker D: Configurable SUPERVISOR_AI_MODEL** | Model passed in config dispatched correctly in API request payloads and audit log. | ✅ PASS |
| 50 | **Round 5 Blocker A: Truncation gate fails closed** | Critical evidence section truncated without full completeness coverage fails closed (`CHANGES_REQUIRED`). | ✅ PASS |
| 51 | **Round 5 Blocker A: Changed-files status & omission detection** | Parses A/M/D/R statuses with rename old/new paths; omits from manifest trigger fail-closed. | ✅ PASS |
| 52 | **Round 5 Blocker B: Fail-closed pinned evidence fetch** | Missing/empty/timeout/404 on required pinned evidence halts review before AI provider call. | ✅ PASS |
| 53 | **Round 5 Blocker C: Window B1 5-trailer & marker isolation** | Adopts remote instruction commit only when all 5 trailers and blob marker match; isolates evidence IDs. | ✅ PASS |
| 54 | **Round 5 Blocker C: Multi-candidate fail-closed** | Multiple matching remote commits raise `GitHubVerificationError` instead of guessing. | ✅ PASS |
| 55 | **Round 5 Blocker D: Strict boolean parsing & 40-char SHA** | Typos in booleans (`USED_MOCK=tru`) return `None`; validates 40-char hex SHAs and positive numeric CI IDs. | ✅ PASS |
| 56 | **Round 5 Blocker D: Live mode model config validation** | Blank model or incompatible provider/model combinations raise `ConfigValidationError`. | ✅ PASS |
| 57 | **Round 6 Blocker A: Exact 6-trailer lineage required** | Missing any of 6 trailers (`Reviewed-Code-Sha`, `Reviewed-Docs-Sha`, `Reviewed-Instruction-Sha`, `Reviewed-Evidence-Id`, `Supervisor-Decision`, `Supervisor-Review-Id`) or short SHA rejects candidate adoption. | ✅ PASS |
| 58 | **Round 6 Blocker A: Remote blob read fail-closed & 6-marker verification** | 404, empty, timeout, or exception on remote blob reading fails closed; remote blob must contain exact 6-identity marker. | ✅ PASS |
| 59 | **Round 6 Blocker A: Durable SHA256 digest authority & staged SHA isolation** | Intended content SHA256 durably persisted before write; staged commits re-verified before adoption; prevents cross-adoption across evidence/review IDs. | ✅ PASS |
| 60 | **Round 6 Blocker B: Mandatory Real Blender acceptance evidence** | Missing or empty `docs/REAL_E2E_ACCEPTANCE.md` when `real_blender=True` halts before provider call; auxiliary Product Truth cannot substitute. | ✅ PASS |
| 61 | **Round 6 Blocker C: Authoritative changed-files manifest comparison** | Detects omitted files, phantom files, status spoofing (`M` vs `A`/`D`/`R`), and rename old/new path mismatches against git authority. | ✅ PASS |
| 62 | **Round 6 Blocker C: Distinct CODE and DOCS diff ranges & contamination check** | Split diff ranges (`INSTRUCTION_SHA..CODE_SHA` vs `CODE_SHA..DOCS_SHA`); files from DOCS commit in CODE diff fail closed. | ✅ PASS |
| 63 | **Round 6 Blocker D: Strict DOCS_CI_RUN_ID validation at parse boundary** | Live strict contract enforces positive integer `DOCS_CI_RUN_ID` before GitHub API; disallows legacy `CI_RUN_ID` substitution. | ✅ PASS |
| 64 | **Round 6 Blocker D: Provider request ID capture & structured audit** | Extracts provider request ID from OpenAI/Anthropic/Gemini responses into structured audit trail; explicit `None` when absent. | ✅ PASS |

---

## 4. Test Execution Summary

```
pytest -v tests/test_supervisor.py
======================== 64 passed, 1 warning in 4.31s ========================

pytest -q
======================== 762 passed ===========================================
```
- Supervisor control-plane test cases: 64 (100% pass)
- Total repository regression suite: 762 (100% pass, 0 failures)
- Dual-platform CI verification on exact CODE commit `2bc44acdd985b5d29ac3a1a3a40fa63d21fc244f`:
  - Run ID: `34783581901`
  - `unit (ubuntu-latest)`: `103794888701` SUCCESS (20m 42s)
  - `unit (windows-latest)`: `103794888628` SUCCESS (16m 00s)
- Clean-tree real environment verification:
  - `scripts/run_product_truth_render_e2e.py`
  - `generation`: `50a84d04-85c2-429d-8c12-641006ac95f1`
  - `evidenceCodeCommit`: `2bc44acdd985b5d29ac3a1a3a40fa63d21fc244f`
  - `workingTreeClean`: `true`
