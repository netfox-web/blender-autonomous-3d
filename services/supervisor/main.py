"""FastAPI application for the Autonomous Supervisor Control Plane."""

from __future__ import annotations

import json
import logging
import subprocess
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from services.supervisor.ai_adapter import (
    RuleBasedSupervisorAdapter,
    SemanticEvidenceSupervisorAdapter,
    SupervisorProviderAdapter,
)
from services.supervisor.config import SupervisorConfig, load_config
from services.supervisor.engine import SupervisorEngine
from services.supervisor.github_client import GitHubClient, GitHubVerificationError
from services.supervisor.models import ReadyForReGateContract
from services.supervisor.policy import PolicyEngine
from services.supervisor.security import (
    SecurityError,
    authorize_sender,
    validate_repo_and_branch,
    verify_admin_auth,
    verify_github_signature,
)
from services.supervisor.state import StateManager
from services.supervisor.watchdog import SupervisorWatchdog

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("supervisor.app")


def create_app(config: Optional[SupervisorConfig] = None) -> FastAPI:
    cfg = config or load_config()
    state_mgr = StateManager(cfg.state_db_path)
    github_client = GitHubClient(cfg)

    if cfg.ai_provider == "semantic_evidence" or cfg.mode.lower() == "live":
        ai_adapter: SupervisorProviderAdapter = SemanticEvidenceSupervisorAdapter()
    else:
        ai_adapter = RuleBasedSupervisorAdapter()

    policy_engine = PolicyEngine(cfg.audit_log_path)
    engine = SupervisorEngine(
        config=cfg,
        state_mgr=state_mgr,
        github_client=github_client,
        ai_adapter=ai_adapter,
        policy_engine=policy_engine,
    )
    watchdog = SupervisorWatchdog(engine=engine, interval_seconds=cfg.watchdog_interval_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Supervisor control plane starting on port %s...", cfg.port)
        watchdog.start()
        yield
        logger.info("Supervisor control plane shutting down...")
        watchdog.stop()

    app = FastAPI(
        title="Fox3D Autonomous Supervisor Control Plane",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.config = cfg
    app.state.state_mgr = state_mgr
    app.state.github_client = github_client
    app.state.ai_adapter = ai_adapter
    app.state.policy_engine = policy_engine
    app.state.engine = engine
    app.state.watchdog = watchdog

    def check_admin_access(request: Request) -> None:
        auth_header = request.headers.get("Authorization") or request.headers.get("X-Supervisor-Admin-Key")
        client_host = request.client.host if request.client else ""
        is_live = cfg.mode.lower() == "live"
        if not verify_admin_auth(auth_header, cfg.admin_key, is_live=is_live, client_host=client_host):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Supervisor admin authentication required.",
            )

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok", "service": "supervisor-control-plane"}

    @app.post("/webhooks/github")
    async def github_webhook(
        request: Request,
        x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
        x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
        x_github_delivery: Optional[str] = Header(None, alias="X-GitHub-Delivery"),
    ) -> Dict[str, Any]:
        """GitHub webhook endpoint handling HMAC-SHA256 authenticated events."""
        body_bytes = await request.body()

        # 1. Signature Verification
        if not verify_github_signature(body_bytes, x_hub_signature_256, cfg.webhook_secret):
            logger.warning("Rejected webhook delivery with invalid or missing HMAC signature.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing X-Hub-Signature-256.",
            )

        delivery_id = x_github_delivery or ""

        # 2. Durable Delivery Lifecycle Evaluation
        if delivery_id:
            can_proc, reason = state_mgr.evaluate_delivery(delivery_id)
            if not can_proc:
                if reason == "IGNORED_DUPLICATE_DELIVERY":
                    logger.info("Ignoring duplicate webhook delivery %s.", delivery_id)
                    return {"status": "IGNORED_DUPLICATE_DELIVERY", "delivery_id": delivery_id}
                elif reason == "PROCESSING_IN_FLIGHT":
                    logger.info("Delivery %s is currently processing.", delivery_id)
                    return {"status": "PROCESSING_IN_FLIGHT", "delivery_id": delivery_id}
                else:
                    return {"status": reason, "delivery_id": delivery_id}

            state_mgr.record_delivery_received(delivery_id, x_github_event or "unknown")
            state_mgr.set_delivery_status(delivery_id, "PROCESSING")

        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            if delivery_id:
                state_mgr.set_delivery_status(delivery_id, "FAILED_TERMINAL", error="Invalid JSON payload")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload.")

        event_name = (x_github_event or "").lower()
        logger.info("Received authenticated GitHub event '%s' (delivery: %s)", event_name, delivery_id)

        try:
            # Check repository match
            repo_data = payload.get("repository") or {}
            repo_full_name = repo_data.get("full_name") or ""
            if repo_full_name and repo_full_name.lower() != cfg.repo_name.lower():
                logger.warning("Rejected webhook for wrong repo '%s' (expected '%s').", repo_full_name, cfg.repo_name)
                if delivery_id:
                    state_mgr.set_delivery_status(delivery_id, "FAILED_TERMINAL", error=f"Wrong repo: {repo_full_name}")
                return {
                    "status": "IGNORED_WRONG_REPOSITORY",
                    "reason": f"Repo '{repo_full_name}' != '{cfg.repo_name}'",
                }

            if event_name == "issue_comment":
                action = payload.get("action", "")
                if action != "created":
                    logger.info("Ignoring issue_comment action '%s' (only 'created' triggers re-gate).", action)
                    if delivery_id:
                        state_mgr.set_delivery_status(delivery_id, "COMPLETED")
                    return {"status": "IGNORED_UNSUPPORTED_ACTION", "action": action}

                issue = payload.get("issue", {})
                comment = payload.get("comment", {})
                sender = payload.get("sender", {}).get("login", "")
                author_assoc = comment.get("author_association", "")

                # Loop protection: ignore supervisor's own comment
                if "[supervisor]" in comment.get("body", "").lower() or sender.lower() == "fox3d-supervisor[bot]":
                    if delivery_id:
                        state_mgr.set_delivery_status(delivery_id, "COMPLETED")
                    return {"status": "IGNORED_SUPERVISOR_OWN_COMMENT"}

                # Sender authorization (Blocker A)
                try:
                    authorize_sender(
                        sender_login=sender,
                        author_association=author_assoc,
                        allowed_senders=cfg.allowed_senders,
                        allowed_associations=cfg.allowed_associations,
                    )
                except SecurityError as se:
                    logger.warning("Unauthorized commenter '%s' (assoc: '%s'): %s", sender, author_assoc, se)
                    if delivery_id:
                        state_mgr.set_delivery_status(delivery_id, "FAILED_TERMINAL", error=str(se))
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Sender '{sender}' is not authorized to trigger supervisor re-gate.",
                    )

                issue_number = issue.get("number")
                body = comment.get("body", "")

                if issue_number != cfg.allowed_issue_number:
                    if delivery_id:
                        state_mgr.set_delivery_status(delivery_id, "COMPLETED")
                    return {
                        "status": "IGNORED_UNSUPPORTED_ISSUE",
                        "reason": f"Issue {issue_number} is not Issue {cfg.allowed_issue_number}.",
                    }

                contract = ReadyForReGateContract.parse_from_text(body)
                if not contract:
                    if delivery_id:
                        state_mgr.set_delivery_status(delivery_id, "COMPLETED")
                    return {"status": "IGNORED_NO_CONTRACT", "reason": "No READY_FOR_RE_GATE block found."}

                logger.info("Parsed valid READY_FOR_RE_GATE contract for CODE_SHA %s.", contract.code_sha)
                res = engine.handle_ready_contract(contract, delivery_id=delivery_id)
                if delivery_id:
                    state_mgr.set_delivery_status(delivery_id, "COMPLETED")
                return res

            elif event_name in ("workflow_run", "push"):
                if delivery_id:
                    state_mgr.set_delivery_status(delivery_id, "COMPLETED")
                return {"status": "EVENT_ACKNOWLEDGED", "event": event_name}

            if delivery_id:
                state_mgr.set_delivery_status(delivery_id, "COMPLETED")
            return {"status": "IGNORED_EVENT", "event": event_name}

        except (GitHubVerificationError, httpx.RequestError, subprocess.CalledProcessError) as e:
            if delivery_id:
                state_mgr.set_delivery_status(delivery_id, "FAILED_RETRYABLE", error=str(e))
            raise
        except HTTPException:
            raise
        except Exception as e:
            if delivery_id:
                state_mgr.set_delivery_status(delivery_id, "FAILED_TERMINAL", error=str(e))
            raise

    @app.get("/supervisor/status")
    async def supervisor_status(request: Request) -> Dict[str, Any]:
        """Observability: current supervisor phase, state, locks, and lineage."""
        check_admin_access(request)
        st = state_mgr.get_state()
        recent_reviews = state_mgr.list_reviews(limit=1)
        last_review = recent_reviews[0] if recent_reviews else None

        return {
            "current_status": st.status.value,
            "active_review_id": st.active_review_id,
            "last_reviewed_code_sha": st.last_reviewed_code_sha,
            "last_reviewed_docs_sha": st.last_reviewed_docs_sha,
            "last_processed_instruction_sha": st.last_processed_instruction_sha,
            "last_seen_event_id": st.last_seen_event_id,
            "retry_count": st.retry_count,
            "started_at": st.started_at,
            "completed_at": st.completed_at,
            "last_review": last_review.model_dump() if last_review else None,
            "repo_name": cfg.repo_name,
            "allowed_branch": cfg.allowed_branch,
            "event_driven_ready": False,  # As required by Section 18
        }

    @app.get("/supervisor/reviews")
    async def list_reviews(request: Request, limit: int = 20) -> Dict[str, Any]:
        """Observability: list past reviews."""
        check_admin_access(request)
        reviews = state_mgr.list_reviews(limit=limit)
        return {"reviews": [r.model_dump() for r in reviews], "count": len(reviews)}

    @app.get("/supervisor/reviews/{review_id}")
    async def get_review_detail(request: Request, review_id: str) -> Dict[str, Any]:
        """Observability: inspect a specific review record."""
        check_admin_access(request)
        rev = state_mgr.get_review(review_id)
        if not rev:
            raise HTTPException(status_code=404, detail="Review not found.")
        return rev.model_dump()

    return app


app = create_app()
