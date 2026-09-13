"""Watchdog fallback runner for missed webhook recovery."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict

from services.supervisor.engine import SupervisorEngine
from services.supervisor.models import ReadyForReGateContract

logger = logging.getLogger("supervisor.watchdog")


class SupervisorWatchdog:
    """Hourly background watchdog to recover any unhandled READY_FOR_RE_GATE comments."""

    def __init__(
        self,
        engine: SupervisorEngine,
        interval_seconds: int = 3600,
    ) -> None:
        self.engine = engine
        self.interval_seconds = interval_seconds
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Supervisor watchdog started with interval %s seconds.", self.interval_seconds)

    def stop(self) -> None:
        self._running = False

    def check_once(self) -> Dict[str, Any]:
        """Check Issue #1 for any unhandled READY_FOR_RE_GATE contract."""
        logger.info("Watchdog checking Issue #%s for unhandled contracts...", self.engine.config.allowed_issue_number)
        try:
            comments = self.engine.github_client.get_latest_issue_comments(
                issue_number=self.engine.config.allowed_issue_number,
                count=10,
            )
        except Exception as e:
            logger.warning("Watchdog failed to fetch comments: %s", e)
            return {"status": "ERROR", "error": str(e)}

        for c in reversed(comments):
            body = c.get("body", "")
            contract = ReadyForReGateContract.parse_from_text(body)
            if contract:
                if not self.engine.state_mgr.is_already_reviewed(contract.code_sha, contract.evidence_generation_id):
                    logger.info("Watchdog found unreviewed contract for CODE_SHA %s. Processing...", contract.code_sha)
                    res = self.engine.handle_ready_contract(contract)
                    return {"status": "PROCESSED", "result": res}
                else:
                    return {"status": "UP_TO_DATE", "code_sha": contract.code_sha}

        return {"status": "NO_CONTRACT_FOUND"}

    def _run_loop(self) -> None:
        while self._running:
            try:
                self.check_once()
            except Exception as e:
                logger.error("Watchdog iteration error: %s", e)
            time.sleep(self.interval_seconds)
