# Event-Driven Autonomous Supervisor Architecture

**System**: Fox3D Autonomous Supervisor Control Plane  
**Target Repository**: `netfox-web/blender-autonomous-3d`  
**Status**: Implemented (Control Plane V1)  
**Readiness Boundary**: `eventDrivenSupervisorReady=false` (per Section 18; held until verified by live GitHub webhook execution).

---

## 1. Executive Summary

Historically, autonomous development in this repository relied on periodic (e.g., hourly or ad-hoc) GitHub polling by ChatGPT or manual triggering to inspect commits, verify CI, re-gate artifacts, and emit next-phase instructions.

The **Event-Driven Autonomous Supervisor** establishes an independent, asynchronous, durable control plane that listens for repository events directly from GitHub Webhooks (`POST /webhooks/github`). Upon receiving a machine-readable `READY_FOR_RE_GATE` contract block on Issue #1:
1. It validates the cryptographic HMAC-SHA256 signature (`X-Hub-Signature-256`) and checks for replay/delivery duplicates.
2. It acquires a durable review lock and enforces idempotency (`CODE_SHA + EVIDENCE_GENERATION_ID` reviewed at most once).
3. It independently verifies the claim against GitHub: checks that `CODE_SHA` and `DOCS_SHA` exist and are merged on `main`, confirms CI run ID matches `CODE_SHA` with overall conclusion `success`, and verifies that both `ubuntu-latest` and `windows-latest` jobs succeeded.
4. It compiles context (commits, diffs, progress reports, audit files, acceptance records) and invokes the AI Re-Gate evaluation layer (`SupervisorProviderAdapter`).
5. It enforces a strict write policy (downgrading any destructive, secret, or physical CNC/laser/PLC operations to `BLOCKED` with `HUMAN_APPROVAL_REQUIRED`).
6. It atomically updates `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md` (and neutral alias `docs/AGENT_NEXT_PHASE_INSTRUCTIONS.md`), pushes to GitHub, and posts a structured `SUPERVISOR_REVIEW_COMPLETE` comment on Issue #1.
7. The Antigravity agent watcher detects the new instruction commit and immediately claims the next phase without human intervention.
8. A lightweight background watchdog checks once per hour only as a fallback for missed or dropped webhook deliveries.

---

## 2. Event Flow & Sequence Diagram

```
Antigravity Agent                   GitHub                     Supervisor Webhook & Engine
       |                              |                                     |
       |-- 1. Push CODE + DOCS ------>|                                     |
       |-- 2. Verify CI Green ------->|                                     |
       |-- 3. Post Issue Comment ---->| (READY_FOR_RE_GATE)                 |
       |                              |                                     |
       |                              |-- 4. Delivery: issue_comment ------>|
       |                              |      (HMAC-SHA256 authenticated)    |
       |                              |                                     |-- 5. Verify Signature & Nonce
       |                              |                                     |-- 6. Acquire Review Lock
       |                              |<-- 7. Query Commits, CI, Jobs ------|
       |                              |--- 8. Return Verified Lineage ----->|
       |                              |                                     |-- 9. Invoke AI Re-Gate Review
       |                              |                                     |-- 10. Enforce Write Policy
       |                              |<-- 11. Commit Next Instructions ----|
       |                              |<-- 12. Post Issue Comment ----------|
       |                              |        (SUPERVISOR_REVIEW_COMPLETE) |-- 13. Release Lock & Update State
       |                              |                                     |
       |<-- 14. Watcher Detects ------|                                     |
       |    New Instruction SHA       |                                     |
       |-- 15. Auto-Claims Next Round |                                     |
```

---

## 3. Core Components

### 3.1 Webhook Ingestion & Security (`services/supervisor/security.py`)
- **Endpoint**: `POST /webhooks/github`
- **HMAC Verification**: Calculates SHA-256 over raw payload bytes using `GITHUB_WEBHOOK_SECRET` and compares with `X-Hub-Signature-256` using constant-time `hmac.compare_digest`.
- **Delivery Deduplication**: Tracks `X-GitHub-Delivery` in `seen_events` table; duplicate deliveries are acknowledged immediately without reprocessing.
- **Repository / Branch Bounds**: Rejects payloads for repositories other than `netfox-web/blender-autonomous-3d` or branches other than `main`.

### 3.2 Machine-Readable Contract (`READY_FOR_RE_GATE`)
Contract block parsed from Issue #1 comments:
```text
READY_FOR_RE_GATE

REPO=netfox-web/blender-autonomous-3d
ISSUE=1
INSTRUCTION_SHA=<sha>
CODE_SHA=<sha>
DOCS_SHA=<sha>
CI_RUN_ID=<id>
TEST_COUNT=<number>
EVIDENCE_GENERATION_ID=<id>
REAL_BLENDER=<true|false>
USED_MOCK=<true|false>
```

