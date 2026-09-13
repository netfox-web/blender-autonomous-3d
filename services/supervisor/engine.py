"""Supervisor review engine orchestrating validation, locks, review, and GitHub writes."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("supervisor.engine")

from services.supervisor.ai_adapter import SupervisorProviderAdapter
from services.supervisor.config import SupervisorConfig
from services.supervisor.github_client import GitHubClientInterface, GitHubVerificationError
from services.supervisor.models import (
    ChangedFileItem,
    EvidenceSectionCompleteness,
    ReadyForReGateContract,
    ReviewContext,
    ReviewDecision,
    SupervisorReviewOutput,
    SupervisorStatus,
)
from services.supervisor.policy import PolicyEngine
from services.supervisor.state import StateManager


def parse_diff_changed_files(diff_text: str) -> List[ChangedFileItem]:
    """Parse unified diff or name-status into ChangedFileItem records with status (A/M/D/R)."""
    items: List[ChangedFileItem] = []
    current_status = "M"
    current_path = ""
    current_old_path = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git a/") and " b/" in line:
            if current_path:
                items.append(ChangedFileItem(status=current_status, path=current_path, old_path=current_old_path))
            parts = line.split(" b/")
            current_path = parts[1].strip()
            current_status = "M"
            current_old_path = None
        elif line.startswith("new file mode"):
            current_status = "A"
        elif line.startswith("deleted file mode"):
            current_status = "D"
        elif line.startswith("rename from "):
            current_status = "R"
            current_old_path = line[len("rename from "):].strip()
        elif line.startswith("rename to "):
            current_path = line[len("rename to "):].strip()
        elif line.startswith(("M\t", "A\t", "D\t")):
            parts = line.split("\t")
            if len(parts) >= 2:
                items.append(ChangedFileItem(status=parts[0].strip(), path=parts[1].strip()))
        elif line.startswith("R") and "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 3:
                items.append(ChangedFileItem(status="R", path=parts[2].strip(), old_path=parts[1].strip()))

    if current_path:
        items.append(ChangedFileItem(status=current_status, path=current_path, old_path=current_old_path))
    return items


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

    def _fetch_evidence_file(self, path: str, ref: Optional[str] = None) -> Tuple[str, str]:
        """
        Fetches file content from GitHub with typed status.
        Returns: (content: str, status: str)
        where status is 'OK', 'NOT_FOUND_404', 'EMPTY_CONTENT', 'TIMEOUT', 'AUTH_FAILURE', or 'FETCH_ERROR: ...'
        """
        try:
            target_ref = ref or self.config.allowed_branch
            content = self.github_client.get_file_content(path, ref=target_ref)
            if not content or not content.strip():
                return "", "EMPTY_CONTENT"
            return content, "OK"
        except Exception as e:
            err_str = str(e).lower()
            if "404" in err_str or "not found" in err_str:
                return "", "NOT_FOUND_404"
            elif "timeout" in err_str:
                return "", "TIMEOUT"
            elif "auth" in err_str or "401" in err_str or "403" in err_str:
                return "", "AUTH_FAILURE"
            return "", f"FETCH_ERROR: {e}"

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

        # 3. Idempotency check: same code_sha + evidence_generation_id
        if self.state_mgr.is_already_reviewed(contract.code_sha, contract.evidence_generation_id):
            return {
                "status": "IGNORE_DUPLICATE",
                "reason": f"Contract for {contract.code_sha} and {contract.evidence_generation_id} already reviewed.",
            }

        # 4. Loop protection: contract must offer fresh work
        state = self.state_mgr.get_state()
        if (
            state.last_reviewed_code_sha == contract.code_sha
            and state.last_processed_instruction_sha == contract.instruction_sha
        ):
            return {
                "status": "IGNORE_DUPLICATE",
                "reason": "Loop protection: same code SHA and instruction SHA already processed.",
            }

        # 5. Acquire durable lock
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

        # 6. Start review
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
        fetch_statuses: Dict[str, str] = {}

        # 1. Pinned instruction text
        instruction_text, status = self._fetch_evidence_file("docs/GROK_NEXT_PHASE_INSTRUCTIONS.md", ref=contract.instruction_sha)
        if status != "OK":
            instruction_text, status = self._fetch_evidence_file("docs/AGENT_NEXT_PHASE_INSTRUCTIONS.md", ref=contract.instruction_sha)
            fetch_statuses["docs/AGENT_NEXT_PHASE_INSTRUCTIONS.md"] = status
        else:
            fetch_statuses["docs/GROK_NEXT_PHASE_INSTRUCTIONS.md"] = status

        # 2. Pinned progress report
        progress_report, status = self._fetch_evidence_file("docs/GROK_PROGRESS_REPORT.md", ref=contract.docs_sha)
        if status != "OK":
            progress_report, status = self._fetch_evidence_file("docs/AGENT_PROGRESS_REPORT.md", ref=contract.docs_sha)
            fetch_statuses["docs/AGENT_PROGRESS_REPORT.md"] = status
        else:
            fetch_statuses["docs/GROK_PROGRESS_REPORT.md"] = status

        # 3. Pinned implementation audit
        audit_text, status = self._fetch_evidence_file("docs/CURRENT_IMPLEMENTATION_AUDIT.md", ref=contract.docs_sha)
        fetch_statuses["docs/CURRENT_IMPLEMENTATION_AUDIT.md"] = status

        # 4. Pinned supervisor acceptance
        event_driven_acceptance_text, status = self._fetch_evidence_file("docs/EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md", ref=contract.docs_sha)
        fetch_statuses["docs/EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md"] = status

        # 5. Real blender acceptance (mandatory if real_blender and not used_mock)
        real_acc_path = "docs/REAL_E2E_ACCEPTANCE.md"
        acceptance_text, status = self._fetch_evidence_file(real_acc_path, ref=contract.docs_sha)
        if status != "OK":
            real_acc_path = "docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.md"
            acceptance_text, status = self._fetch_evidence_file(real_acc_path, ref=contract.docs_sha)
        fetch_statuses[real_acc_path] = status

        # 6. Optional cabinet acceptance
        cabinet_acceptance_text, status = self._fetch_evidence_file("docs/CABINET_REAL_ACCEPTANCE.md", ref=contract.docs_sha)
        fetch_statuses["docs/CABINET_REAL_ACCEPTANCE.md"] = status

        # Fail closed BEFORE provider call if any required pinned evidence is missing, empty, or failed fetch
        required_failures = []
        if fetch_statuses.get("docs/GROK_NEXT_PHASE_INSTRUCTIONS.md") != "OK" and fetch_statuses.get("docs/AGENT_NEXT_PHASE_INSTRUCTIONS.md") != "OK":
            required_failures.append(f"Instruction text at pinned {contract.instruction_sha} failed: {fetch_statuses.get('docs/GROK_NEXT_PHASE_INSTRUCTIONS.md') or fetch_statuses.get('docs/AGENT_NEXT_PHASE_INSTRUCTIONS.md')}")
        if fetch_statuses.get("docs/GROK_PROGRESS_REPORT.md") != "OK" and fetch_statuses.get("docs/AGENT_PROGRESS_REPORT.md") != "OK":
            required_failures.append("Progress report at pinned DOCS_SHA failed or missing")
        if fetch_statuses.get("docs/CURRENT_IMPLEMENTATION_AUDIT.md") != "OK":
            required_failures.append(f"Implementation audit failed: {fetch_statuses.get('docs/CURRENT_IMPLEMENTATION_AUDIT.md')}")
        if fetch_statuses.get("docs/EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md") != "OK":
            required_failures.append(f"Supervisor acceptance report failed: {fetch_statuses.get('docs/EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md')}")
        if contract.real_blender and not contract.used_mock and fetch_statuses.get(real_acc_path) != "OK":
            required_failures.append(f"Real Blender acceptance report failed: {fetch_statuses.get(real_acc_path)}")

        commits = self.github_client.get_commits_since(contract.instruction_sha, contract.docs_sha)
        diffs = self.github_client.get_diff_between(contract.instruction_sha, contract.docs_sha)

        # Extract changed files from diffs
        changed_file_items = parse_diff_changed_files(diffs)
        changed_files = [item.format_entry() for item in changed_file_items]

        if required_failures:
            logger.warning("Required evidence fetch failed: %s. Failing closed without calling AI provider.", required_failures)
            raw_output = SupervisorReviewOutput(
                decision=ReviewDecision.CHANGES_REQUIRED,
                reviewed_code_sha=contract.code_sha,
                reviewed_docs_sha=contract.docs_sha,
                reviewed_instruction_sha=contract.instruction_sha,
                reviewed_evidence_generation_id=contract.evidence_generation_id,
                blockers=required_failures,
                next_instruction_markdown="# Phase Re-Gate: Changes Required\nRequired evidence fetch failed.",
                issue_comment_markdown="## SUPERVISOR_REVIEW_COMPLETE\nDECISION=CHANGES_REQUIRED\nRequired pinned evidence fetch failed before calling AI provider.",
                audit_trail={"fetch_statuses": fetch_statuses},
            )
            context = None
        else:
            # Step E: Build context and invoke AI review adapter
            context = ReviewContext(
                contract=contract,
                commits=commits,
                diffs=diffs,
                changed_files=changed_files,
                changed_file_items=changed_file_items,
                fetch_statuses=fetch_statuses,
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

        if raw_output.reviewed_docs_sha != contract.docs_sha:
            logger.warning(
                "Provider returned mismatched DOCS SHA %s (expected %s). Failing closed.",
                raw_output.reviewed_docs_sha, contract.docs_sha,
            )
            raw_output.decision = ReviewDecision.CHANGES_REQUIRED
            raw_output.blockers.append(
                f"Provider output reviewed_docs_sha ({raw_output.reviewed_docs_sha}) does not match contract ({contract.docs_sha})."
            )

        if raw_output.reviewed_instruction_sha != contract.instruction_sha:
            logger.warning(
                "Provider returned mismatched INSTRUCTION SHA %s (expected %s). Failing closed.",
                raw_output.reviewed_instruction_sha, contract.instruction_sha,
            )
            raw_output.decision = ReviewDecision.CHANGES_REQUIRED
            raw_output.blockers.append(
                f"Provider output reviewed_instruction_sha ({raw_output.reviewed_instruction_sha}) does not match contract ({contract.instruction_sha})."
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

        # Independent check: critical changed files manifest completeness
        actual_diff_paths = {item.path for item in changed_file_items}
        manifest_paths = {item.path for item in context.changed_file_items} if (context and context.changed_file_items) else actual_diff_paths
        omitted_changed_files = actual_diff_paths - manifest_paths
        if omitted_changed_files and raw_output.decision == ReviewDecision.ACCEPT_WITH_SCOPE:
            logger.warning("Critical changed files omitted from manifest: %s. Failing closed.", omitted_changed_files)
            raw_output.decision = ReviewDecision.CHANGES_REQUIRED
            raw_output.blockers.append(f"Changed files manifest omitted critical changed files: {sorted(omitted_changed_files)}.")

        # Independent check: critical evidence section completeness
        if context and any(c.critical and c.truncated and not c.is_complete for c in context.completeness) and raw_output.decision == ReviewDecision.ACCEPT_WITH_SCOPE:
            logger.warning("Critical evidence section truncated without full completeness coverage. Downgrading to CHANGES_REQUIRED.")
            raw_output.decision = ReviewDecision.CHANGES_REQUIRED
            raw_output.blockers.append("Critical evidence section is truncated without full completeness coverage. ACCEPT not permitted.")

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
                remote_commits = self.github_client.get_commits_since(
                    contract.instruction_sha, f"origin/{self.config.allowed_branch}"
                )
                matching_candidates: List[str] = []
                for c in remote_commits:
                    msg = c.get("message") or (c.get("commit", {}).get("message") if isinstance(c.get("commit"), dict) else "") or ""
                    msg_lower = msg.lower()

                    has_code = f"Reviewed-Code-Sha: {contract.code_sha}".lower() in msg_lower or f"Reviewed: {contract.code_sha}".lower() in msg_lower or f"code {contract.code_sha[:7]}".lower() in msg_lower
                    has_ev = f"Reviewed-Evidence-Id: {contract.evidence_generation_id}".lower() in msg_lower or f"Evidence-ID: {contract.evidence_generation_id}".lower() in msg_lower or f"evidence_id={contract.evidence_generation_id}".lower() in msg_lower

                    if has_code and has_ev:
                        # Check full trailers if present in commit message
                        if "reviewed-docs-sha:" in msg_lower and f"Reviewed-Docs-Sha: {contract.docs_sha}".lower() not in msg_lower:
                            continue
                        if "reviewed-instruction-sha:" in msg_lower and f"Reviewed-Instruction-Sha: {contract.instruction_sha}".lower() not in msg_lower:
                            continue
                        if "supervisor-decision:" in msg_lower and f"Supervisor-Decision: {output.decision.value}".lower() not in msg_lower:
                            continue

                        # Also verify remote blob content marker if file content exists
                        try:
                            blob = self.github_client.get_file_content("docs/GROK_NEXT_PHASE_INSTRUCTIONS.md", ref=c.get("sha"))
                            if blob and f"EVIDENCE_GENERATION_ID={contract.evidence_generation_id}" in blob:
                                if f"CODE_SHA={contract.code_sha}" not in blob:
                                    continue
                        except Exception:
                            pass

                        matching_candidates.append(c.get("sha"))

                if len(matching_candidates) > 1:
                    logger.error("Multiple matching instruction commit candidates found: %s. Failing closed.", matching_candidates)
                    raise GitHubVerificationError(f"Multiple matching remote instruction commits found: {matching_candidates}. Refusing to guess.")
                elif len(matching_candidates) == 1:
                    new_instruction_sha = matching_candidates[0]
                    self.state_mgr.record_instruction_pushed(review_id, new_instruction_sha)
                else:
                    commit_trailers = (
                        f"\n\nReviewed-Code-Sha: {contract.code_sha}\n"
                        f"Reviewed-Docs-Sha: {contract.docs_sha}\n"
                        f"Reviewed-Instruction-Sha: {contract.instruction_sha}\n"
                        f"Reviewed-Evidence-Id: {contract.evidence_generation_id}\n"
                        f"Supervisor-Decision: {output.decision.value}\n"
                        f"Supervisor-Review-Id: {review_id}"
                    )
                    commit_msg = (
                        f"supervisor: accept {contract.code_sha[:7]} and start next-phase{commit_trailers}"
                        if output.decision == ReviewDecision.ACCEPT_WITH_SCOPE
                        else f"supervisor: correction-only re-gate for {contract.code_sha[:7]}{commit_trailers}"
                    )
                    content_marker = (
                        f"\n\n<!-- SUPERVISOR_COMMIT_IDENTITY:\n"
                        f"CODE_SHA={contract.code_sha}\n"
                        f"DOCS_SHA={contract.docs_sha}\n"
                        f"INSTRUCTION_SHA={contract.instruction_sha}\n"
                        f"EVIDENCE_GENERATION_ID={contract.evidence_generation_id}\n"
                        f"DECISION={output.decision.value}\n"
                        f"REVIEW_ID={review_id}\n"
                        f"-->\n"
                    )
                    new_instruction_sha = self.github_client.commit_instruction_file(
                        file_path="docs/GROK_NEXT_PHASE_INSTRUCTIONS.md",
                        content=output.next_instruction_markdown + content_marker,
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
            # Window B2 check for BLOCKED decision: idempotent comment adoption
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
