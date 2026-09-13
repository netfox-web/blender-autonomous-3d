"""Supervisor review engine orchestrating validation, locks, review, and GitHub writes."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from services.supervisor.ai_adapter import SupervisorProviderAdapter
from services.supervisor.config import SupervisorConfig
from services.supervisor.github_client import GitHubClientInterface, GitHubVerificationError
from services.supervisor.models import (
    ReadyForReGateContract,
    ReviewContext,
    ReviewDecision,
    SupervisorReviewOutput,
    SupervisorStatus,
)
from services.supervisor.policy import PolicyEngine
from services.supervisor.state import StateManager


class SupervisorEngine:
    """Core review coordinator implementing idempotency, verification, and writes."""

    def __init__(
        self,
        config: SupervisorConfig,
        state_mgr: StateManager,
        github_client: GitHubClientInterface,
        ai_adapter: SupervisorProviderAdapter,
        policy_engine: PolicyEngine,
    ) -> None:
        self.config = config
        self.state_mgr = state_mgr
        self.github_client = github_client
        self.ai_adapter = ai_adapter
        self.policy_engine = policy_engine

    def handle_ready_contract(
        self,
        contract: ReadyForReGateContract,
        delivery_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process an incoming READY_FOR_RE_GATE contract."""
        # 1. Target repository & issue checks
        if contract.repo.lower() != self.config.repo_name.lower():
            return {"status": "REJECTED", "reason": f"Wrong repo: {contract.repo}"}
        if contract.issue != self.config.allowed_issue_number:
            return {"status": "REJECTED", "reason": f"Wrong issue: {contract.issue}"}

        # 2. Idempotency check: same code_sha + evidence_generation_id
        if self.state_mgr.is_already_reviewed(contract.code_sha, contract.evidence_generation_id):
            return {
                "status": "IGNORE_DUPLICATE",
                "reason": f"Contract for {contract.code_sha} and {contract.evidence_generation_id} already reviewed.",
            }

        # 3. Loop protection: contract must offer fresh work
        state = self.state_mgr.get_state()
        if (
            state.last_reviewed_code_sha == contract.code_sha
            and state.last_processed_instruction_sha == contract.instruction_sha
        ):
            return {
                "status": "IGNORE_DUPLICATE",
                "reason": "Loop protection: same code SHA and instruction SHA already processed.",
            }

        # 4. Acquire durable lock
        review_id = f"rev_{uuid.uuid4().hex[:12]}"
        acquired, current_lock_holder_code = self.state_mgr.acquire_review_lock(
            review_id=review_id,
            code_sha=contract.code_sha,
        )
        if not acquired:
            if current_lock_holder_code == contract.code_sha:
                return {
                    "status": "IGNORE_DUPLICATE",
                    "reason": f"Review for {contract.code_sha} is currently in progress.",
                }
            # Different code SHA submitted while another review is running -> queue as pending newer evidence
            self.state_mgr.enqueue_pending_evidence(
                code_sha=contract.code_sha,
                evidence_generation_id=contract.evidence_generation_id,
                contract_json=contract.model_dump_json(),
            )
            return {
                "status": "PENDING_NEWER_EVIDENCE",
                "reason": f"Enqueued newer evidence {contract.code_sha} while review in progress.",
            }

        # 5. Start review
        self.state_mgr.start_review(
            review_id=review_id,
            code_sha=contract.code_sha,
            evidence_generation_id=contract.evidence_generation_id,
        )

        try:
            return self._execute_review(review_id, contract)
        except Exception as e:
            self.state_mgr.fail_review(review_id, str(e))
            self.state_mgr.release_review_lock(review_id)
            raise
        finally:
            self.state_mgr.release_review_lock(review_id)
            self._process_pending_queue_if_any()

    def _execute_review(
        self,
        review_id: str,
        contract: ReadyForReGateContract,
    ) -> Dict[str, Any]:
        # Step A: Verify CODE_SHA exists and is reachable on main
        self.state_mgr.set_status(SupervisorStatus.VALIDATING, active_review_id=review_id)
        if not self.github_client.verify_commit_on_main(contract.code_sha):
            raise GitHubVerificationError(
                f"CODE_SHA {contract.code_sha} is not reachable from {self.config.allowed_branch}."
            )

        # Step B: Verify DOCS_SHA is reachable on main
        if not self.github_client.verify_commit_on_main(contract.docs_sha):
            raise GitHubVerificationError(
                f"DOCS_SHA {contract.docs_sha} is not reachable from {self.config.allowed_branch}."
            )

        # Step C: Verify CI run (status, head_sha, ubuntu, windows)
        ci_summary = self.github_client.verify_ci_run(
            run_id=contract.ci_run_id,
            expected_code_sha=contract.code_sha,
        )

        # Step D: Read documentation and evidence files
        self.state_mgr.set_status(SupervisorStatus.REVIEWING, active_review_id=review_id)
        progress_report = self._safe_get_file("docs/GROK_PROGRESS_REPORT.md") or self._safe_get_file("docs/AGENT_PROGRESS_REPORT.md")
        audit_text = self._safe_get_file("docs/CURRENT_IMPLEMENTATION_AUDIT.md")
        acceptance_text = self._safe_get_file("docs/REAL_E2E_ACCEPTANCE.md")
        instruction_text = self._safe_get_file("docs/GROK_NEXT_PHASE_INSTRUCTIONS.md") or self._safe_get_file("docs/AGENT_NEXT_PHASE_INSTRUCTIONS.md")
        commits = self.github_client.get_commits_since(contract.instruction_sha, contract.docs_sha)

        # Step E: Build context and invoke AI review adapter
        context = ReviewContext(
            contract=contract,
            commits=commits,
            diffs="",
            progress_report_text=progress_report,
            audit_text=audit_text,
            acceptance_text=acceptance_text,
            ci_summary=ci_summary,
            instruction_text=instruction_text,
        )
        raw_output = self.ai_adapter.review_repository(context)

        # Step F: Enforce write policy and safety guardrails
        self.state_mgr.set_status(SupervisorStatus.WRITING_INSTRUCTIONS, active_review_id=review_id)
        output = self.policy_engine.enforce_output_policy(raw_output)

        new_instruction_sha = contract.instruction_sha

        # Step G: Execute GitHub writes based on decision
        if output.decision == ReviewDecision.ACCEPT_WITH_SCOPE:
            self.policy_engine.validate_action("update_next_instruction")
            new_instruction_sha = self.github_client.commit_instruction_file(
                file_path="docs/GROK_NEXT_PHASE_INSTRUCTIONS.md",
                content=output.next_instruction_markdown,
                commit_message=f"supervisor: accept {contract.code_sha[:7]} and start next-phase",
                branch=self.config.allowed_branch,
            )

            comment_body = (
                f"## SUPERVISOR_REVIEW_COMPLETE\n\n"
                f"DECISION=ACCEPT_WITH_SCOPE\n"
                f"REVIEWED_CODE_SHA={contract.code_sha}\n"
                f"NEXT_INSTRUCTION_SHA={new_instruction_sha}\n"
                f"EVIDENCE_GENERATION_ID={contract.evidence_generation_id}\n\n"
                f"{output.issue_comment_markdown}"
            )
            self.github_client.add_issue_comment(contract.issue, comment_body)

        elif output.decision == ReviewDecision.CHANGES_REQUIRED:
            self.policy_engine.validate_action("update_next_instruction")
            new_instruction_sha = self.github_client.commit_instruction_file(
                file_path="docs/GROK_NEXT_PHASE_INSTRUCTIONS.md",
                content=output.next_instruction_markdown,
                commit_message=f"supervisor: correction-only re-gate for {contract.code_sha[:7]}",
                branch=self.config.allowed_branch,
            )

            comment_body = (
                f"## SUPERVISOR_REVIEW_COMPLETE\n\n"
                f"DECISION=CHANGES_REQUIRED\n"
                f"REVIEWED_CODE_SHA={contract.code_sha}\n"
                f"NEXT_INSTRUCTION_SHA={new_instruction_sha}\n"
                f"EVIDENCE_GENERATION_ID={contract.evidence_generation_id}\n\n"
                f"{output.issue_comment_markdown}"
            )
            self.github_client.add_issue_comment(contract.issue, comment_body)

        elif output.decision == ReviewDecision.BLOCKED:
            comment_body = (
                f"## SUPERVISOR_REVIEW_COMPLETE\n\n"
                f"DECISION=BLOCKED\n"
                f"REVIEWED_CODE_SHA={contract.code_sha}\n"
                f"EVIDENCE_GENERATION_ID={contract.evidence_generation_id}\n\n"
                f"HUMAN_APPROVAL_REQUIRED\n\n"
                f"{output.issue_comment_markdown}"
            )
            self.github_client.add_issue_comment(contract.issue, comment_body)

        # Step H: Complete review in state
        self.state_mgr.complete_review(
            review_id=review_id,
            code_sha=contract.code_sha,
            docs_sha=contract.docs_sha,
            instruction_sha=new_instruction_sha,
            output=output,
        )

        return {
            "status": "COMPLETED",
            "review_id": review_id,
            "decision": output.decision.value,
            "new_instruction_sha": new_instruction_sha,
        }

    def _safe_get_file(self, path: str) -> str:
        try:
            return self.github_client.get_file_content(path, ref=self.config.allowed_branch)
        except Exception:
            return ""

    def _process_pending_queue_if_any(self) -> None:
        pending = self.state_mgr.pop_latest_pending()
        if not pending:
            return
        try:
            contract = ReadyForReGateContract.model_validate_json(pending["contract_json"])
            self.handle_ready_contract(contract)
        except Exception:
            pass