### 3.3 Independent Verification Authority (`services/supervisor/github_client.py`)
The supervisor never trusts user or agent comment claims blindly:
- Re-queries GitHub API / local git to confirm `CODE_SHA` is an ancestor of `main`.
- Queries `/actions/runs/{CI_RUN_ID}` to verify `head_sha == CODE_SHA` and `conclusion == "success"`.
- Inspects run jobs to confirm both `unit (ubuntu-latest)` and `unit (windows-latest)` concluded with `success`.
- Verifies `DOCS_SHA` is reachable from `main`.

### 3.4 Durable State & Review Concurrency Lock (`services/supervisor/state.py`)
- Backed by SQLite (`.fox3d-data/supervisor_state.db`).
- **Singleton State Table**: Tracks `status`, `active_review_id`, `last_reviewed_code_sha`, `last_reviewed_docs_sha`, `last_processed_instruction_sha`, `retry_count`, `started_at`, `completed_at`.
- **Atomic Lock (`active_lock`)**: Ensures only one review runs at any instant.
  - If identical `CODE_SHA` arrives during an active review: `IGNORE_DUPLICATE`.
  - If newer `CODE_SHA` arrives during an active review: enqueued in `pending_queue` as `PENDING_NEWER_EVIDENCE` and processed immediately after the current review completes.
- **Idempotency**: Completed reviews (`decision IS NOT NULL`) are recorded; identical contracts are never re-evaluated.

### 3.5 AI Re-Gate Interface (`services/supervisor/ai_adapter.py`)
- Decoupled interface `SupervisorProviderAdapter`:
  ```python
  def review_repository(context: ReviewContext) -> SupervisorReviewOutput
  ```
- **Inputs**: `ReadyForReGateContract`, commit history, diffs, `GROK_PROGRESS_REPORT.md`, `CURRENT_IMPLEMENTATION_AUDIT.md`, `REAL_E2E_ACCEPTANCE.md`, CI run metadata, upstream instruction text.
- **Outputs**:
  - `decision`: `ACCEPT_WITH_SCOPE` | `CHANGES_REQUIRED` | `BLOCKED`
  - `accepted_claims[]`, `rejected_claims[]`
  - `truth_matrix`: `REAL[]`, `MOCK[]`, `PARTIAL[]`, `BLOCKED[]`
  - `blockers[]`
  - `next_instruction_markdown`: Next round instruction text.
  - `issue_comment_markdown`: Structured Issue #1 response.

### 3.6 Strict Write Policy & Safety Guardrails (`services/supervisor/policy.py`)
- AI adapter has **zero direct access** to tokens, credentials, or shells.
- All write actions pass through `PolicyEngine`:
  - Permitted actions: `UPDATE_NEXT_INSTRUCTION`, `ADD_ISSUE_COMMENT`.
  - Strictly prohibited: `delete_branch`, `force_push`, `close_issue`, `merge_pr`, `delete_file`, `modify_secrets`, `modify_github_settings`.
- **Physical & Destructive Guardrails**:
  - Automatically triggers `BLOCKED` and posts `HUMAN_APPROVAL_REQUIRED` if instructions or diffs attempt live factory machinery control (`LIVE_CNC`, `LIVE_LASER`, `PLC`), destructive production actions, or secret manipulation.
- **Audit Logging**: Every write action, whether allowed or blocked, is recorded to `.fox3d-data/supervisor_audit.log`.

### 3.7 Loop Protection
- Supervisor ignores its own issue comments (marked with `[SUPERVISOR]` or authored by `fox3d-supervisor[bot]`).
- Webhook push events generated by supervisor instruction commits are acknowledged but do not trigger a review.
- Every `READY_FOR_RE_GATE` contract must advance code or instruction lineage (`instructionSha != lastProcessedInstructionSha` or `codeSha != lastReviewedCodeSha`).

### 3.8 Observability Endpoints (`services/supervisor/main.py`)
- `GET /supervisor/status`: Active state, last reviewed code SHA, lineage, and watchdog status.
- `GET /supervisor/reviews`: Recent review log and verdicts.
- `GET /supervisor/reviews/{id}`: Detailed review record.
- `GET /health`: Liveness probe.

### 3.9 Watchdog Fallback (`services/supervisor/watchdog.py`)
- Runs once per hour in the background.
- Scans recent Issue #1 comments for any unhandled `READY_FOR_RE_GATE` contracts.
- Catches dropped packets, network timeouts, or webhook delivery failures.

### 3.10 Migration Aliases
- `docs/GROK_NEXT_PHASE_INSTRUCTIONS.md` <-> `docs/AGENT_NEXT_PHASE_INSTRUCTIONS.md`
- `docs/GROK_PROGRESS_REPORT.md` <-> `docs/AGENT_PROGRESS_REPORT.md`
- Backward compatibility preserved; agents prioritize neutral `AGENT_*` names.
