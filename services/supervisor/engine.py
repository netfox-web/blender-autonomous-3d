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

        # Step C: Verify dual CI runs (status, head_sha, ubuntu, windows)
        code_run_id = contract.code_ci_run_id or contract.ci_run_id
        if not code_run_id:
            raise GitHubVerificationError("Missing CODE_CI_RUN_ID in READY_FOR_RE_GATE contract.")
        code_ci_summary = self.github_client.verify_ci_run(
            run_id=code_run_id,
            expected_code_sha=contract.code_sha,
        )

        docs_ci_summary: Dict[str, Any] = {}
        if not contract.docs_ci_run_id:
            if self.config.mode.lower() == "live":
                raise GitHubVerificationError("Live mode requires explicit DOCS_CI_RUN_ID in READY_FOR_RE_GATE contract.")
        else:
            docs_ci_summary = self.github_client.verify_ci_run(
                run_id=contract.docs_ci_run_id,
                expected_code_sha=contract.docs_sha,
            )

        # Step D: Read documentation and evidence files from exact pinned refs
        self.state_mgr.set_status(SupervisorStatus.REVIEWING, active_review_id=review_id)
        progress_report = (
            self._safe_get_file("docs/GROK_PROGRESS_REPORT.md", ref=contract.docs_sha)
            or self._safe_get_file("docs/AGENT_PROGRESS_REPORT.md", ref=contract.docs_sha)
        )
        audit_text = self._safe_get_file("docs/CURRENT_IMPLEMENTATION_AUDIT.md", ref=contract.docs_sha)
        acceptance_text = self._safe_get_file("docs/REAL_E2E_ACCEPTANCE.md", ref=contract.docs_sha)
        cabinet_acceptance_text = self._safe_get_file("docs/CABINET_REAL_ACCEPTANCE.md", ref=contract.docs_sha)
        event_driven_acceptance_text = self._safe_get_file("docs/EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md", ref=contract.docs_sha)
        instruction_text = (
            self._safe_get_file("docs/GROK_NEXT_PHASE_INSTRUCTIONS.md", ref=contract.instruction_sha)
            or self._safe_get_file("docs/AGENT_NEXT_PHASE_INSTRUCTIONS.md", ref=contract.instruction_sha)
        )
        commits = self.github_client.get_commits_since(contract.instruction_sha, contract.docs_sha)
        diffs = self.github_client.get_diff_between(contract.instruction_sha, contract.docs_sha)

        # Step E: Build context and invoke AI review adapter
        context = ReviewContext(
            contract=contract,
            commits=commits,
            diffs=diffs,
            progress_report_text=progress_report,
            audit_text=audit_text,
            acceptance_text=acceptance_text,
            cabinet_acceptance_text=cabinet_acceptance_text,
            event_driven_acceptance_text=event_driven_acceptance_text,
            ci_summary=code_ci_summary,
            code_ci_summary=code_ci_summary,
            docs_ci_summary=docs_ci_summary,
            instruction_text=instruction_text,
        )
        raw_output = self.ai_adapter.review_repository(context)

        # Independent verification of provider output against contract
        if raw_output.reviewed_code_sha != contract.code_sha:
            logger.warning(
                "Provider returned mismatched CODE SHA %s (expected %s). Failing closed.",
                raw_output.reviewed_code_sha, contract.code_sha,
            )
            raw_output.decision = ReviewDecision.CHANGES_REQUIRED
            raw_output.blockers.append(
                f"Provider output reviewed_code_sha ({raw_output.reviewed_code_sha}) does not match contract ({contract.code_sha})."
            )

        if raw_output.reviewed_evidence_generation_id != contract.evidence_generation_id:
            logger.warning(
                "Provider returned mismatched evidence generation ID %s (expected %s). Failing closed.",
                raw_output.reviewed_evidence_generation_id, contract.evidence_generation_id,
            )
            raw_output.decision = ReviewDecision.CHANGES_REQUIRED
            raw_output.blockers.append(
                f"Provider output reviewed_evidence_generation_id ({raw_output.reviewed_evidence_generation_id}) does not match contract ({contract.evidence_generation_id})."
            )

        if contract.used_mock and "Real Blender Cycles OptiX" in raw_output.truth_matrix.get("REAL", []):
            logger.warning("Provider attempted to promote mock execution to REAL. Downgrading to CHANGES_REQUIRED.")
            raw_output.decision = ReviewDecision.CHANGES_REQUIRED
            raw_output.blockers.append("Provider invalidly promoted mock execution to Production Ready REAL.")

        # Step F: Enforce write policy and safety guardrails
        self.state_mgr.set_status(SupervisorStatus.WRITING_INSTRUCTIONS, active_review_id=review_id)
        output = self.policy_engine.enforce_output_policy(raw_output)

        marker = (
            f"<!-- REVIEW_MARKER: CODE_SHA={contract.code_sha} "
            f"EVIDENCE_ID={contract.evidence_generation_id} REVIEW_ID={review_id} -->"
        )
        new_instruction_sha = contract.instruction_sha

        # Step G: Execute GitHub writes based on decision
        if output.decision in (ReviewDecision.ACCEPT_WITH_SCOPE, ReviewDecision.CHANGES_REQUIRED):
            self.policy_engine.validate_action("update_next_instruction")

            # Window B1 check: staged commit in DB or matching remote commit
            staged_sha = self.state_mgr.get_staged_commit(contract.code_sha, contract.evidence_generation_id)
            if staged_sha:
                new_instruction_sha = staged_sha
            else:
                expected_tag = contract.code_sha[:7]
                remote_commits = self.github_client.get_commits_since(
                    contract.instruction_sha, f"origin/{self.config.allowed_branch}"
                )
                adopted_sha = None
                for c in remote_commits:
                    msg = c.get("message") or (c.get("commit", {}).get("message") if isinstance(c.get("commit"), dict) else "") or ""
                    if "supervisor:" in msg and expected_tag in msg:
                        adopted_sha = c.get("sha")
                        break

                if adopted_sha:
                    new_instruction_sha = adopted_sha
                    self.state_mgr.record_instruction_pushed(review_id, new_instruction_sha)
                else:
                    commit_msg = (
                        f"supervisor: accept {contract.code_sha[:7]} and start next-phase"
                        if output.decision == ReviewDecision.ACCEPT_WITH_SCOPE
                        else f"supervisor: correction-only re-gate for {contract.code_sha[:7]}"
                    )
                    new_instruction_sha = self.github_client.commit_instruction_file(
                        file_path="docs/GROK_NEXT_PHASE_INSTRUCTIONS.md",
                        content=output.next_instruction_markdown,
                        commit_message=commit_msg,
                        branch=self.config.allowed_branch,
                    )
                    self.state_mgr.record_instruction_pushed(review_id, new_instruction_sha)

            # Window B2 check: has comment already been posted?
            rev_record = self.state_mgr.get_review_by_contract(contract.code_sha, contract.evidence_generation_id)
            already_commented = rev_record and rev_record.get("issue_comment_id")
            if not already_commented:
                recent_comments = self.github_client.get_latest_issue_comments(contract.issue, count=20)
                adopted_comment_id = None
                for comm in recent_comments:
                    body = comm.get("body", "")
                    if f"CODE_SHA={contract.code_sha}" in body and f"EVIDENCE_ID={contract.evidence_generation_id}" in body:
                        adopted_comment_id = str(comm.get("id", ""))
                        break

                if adopted_comment_id:
                    self.state_mgr.record_comment_posted(review_id, adopted_comment_id)
                else:
                    comment_body = (
                        f"## SUPERVISOR_REVIEW_COMPLETE\n\n"
                        f"{marker}\n"
                        f"DECISION={output.decision.value}\n"
                        f"REVIEWED_CODE_SHA={contract.code_sha}\n"
                        f"NEXT_INSTRUCTION_SHA={new_instruction_sha}\n"
                        f"EVIDENCE_GENERATION_ID={contract.evidence_generation_id}\n\n"
                        f"{output.issue_comment_markdown}"
                    )
                    comment_id = self.github_client.add_issue_comment(contract.issue, comment_body)
                    self.state_mgr.record_comment_posted(review_id, comment_id)

        elif output.decision == ReviewDecision.BLOCKED:
            comment_body = (
                f"## SUPERVISOR_REVIEW_COMPLETE\n\n"
                f"{marker}\n"
                f"DECISION=BLOCKED\n"
                f"REVIEWED_CODE_SHA={contract.code_sha}\n"
                f"EVIDENCE_GENERATION_ID={contract.evidence_generation_id}\n\n"
                f"HUMAN_APPROVAL_REQUIRED\n\n"
                f"{output.issue_comment_markdown}"
            )
            comment_id = self.github_client.add_issue_comment(contract.issue, comment_body)
            self.state_mgr.record_comment_posted(review_id, comment_id)

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

    def _safe_get_file(self, path: str, ref: Optional[str] = None) -> str:
        try:
            target_ref = ref or self.config.allowed_branch
            return self.github_client.get_file_content(path, ref=target_ref)
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
