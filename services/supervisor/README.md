# Autonomous Supervisor Control Plane

Independent event-driven control plane for `netfox-web/blender-autonomous-3d`. Replaces periodic hourly manual ChatGPT GitHub polling with near real-time automated AI Re-Gate verification.

## Architecture

1. **Webhook Ingestion**: Authenticates `X-Hub-Signature-256` HMAC-SHA256 headers.
2. **Contract Parser**: Extracts machine-readable `READY_FOR_RE_GATE` blocks from Issue #1 comments.
3. **Idempotency & Concurrency Lock**: Re-gates any `CODE_SHA + EVIDENCE_GENERATION_ID` at most once; serializes concurrent reviews and queues newer code.
4. **Independent Evidence Verification**: Validates commits on `main`, CI conclusion, Ubuntu + Windows job success, and documentation hashes directly with GitHub.
5. **AI Re-Gate Engine**: Decoupled `SupervisorProviderAdapter` assesses progress reports, truth boundaries, and blockers.
6. **Strict Write Policy**: AI can only propose instruction updates and issue comments; guardrails block destructive/CNC operations.
7. **Loop Protection**: Supervisor's own instruction commits and issue comments never trigger review loops.
8. **Watchdog Fallback**: Checks Issue #1 every 1 hour in case webhooks are delayed or missed.

## Quick Start

### Local Execution

```bash
python scripts/run_supervisor.py
```

Runs FastAPI server on `http://0.0.0.0:8791`.

### Docker Execution

```bash
docker build -t fox3d-supervisor -f services/supervisor/Dockerfile .
docker run -p 8791:8791 --env-file services/supervisor/.env fox3d-supervisor
```

## API Endpoints

- `POST /webhooks/github`: Authenticated GitHub webhook listener.
- `GET /supervisor/status`: Active state, last reviewed code SHA, and review history.
- `GET /supervisor/reviews`: Recent review history.
- `GET /supervisor/reviews/{id}`: Deep inspection of specific review record.
- `GET /health`: Liveness probe.
