# Development Agent 修正指令：Event-Driven Supervisor Re-Gate Round 1 — CHANGES REQUIRED

> Repo: `netfox-web/blender-autonomous-3d`
> Reviewed Supervisor CODE: `872da2030ce7d67557b613e24aac0cc8266fcd28`
> Reviewed docs/head: `2a7e8624b7883c3bf687666bc416d3107cd9271f`
> CODE Actions: `34755874821` — Ubuntu `103720037645` SUCCESS / Windows `103720037559` SUCCESS
> DOCS Actions: `34756868704` — Ubuntu `103722630350` SUCCESS / Windows `103722630394` SUCCESS
> Reported regression: **717 passed**; Supervisor-specific: **19 passed**
> Re-Gate result: **CHANGES REQUIRED**
> `WEBHOOK_REAL_E2E=false`; `EVENT_DRIVEN_READY=false` remains correct.
> **Phase 961+ remains HOLD.**

## 0. Accepted work — preserve it

Do not rewrite existing Fox3D Scheduler / Queue / DAM / Recipe / TwinStore / CabinetSpec / Product Truth architecture.

Accepted within scope:

- Event-driven Supervisor control-plane skeleton exists under `services/supervisor/`.
- HMAC SHA-256 signature verification, delivery-id storage, repo/issue contract parsing, CI verification, durable review state/lock, policy layer, watchdog, and Antigravity watcher are implemented and covered by local tests.
- Exact Supervisor CODE `872da20` passed GitHub Actions on Ubuntu + Windows.
- Exact docs/head `2a7e862` also passed Ubuntu + Windows.
- Documentation correctly keeps `eventDrivenSupervisorReady=false` and `webhookRealE2e=false`; do not upgrade these flags from unit/integration tests.
- Existing Product Content / Product Truth REAL/MOCK/PARTIAL/BLOCKED truth boundaries remain unchanged.

The prior **Phase 901–960 Re-Gate Round 2 Product Content blockers remain open**. Do not claim they were fixed by this Supervisor side-track. Preserve the prior instruction lineage at blob `39024d643b931a5a60933dde9c1b8cba0ab3b327`; Phase 961+ stays HOLD until those product blockers are separately re-gated.

## 1. Blocker A — public Issue comment currently has no trusted-sender authorization

GitHub webhook HMAC proves the event came from GitHub, but it does **not** prove the commenter is authorized to command the Supervisor. The repository is public, and the current route accepts any Issue #1 comment containing a syntactically valid `READY_FOR_RE_GATE` contract.

### Required correction

1. Before parsing/processing READY, verify `payload.repository.full_name` exactly equals the configured repo.
2. Require `issue_comment.action == created` for the trigger path.
3. Authorize the commenter using an explicit allowlist and/or GitHub `author_association` / collaborator permission check. Default-deny unknown public commenters.
4. Recommended minimum accepted associations: OWNER / MEMBER / COLLABORATOR, with an optional explicit `SUPERVISOR_ALLOWED_SENDERS` allowlist.
5. Log authorization decision without leaking tokens/secrets.
6. Add negative tests: outsider comment, wrong repo payload with valid HMAC, edited/deleted comment event, spoofed contract from unauthorized sender.

## 2. Blocker B — delivery dedupe is recorded before processing, so a crash can permanently lose a valid event

`main.py` currently calls `record_delivery()` before JSON parsing and before `engine.handle_ready_contract()` completes. If the process crashes or GitHub/API work fails after that point, a GitHub retry with the same `X-GitHub-Delivery` is returned as `IGNORED_DUPLICATE_DELIVERY`; the READY event can be lost.

### Required correction

Implement a durable delivery lifecycle, not a single seen/not-seen bit:

- RECEIVED
- PROCESSING
- COMPLETED
- FAILED_RETRYABLE
- FAILED_TERMINAL

Rules:

1. Same delivery in COMPLETED/FAILED_TERMINAL -> dedupe safely.
2. Same delivery in FAILED_RETRYABLE or stale PROCESSING -> resume/retry safely.
3. Do not mark COMPLETED until the intended terminal outcome is durably recorded.
4. Crash before GitHub write must allow retry.
5. Crash after instruction push but before Issue comment must resume from persisted write state and post only the missing comment, without creating a second instruction commit.
6. Add subprocess/process-crash tests that prove these exact windows, not only in-process mock exceptions.

## 3. Blocker C — GitHub write path can silently report success when `git push` failed

`GitHubClient.commit_instruction_file()` currently catches push failure and still returns the local commit SHA. The engine can then post `SUPERVISOR_REVIEW_COMPLETE` even though the instruction commit never reached GitHub main.

### Required correction

1. **Never swallow push failure in live mode.** Push failure is retryable failure; do not post success comment.
2. Before write: fetch `origin/main`, prove local branch/base is the expected remote head, and ensure no unrelated staged changes are included.
3. Only allow the instruction paths intended by policy (`docs/GROK_NEXT_PHASE_INSTRUCTIONS.md` and neutral alias if required).
4. After push: verify remote `main` contains the exact new commit and verify the remote instruction file content/blob corresponds to the intended payload.
5. Persist the successful instruction commit SHA before attempting the Issue comment so crash recovery can resume without duplicate commit.
6. Issue `SUPERVISOR_REVIEW_COMPLETE` only after remote push verification succeeds.
7. Add tests for rejected push, non-fast-forward, dirty/pre-staged unrelated file, remote verification mismatch, push-success/comment-failure recovery, and duplicate retry.

