# Event-Driven Autonomous Supervisor Runbook

Operational and maintenance guide for the **Fox3D Autonomous Supervisor Control Plane**.

---

## 1. Prerequisites & Environment Configuration

Copy `services/supervisor/.env.example` to `services/supervisor/.env` or configure the following environment variables:

```bash
# GitHub Authentication & Settings
GITHUB_WEBHOOK_SECRET="<generate_secure_random_hex_key>"
GITHUB_TOKEN="ghp_<pat_with_repo_and_issues_scope>"
GITHUB_REPO_NAME="netfox-web/blender-autonomous-3d"
GITHUB_ALLOWED_BRANCH="main"
GITHUB_ALLOWED_ISSUE="1"

# Service Binding
SUPERVISOR_HOST="0.0.0.0"
SUPERVISOR_PORT="8791"

# File Paths
SUPERVISOR_STATE_DB_PATH=".fox3d-data/supervisor_state.db"
SUPERVISOR_AUDIT_LOG_PATH=".fox3d-data/supervisor_audit.log"

# AI Review Adapter
SUPERVISOR_AI_PROVIDER="rule_based"  # options: rule_based, mock, openai, anthropic, gemini
SUPERVISOR_AI_API_KEY=""

# Watchdog interval (seconds)
SUPERVISOR_WATCHDOG_INTERVAL="3600"
```

---

## 2. GitHub Webhook Configuration

In the GitHub repository (`netfox-web/blender-autonomous-3d` -> **Settings** -> **Webhooks** -> **Add webhook**):

1. **Payload URL**: `https://<supervisor_host_domain>/webhooks/github` (or via reverse proxy / tunnel like Cloudflare Tunnel / ngrok for development).
2. **Content type**: `application/json`.
3. **Secret**: Enter the exact string set in `GITHUB_WEBHOOK_SECRET`.
4. **SSL verification**: Enable SSL verification.
5. **Events to trigger**:
   - `Issue comments` (Required)
   - `Issues` (Optional)
   - `Pushes` (Optional for push lineage tracking)
   - `Workflow runs` (Optional for CI status tracking)
6. **Active**: Check **Active** and click **Add webhook**.

---

## 3. Starting the Service

### Option A: Local Python Process
```bash
python scripts/run_supervisor.py
```
Starts on `http://0.0.0.0:8791`.

### Option B: Docker Container
```bash
docker build -t fox3d-supervisor -f services/supervisor/Dockerfile .
docker run -d --name supervisor \
  --restart unless-stopped \
  -p 8791:8791 \
  -v $(pwd)/.fox3d-data:/app/.fox3d-data \
  --env-file services/supervisor/.env \
  fox3d-supervisor
```

---

## 4. Antigravity Watcher Operation

The autonomous agent watcher monitors for supervisor review completion and claims new tasks without human intervention:

```bash
python scripts/antigravity_watcher.py
```

### Emitting Re-Gate Contract After Completing Work
When the agent finishes CODE + DOCS verification and dual-platform CI is green, format and post the contract block on Issue #1:
```python
from scripts.antigravity_watcher import format_ready_contract

contract_text = format_ready_contract(
    instruction_sha="a84cd64...",
    code_sha="4406119...",
    docs_sha="aac040c...",
    ci_run_id="34740940584",
    test_count=628,
    evidence_generation_id="57f72869-a017-415f-bf66-7df55824d486",
    real_blender=True,
    used_mock=False,
)
```

---

## 5. Observability & Monitoring

### Status Inspection
```bash
curl -s http://127.0.0.1:8791/supervisor/status | jq .
```
Expected output:
```json
{
  "current_status": "WAITING_AGENT",
  "active_review_id": null,
  "last_reviewed_code_sha": "4406119cbf5bc62dcb43d0dd1ec6fc041353dd28",
  "last_processed_instruction_sha": "instr_0001",
  "event_driven_ready": false
}
```

### Review History
```bash
curl -s http://127.0.0.1:8791/supervisor/reviews | jq .
```

### Audit Log Inspection
Inspect all write operations and guardrail decisions in:
```bash
tail -n 50 .fox3d-data/supervisor_audit.log
```

---

## 6. Troubleshooting & Recovery

### Lock Recovery
If the supervisor process crashes during an active review, the SQLite state marks the review as `FAILED` and increments the retry count.
To manually release an orphaned lock if the service was forcefully killed:
```sql
sqlite3 .fox3d-data/supervisor_state.db "UPDATE active_lock SET holder_review_id = NULL, locked_code_sha = NULL WHERE lock_id = 1;"
sqlite3 .fox3d-data/supervisor_state.db "UPDATE supervisor_state SET status = 'IDLE', active_review_id = NULL WHERE id = 1;"
```

### Watchdog Recovery
If GitHub webhooks were interrupted or dropped by network issues, the background watchdog automatically queries Issue #1 once per hour and triggers any unreviewed `READY_FOR_RE_GATE` contracts.
To trigger an immediate manual watchdog check:
```bash
python -c "
from services.supervisor.config import load_config
from services.supervisor.state import StateManager
from services.supervisor.github_client import GitHubClient
from services.supervisor.ai_adapter import RuleBasedSupervisorAdapter
from services.supervisor.policy import PolicyEngine
from services.supervisor.engine import SupervisorEngine
from services.supervisor.watchdog import SupervisorWatchdog

cfg = load_config()
state_mgr = StateManager(cfg.state_db_path)
gh = GitHubClient(cfg)
ai = RuleBasedSupervisorAdapter()
pol = PolicyEngine(cfg.audit_log_path)
engine = SupervisorEngine(cfg, state_mgr, gh, ai, pol)
wd = SupervisorWatchdog(engine)
print(wd.check_once())
"
```