## 4. Blocker D — current live reviewer is not a real Re-Gate authority

`create_app()` always instantiates `RuleBasedSupervisorAdapter()`. That adapter can ACCEPT based mainly on:

- `test_count >= 10`,
- progress report non-empty,
- contract `real_blender` / `used_mock` flags.

It does **not** materially review repository diffs, the requested audit/acceptance files, or semantic evidence. `ReviewContext.diffs` is currently empty. Therefore an arbitrary bad code change can still receive `ACCEPT_WITH_SCOPE` if the READY contract and test count look plausible.

### Required correction

1. Treat `RuleBasedSupervisorAdapter` and `MockSupervisorAdapter` as TEST/DEVELOPMENT ONLY.
2. Live event-driven mode must fail closed unless a real configured `SupervisorProviderAdapter` is available.
3. Build the review context from independently fetched GitHub evidence at the claimed SHAs, including at minimum:
   - commits since instruction SHA;
   - actual per-file diff/patch or equivalent changed-file content;
   - `docs/GROK_PROGRESS_REPORT.md` / `AGENT_PROGRESS_REPORT.md`;
   - `docs/CURRENT_IMPLEMENTATION_AUDIT.md`;
   - `docs/REAL_E2E_ACCEPTANCE.md`;
   - `docs/CABINET_REAL_ACCEPTANCE.md` where applicable;
   - current instruction text;
   - exact CODE/DOCS CI summaries.
4. Do not trust the READY contract's REAL/MOCK flags as review conclusions; independently reconcile them against acceptance/audit evidence.
5. Structured reviewer output must remain schema-validated and pass the policy layer before writes.
6. If provider unavailable, malformed output, timeout, or contradictory evidence -> CHANGES_REQUIRED/BLOCKED or retryable failure; never auto-ACCEPT.
7. Add adversarial tests where contract says green/REAL but the diff or acceptance evidence contradicts it; ACCEPT must be impossible.

## 5. Blocker E — live configuration must fail closed

Current configuration has a development default webhook secret (`dev-webhook-secret-not-for-prod`). This is acceptable only for local tests, not a live webhook endpoint.

### Required correction

1. Add explicit execution mode, e.g. `SUPERVISOR_MODE=test|live`.
2. In `live` mode require:
   - non-default strong `GITHUB_WEBHOOK_SECRET`;
   - GitHub token / installation auth with minimum required permissions;
   - configured authorized senders;
   - real reviewer provider configuration;
   - writable state/audit storage.
3. Refuse startup if any live prerequisite is missing/default.
4. Never print secret/token values.
5. Protect `/supervisor/status` and `/supervisor/reviews*` in live mode with admin auth or bind them to a trusted/private interface; do not expose internal review/audit details publicly by default.

## 6. REAL webhook E2E acceptance required before readiness

After Blocks A–E are fixed:

1. Run full `pytest -q`; record exact count.
2. Commit exact CODE SHA and wait for Ubuntu + Windows SUCCESS on that SHA.
3. Configure a **real GitHub webhook** for this repo with the live secret and the Supervisor endpoint.
4. Perform one controlled REAL chain using a harmless test/correction instruction:
   - authorized agent posts `READY_FOR_RE_GATE` on Issue #1;
   - GitHub sends a real delivery ID;
   - endpoint verifies HMAC and sender/repo authority;
   - Supervisor independently verifies CODE/DOCS/CI/evidence;
   - reviewer returns a structured decision;
   - Supervisor pushes exactly one instruction commit to GitHub;
   - remote commit is verified;
   - Issue #1 gets exactly one `SUPERVISOR_REVIEW_COMPLETE`;
   - Antigravity watcher detects the new instruction and claims it exactly once.
5. Capture delivery ID, reviewed CODE SHA, CI run/job IDs, resulting instruction commit SHA, Issue comment id, watcher claimed instruction/blob SHA, and timestamps.
6. Run at least one retry/replay proof showing duplicate delivery / duplicate READY cannot create another instruction commit.
7. Update `docs/EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md` and runbook with REAL evidence.
8. Only after that chain passes may `webhookRealE2e=true` and `eventDrivenSupervisorReady=true` be proposed for Re-Gate. Do not self-promote readiness before review.

## 7. Existing Fox3D product truth boundaries remain fixed

Do not use Supervisor work to loosen any existing product/manufacturing boundary:

- live H3 MAX / LTX 2.5 = BLOCKED unless separately proven REAL;
- Vision Judge = MOCK/BLOCKED;
- physical print = false/BLOCKED;
- LIVE_CNC / LIVE_LASER / PLC / machine control = BLOCKED;
- `commercialAssetProductionReady=false`;
- `globalProductionReady=false`;
- `fullAutonomousFactoryReady=false`;
- `liveFactoryExecutionReady=false`.

After Supervisor correction and REAL webhook E2E evidence are complete, stop for Re-Gate. Do not start Phase 961+ and do not erase the still-open Phase 901–960 Product Content correction lineage.