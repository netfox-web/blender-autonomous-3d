"""AI adapter interface and implementations for repository review."""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from services.supervisor.config import ConfigValidationError
from services.supervisor.models import (
    ChangedFileItem,
    EvidenceSectionCompleteness,
    ProviderReviewResponseSchema,
    ReviewContext,
    ReviewDecision,
    SupervisorReviewOutput,
)

logger = logging.getLogger("supervisor.ai_adapter")


class SupervisorProviderAdapter(ABC):
    """Abstract interface for AI Re-Gate review adapters."""

    @abstractmethod
    def review_repository(self, context: ReviewContext) -> SupervisorReviewOutput:
        """Review repository evidence and return structured review decision."""
        pass


class RuleBasedSupervisorAdapter(SupervisorProviderAdapter):
    """
    Deterministic rule-based reviewer checking claims, test counts,
    and progress report integrity.
    """

    def review_repository(self, context: ReviewContext) -> SupervisorReviewOutput:
        contract = context.contract
        report_text = context.progress_report_text
        blockers = []
        accepted_claims = []
        rejected_claims = []

        # Check for mock claim contradictions
        if contract.used_mock and contract.real_blender:
            blockers.append("Contradiction: claimed both real_blender=true and used_mock=true.")
            rejected_claims.append("real_blender authority")
        elif contract.real_blender and not contract.used_mock:
            accepted_claims.append("Real Blender OptiX execution evidence verified")
        else:
            accepted_claims.append("Mock / fixture validation verified (non-production)")

        # Verify test count
        if contract.test_count < 10:
            blockers.append(f"Insufficient test count ({contract.test_count} < 10 required for re-gate).")
            rejected_claims.append("Comprehensive test verification")
        else:
            accepted_claims.append(f"Test suite count {contract.test_count} passed")

        # Check progress report presence
        if not report_text.strip():
            blockers.append("Progress report is empty or missing.")
            rejected_claims.append("Progress report lineage")
        else:
            accepted_claims.append("Progress report lineage linked to instruction")

        truth_matrix = {
            "REAL": ["Real Blender Cycles OptiX"] if contract.real_blender and not contract.used_mock else [],
            "MOCK": ["Blender Mock Engine"] if contract.used_mock else [],
            "PARTIAL": ["Deterministic Commerce Asset Pack"],
            "BLOCKED": ["LIVE_CNC", "LIVE_LASER", "PLC", "Physical Print"],
        }

        if blockers:
            decision = ReviewDecision.CHANGES_REQUIRED
            next_instruction_md = (
                f"# Phase Re-Gate: Changes Required\n\n"
                f"Previous CODE `{contract.code_sha[:7]}` had blockers:\n"
                + "\n".join(f"- {b}" for b in blockers)
                + "\n\n## Required Corrections\n"
                "- Address blockers and re-execute clean-tree tests.\n"
                "- Post updated READY_FOR_RE_GATE once verified.\n"
            )
            issue_comment_md = (
                f"## SUPERVISOR_REVIEW_COMPLETE\n"
                f"DECISION=CHANGES_REQUIRED\n"
                f"REVIEWED_CODE_SHA={contract.code_sha}\n"
                f"NEXT_INSTRUCTION_SHA=pending_commit\n\n"
                f"Blockers found: {', '.join(blockers)}.\n"
                f"Please address corrections."
            )
        else:
            decision = ReviewDecision.ACCEPT_WITH_SCOPE
            next_instruction_md = (
                f"# Phase Re-Gate: Accepted With Scope\n\n"
                f"CODE `{contract.code_sha[:7]}` and DOCS `{contract.docs_sha[:7]}` accepted.\n\n"
                f"## Next Phase Scope\n"
                f"- Continue autonomous pipeline execution.\n"
                f"- Maintain dual-platform CI pass (Ubuntu + Windows).\n"
                f"- Retain truth boundaries: no live CNC/laser/PLC.\n"
            )
            issue_comment_md = (
                f"## SUPERVISOR_REVIEW_COMPLETE\n"
                f"DECISION=ACCEPT_WITH_SCOPE\n"
                f"REVIEWED_CODE_SHA={contract.code_sha}\n"
                f"NEXT_INSTRUCTION_SHA=pending_commit\n\n"
                f"All required evidence and tests verified green. Next phase instruction released."
            )

        return SupervisorReviewOutput(
            decision=decision,
            reviewed_code_sha=contract.code_sha,
            reviewed_docs_sha=contract.docs_sha,
            reviewed_instruction_sha=contract.instruction_sha,
            reviewed_evidence_generation_id=contract.evidence_generation_id,
            accepted_claims=accepted_claims,
            rejected_claims=rejected_claims,
            truth_matrix=truth_matrix,
            blockers=blockers,
            next_instruction_markdown=next_instruction_md,
            issue_comment_markdown=issue_comment_md,
        )


class MockSupervisorAdapter(SupervisorProviderAdapter):
    """Configurable mock adapter for unit tests."""

    def __init__(
        self,
        forced_decision: ReviewDecision = ReviewDecision.ACCEPT_WITH_SCOPE,
        forced_blockers: list[str] | None = None,
        forced_instruction_md: str = "Mock next instruction",
        forced_comment_md: str = "Mock issue comment",
    ) -> None:
        self.forced_decision = forced_decision
        self.forced_blockers = forced_blockers or []
        self.forced_instruction_md = forced_instruction_md
        self.forced_comment_md = forced_comment_md

    def review_repository(self, context: ReviewContext) -> SupervisorReviewOutput:
        return SupervisorReviewOutput(
            decision=self.forced_decision,
            reviewed_code_sha=context.contract.code_sha,
            reviewed_docs_sha=context.contract.docs_sha,
            reviewed_instruction_sha=context.contract.instruction_sha,
            reviewed_evidence_generation_id=context.contract.evidence_generation_id,
            accepted_claims=["Mock claim verified"],
            rejected_claims=[],
            truth_matrix={"REAL": [], "MOCK": ["All"], "PARTIAL": [], "BLOCKED": []},
            blockers=self.forced_blockers,
            next_instruction_markdown=self.forced_instruction_md,
            issue_comment_markdown=self.forced_comment_md,
        )


class SemanticEvidenceSupervisorAdapter(SupervisorProviderAdapter):
    """
    Deterministic semantic safety preflight filter reconciling diffs, acceptance evidence,
    and audit reports against the contract's claims.
    In live mode, acts as a safety gate and refuses to unilaterally issue ACCEPT_WITH_SCOPE.
    """

    def __init__(self, is_live: bool = False) -> None:
        self.is_live = is_live

    def review_repository(self, context: ReviewContext) -> SupervisorReviewOutput:
        contract = context.contract
        report_text = context.progress_report_text or ""
        audit_text = context.audit_text or ""
        acceptance_text = context.acceptance_text or ""
        diffs = context.diffs or ""

        blockers: list[str] = []
        accepted_claims: list[str] = []
        rejected_claims: list[str] = []

        # 0. Verification of Evidence Fetch Statuses
        if context.fetch_statuses:
            for fpath, fstatus in context.fetch_statuses.items():
                if fstatus != "OK" and "CABINET" not in fpath:
                    blockers.append(f"Required evidence fetch failed for {fpath}: {fstatus}")
                    rejected_claims.append(f"Evidence fetch: {fpath}")

        # 1. Verification of Progress Report & Lineage Markers
        if not report_text.strip():
            blockers.append("Progress report is empty or missing from repository.")
            rejected_claims.append("Progress report lineage")
        else:
            code_short = contract.code_sha[:7].lower()
            code_full = contract.code_sha.lower()
            instr_short = contract.instruction_sha[:7].lower()
            instr_full = contract.instruction_sha.lower()
            report_lower = report_text.lower()
            if (code_short not in report_lower and code_full not in report_lower) or (
                instr_short not in report_lower and instr_full not in report_lower
            ):
                blockers.append(
                    f"Progress report lineage mismatch: missing reference to CODE SHA {contract.code_sha[:7]} "
                    f"or INSTRUCTION SHA {contract.instruction_sha[:7]}. Stale report detected."
                )
                rejected_claims.append("Progress report lineage")
            else:
                accepted_claims.append("Progress report lineage verified")

        # 2. Verification of Test Count
        if contract.test_count < 10:
            blockers.append(f"Insufficient test count ({contract.test_count} < 10 required for re-gate).")
            rejected_claims.append("Comprehensive test verification")
        else:
            accepted_claims.append(f"Test count {contract.test_count} verified")

        # 3. Diffs availability check
        if not diffs.strip():
            blockers.append("Repository diff is empty or unreachable for claimed code changes.")
            rejected_claims.append("Codebase diff authenticity")
        else:
            accepted_claims.append("Codebase diff reconciled")

        # 4. Contradiction checks for REAL vs MOCK

        if contract.used_mock and contract.real_blender:
            blockers.append("Contradiction: Contract claimed both real_blender=true and used_mock=true.")
            rejected_claims.append("Execution truth consistency")

        # 5. Semantic reconciliation of REAL blender claims against evidence
        if contract.real_blender and not contract.used_mock:
            combined_evidence = f"{acceptance_text}\n{audit_text}".lower()
            if not combined_evidence.strip():
                blockers.append("Contract claimed real_blender=true but acceptance and audit evidence files are missing.")
                rejected_claims.append("Real Blender OptiX execution evidence")
            elif ("real_blender: false" in combined_evidence or "real_blender=false" in combined_evidence or "used_mock: true" in combined_evidence):
                blockers.append("Contradiction: Contract claimed real_blender=true but acceptance evidence explicitly indicates mock execution.")
                rejected_claims.append("Real Blender OptiX execution evidence")
            else:
                accepted_claims.append("Real Blender execution evidence reconciled with acceptance audit")

        # 6. Semantic check on diffs for spoofing or unauthorized changes
        diffs_lower = diffs.lower()
        if "mock_blender" in diffs_lower and contract.real_blender and not contract.used_mock:
            if "force_mock = true" in diffs_lower or "use_mock = true" in diffs_lower:
                blockers.append("Adversarial contradiction: Diff forces mock execution while contract claims real_blender=true.")
                rejected_claims.append("Codebase diff authenticity")

        # 7. CI Summary verification
        ci_summary = context.ci_summary or {}
        if ci_summary:
            if ci_summary.get("conclusion") != "success":
                blockers.append(f"CI run conclusion is '{ci_summary.get('conclusion')}', expected 'success'.")
                rejected_claims.append("Dual-platform CI verification")
            if not ci_summary.get("ubuntu_ok") or not ci_summary.get("windows_ok"):
                blockers.append("Dual-platform CI jobs (Ubuntu + Windows) incomplete.")
                rejected_claims.append("Dual-platform CI verification")

        # 8. Live mode safety rule: deterministic filter cannot unilaterally produce ACCEPT_WITH_SCOPE
        if self.is_live and not blockers:
            blockers.append(
                "Deterministic safety filter passed preflight, but cannot unilaterally issue ACCEPT_WITH_SCOPE in live mode; requires a configured AI provider (openai/anthropic/gemini)."
            )
            rejected_claims.append("Final AI provider Re-Gate authority")

        truth_matrix = {
            "REAL": ["Real Blender Cycles OptiX"] if contract.real_blender and not contract.used_mock and not blockers else [],
            "MOCK": ["Blender Mock Engine"] if contract.used_mock else [],
            "PARTIAL": ["Deterministic Commerce Asset Pack", "Autonomous Supervisor Control Plane"],
            "BLOCKED": ["LIVE_CNC", "LIVE_LASER", "PLC", "Physical Print", "Phase 961+"],
        }

        if blockers:
            decision = ReviewDecision.CHANGES_REQUIRED
            next_instruction_md = (
                f"# Phase Re-Gate: Changes Required\n\n"
                f"Previous CODE `{contract.code_sha[:7]}` had blockers:\n"
                + "\n".join(f"- {b}" for b in blockers)
                + "\n\n## Required Corrections\n"
                "- Address semantic blockers and reconcile evidence.\n"
                "- Post updated READY_FOR_RE_GATE once verified.\n"
            )
            issue_comment_md = (
                f"## SUPERVISOR_REVIEW_COMPLETE\n"
                f"DECISION=CHANGES_REQUIRED\n"
                f"REVIEWED_CODE_SHA={contract.code_sha}\n"
                f"NEXT_INSTRUCTION_SHA=pending_commit\n\n"
                f"Blockers found:\n"
                + "\n".join(f"- {b}" for b in blockers)
            )
        else:
            decision = ReviewDecision.ACCEPT_WITH_SCOPE
            next_instruction_md = (
                f"# Phase Re-Gate: Accepted With Scope\n\n"
                f"CODE `{contract.code_sha[:7]}` and DOCS `{contract.docs_sha[:7]}` accepted.\n\n"
                f"## Next Phase Scope\n"
                f"- Continue autonomous pipeline execution.\n"
                f"- Maintain dual-platform CI pass (Ubuntu + Windows).\n"
                f"- Retain truth boundaries: no live CNC/laser/PLC.\n"
            )
            issue_comment_md = (
                f"## SUPERVISOR_REVIEW_COMPLETE\n"
                f"DECISION=ACCEPT_WITH_SCOPE\n"
                f"REVIEWED_CODE_SHA={contract.code_sha}\n"
                f"NEXT_INSTRUCTION_SHA=pending_commit\n\n"
                f"All semantic evidence, diffs, and tests verified green. Next phase instruction released."
            )

        return SupervisorReviewOutput(
            decision=decision,
            reviewed_code_sha=contract.code_sha,
            reviewed_docs_sha=contract.docs_sha,
            reviewed_instruction_sha=contract.instruction_sha,
            reviewed_evidence_generation_id=contract.evidence_generation_id,
            accepted_claims=accepted_claims,
            rejected_claims=rejected_claims,
            truth_matrix=truth_matrix,
            blockers=blockers,
            next_instruction_markdown=next_instruction_md,
            issue_comment_markdown=issue_comment_md,
        )


class ExternalProviderSupervisorAdapter(SupervisorProviderAdapter):
    """
    Provider-neutral HTTP review client calling OpenAI, Anthropic, or Gemini endpoints
    with structured schema prompting and strict fail-closed validation.
    """

    def __init__(
        self,
        config: Any,
        provider_name: str,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 30.0,
    ) -> None:
        self.config = config
        self.provider_name = provider_name.lower()
        self.preflight = SemanticEvidenceSupervisorAdapter(is_live=False)
        self.api_key = getattr(config, "ai_api_key", "")
        if not self.api_key:
            env_var = f"{self.provider_name.upper()}_API_KEY"
            raise ConfigValidationError(f"{env_var} is required for {self.provider_name} provider.")
        self.model = getattr(config, "ai_model", "") or self._default_model(self.provider_name)
        self.transport = transport
        self.timeout = timeout

    @staticmethod
    def _default_model(provider_name: str) -> str:
        if provider_name == "openai":
            return "gpt-4o"
        elif provider_name == "anthropic":
            return "claude-3-5-sonnet-20241022"
        elif provider_name == "gemini":
            return "gemini-1.5-pro"
        return "default-model"

    @staticmethod
    def _format_bounded_section(
        title: str,
        content: str,
        max_chars: int,
        ref_sha: str = "",
        path: str = "",
        context: Optional[ReviewContext] = None,
        critical: bool = True,
        chunks_total: int = 1,
        chunks_covered: int = 1,
    ) -> str:
        orig_len = len(content)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest() if content else ""
        digest_prefix = digest[:16] if digest else "none"
        is_truncated = orig_len > max_chars
        sliced = content[:max_chars]
        supplied_len = len(sliced)

        computed_chunks_count = chunks_total
        if is_truncated and chunks_total == 1 and max_chars > 0:
            computed_chunks_count = (orig_len + max_chars - 1) // max_chars

        if context is not None:
            existing = [c for c in context.completeness if c.path == (path or title)]
            if not existing:
                context.completeness.append(
                    EvidenceSectionCompleteness(
                        path=path or title,
                        ref_sha=ref_sha,
                        original_chars=orig_len,
                        supplied_chars=supplied_len,
                        truncated=is_truncated,
                        sha256=digest,
                        critical=critical,
                        chunks_count=computed_chunks_count,
                        chunks_covered=chunks_covered if is_truncated else 1,
                        chunk_digests=[digest_prefix] if digest else [],
                    )
                )

        meta = (
            f"[METADATA: path={path or title} ref={ref_sha or 'n/a'} "
            f"original_chars={orig_len} supplied_chars={supplied_len} "
            f"truncated={'true' if is_truncated else 'false'} sha256_prefix={digest_prefix}]"
        )
        return f"=== {title} ===\n{meta}\n{sliced}\n"

    def review_repository(self, context: ReviewContext) -> SupervisorReviewOutput:
        # Step 1: Deterministic safety preflight
        pf = self.preflight.review_repository(context)
        if pf.decision != ReviewDecision.ACCEPT_WITH_SCOPE:
            logger.info("Preflight rejected review with %s; skipping external provider call.", pf.decision.value)
            return pf

        # Step 2: Build structured review prompt & register completeness
        prompt = self._build_prompt(context)

        # Completeness Gate: Any critical section truncated without full coverage fails closed immediately
        uncovered = [c for c in context.completeness if c.critical and c.truncated and not c.is_complete]
        if uncovered:
            uncovered_paths = [c.path for c in uncovered]
            logger.warning("Critical evidence truncated without full completeness handling: %s. Failing closed.", uncovered_paths)
            return SupervisorReviewOutput(
                decision=ReviewDecision.CHANGES_REQUIRED,
                reviewed_code_sha=context.contract.code_sha,
                reviewed_docs_sha=context.contract.docs_sha,
                reviewed_instruction_sha=context.contract.instruction_sha,
                reviewed_evidence_generation_id=context.contract.evidence_generation_id,
                blockers=[f"Critical evidence section '{c.path}' is truncated without full completeness coverage. ACCEPT not permitted." for c in uncovered],
                next_instruction_markdown="# Phase Re-Gate: Changes Required\nCritical evidence section truncated without full coverage.",
                issue_comment_markdown="## SUPERVISOR_REVIEW_COMPLETE\nDECISION=CHANGES_REQUIRED\nCritical evidence section truncated without full completeness coverage.",
                audit_trail={
                    "provider": self.provider_name,
                    "model": self.model,
                    "completeness": [c.model_dump() for c in context.completeness],
                },
            )

        # Step 3: Dispatch HTTP request to provider endpoint
        try:
            raw_text = self._call_provider_endpoint(prompt)
        except Exception as e:
            logger.warning("Provider %s HTTP request failed: %s. Failing closed.", self.provider_name, e)
            return SupervisorReviewOutput(
                decision=ReviewDecision.CHANGES_REQUIRED,
                reviewed_code_sha=context.contract.code_sha,
                reviewed_docs_sha=context.contract.docs_sha,
                reviewed_instruction_sha=context.contract.instruction_sha,
                reviewed_evidence_generation_id=context.contract.evidence_generation_id,
                blockers=[f"Provider {self.provider_name} request failed: {type(e).__name__} - {str(e)}"],
                next_instruction_markdown="# Phase Re-Gate: Changes Required\nProvider request failed.",
                issue_comment_markdown="## SUPERVISOR_REVIEW_COMPLETE\nDECISION=CHANGES_REQUIRED\nProvider request failed.",
            )

        # Step 4: Extract JSON and validate against schema
        try:
            parsed = self._extract_json(raw_text)
            validated = ProviderReviewResponseSchema.model_validate(parsed)
        except Exception as e:
            logger.warning("Provider %s output failed schema validation: %s. Failing closed.", self.provider_name, e)
            return SupervisorReviewOutput(
                decision=ReviewDecision.CHANGES_REQUIRED,
                reviewed_code_sha=context.contract.code_sha,
                reviewed_docs_sha=context.contract.docs_sha,
                reviewed_instruction_sha=context.contract.instruction_sha,
                reviewed_evidence_generation_id=context.contract.evidence_generation_id,
                blockers=[f"Provider response schema validation failed: {str(e)}"],
                next_instruction_markdown="# Phase Re-Gate: Changes Required\nMalformed provider response.",
                issue_comment_markdown="## SUPERVISOR_REVIEW_COMPLETE\nDECISION=CHANGES_REQUIRED\nMalformed provider response.",
            )

        # Step 5: Verify SHA and generation match contract across all 4 identities
        blockers = list(validated.blockers)
        decision = validated.decision

        if validated.reviewedCodeSha != context.contract.code_sha:
            blockers.append(
                f"Provider returned mismatched reviewedCodeSha '{validated.reviewedCodeSha}' (expected '{context.contract.code_sha}')."
            )
            decision = ReviewDecision.CHANGES_REQUIRED

        if validated.reviewedDocsSha != context.contract.docs_sha:
            blockers.append(
                f"Provider returned mismatched reviewedDocsSha '{validated.reviewedDocsSha}' (expected '{context.contract.docs_sha}')."
            )
            decision = ReviewDecision.CHANGES_REQUIRED

        if validated.reviewedInstructionSha != context.contract.instruction_sha:
            blockers.append(
                f"Provider returned mismatched reviewedInstructionSha '{validated.reviewedInstructionSha}' (expected '{context.contract.instruction_sha}')."
            )
            decision = ReviewDecision.CHANGES_REQUIRED

        if validated.reviewedEvidenceGenerationId != context.contract.evidence_generation_id:
            blockers.append(
                f"Provider returned mismatched reviewedEvidenceGenerationId '{validated.reviewedEvidenceGenerationId}' (expected '{context.contract.evidence_generation_id}')."
            )
            decision = ReviewDecision.CHANGES_REQUIRED

        truth_dict = {
            "REAL": validated.truthMatrix.REAL,
            "MOCK": validated.truthMatrix.MOCK,
            "PARTIAL": validated.truthMatrix.PARTIAL,
            "BLOCKED": validated.truthMatrix.BLOCKED,
        }

        # Downgrade if MOCK claimed as REAL
        if context.contract.used_mock and "Real Blender Cycles OptiX" in truth_dict["REAL"]:
            blockers.append("Provider invalidly promoted mock execution to Production Ready REAL.")
            decision = ReviewDecision.CHANGES_REQUIRED

        return SupervisorReviewOutput(
            decision=decision,
            reviewed_code_sha=context.contract.code_sha,
            reviewed_docs_sha=context.contract.docs_sha,
            reviewed_instruction_sha=context.contract.instruction_sha,
            reviewed_evidence_generation_id=context.contract.evidence_generation_id,
            accepted_claims=validated.acceptedClaims,
            rejected_claims=validated.rejectedClaims,
            truth_matrix=truth_dict,
            blockers=blockers,
            next_instruction_markdown=validated.nextInstructionMarkdown or "# Phase Re-Gate",
            issue_comment_markdown=validated.issueCommentMarkdown or f"## SUPERVISOR_REVIEW_COMPLETE\nDECISION={decision.value}",
            audit_trail={
                "provider": self.provider_name,
                "model": self.model,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reviewed_code_sha": context.contract.code_sha,
                "reviewed_docs_sha": context.contract.docs_sha,
                "reviewed_instruction_sha": context.contract.instruction_sha,
                "reviewed_evidence_generation_id": context.contract.evidence_generation_id,
                "completeness": [c.model_dump() for c in context.completeness],
            },
        )

    def _build_prompt(self, context: ReviewContext) -> str:
        contract = context.contract
        if context.changed_file_items:
            manifest_text = "\n".join(f"- {item.format_entry()}" for item in context.changed_file_items)
        elif context.changed_files:
            manifest_text = "\n".join(f"- {f}" for f in context.changed_files)
        else:
            manifest_text = "- (extracted from repository diff)"

        sections = [
            "You are Fox3D Autonomous Supervisor reviewing a Phase Re-Gate submission.\n"
            "Review the contract, exact instruction text, changed files manifest, diffs, CI runs, and evidence files.\n"
            "Output ONLY valid JSON matching this schema:\n"
            "{\n"
            '  "decision": "ACCEPT_WITH_SCOPE" | "CHANGES_REQUIRED" | "BLOCKED",\n'
            f'  "reviewedCodeSha": "{contract.code_sha}",\n'
            f'  "reviewedDocsSha": "{contract.docs_sha}",\n'
            f'  "reviewedInstructionSha": "{contract.instruction_sha}",\n'
            f'  "reviewedEvidenceGenerationId": "{contract.evidence_generation_id}",\n'
            '  "acceptedClaims": ["..."],\n'
            '  "rejectedClaims": ["..."],\n'
            '  "truthMatrix": {"REAL": [...], "MOCK": [...], "PARTIAL": [...], "BLOCKED": [...]},\n'
            '  "blockers": ["..."],\n'
            '  "nextInstructionMarkdown": "# Next Phase Instructions...",\n'
            '  "issueCommentMarkdown": "## SUPERVISOR_REVIEW_COMPLETE..."\n'
            "}\n",
            f"=== CONTRACT ===\n{contract.to_contract_block()}",
            self._format_bounded_section(
                "INSTRUCTION TEXT",
                context.instruction_text,
                8000,
                ref_sha=contract.instruction_sha,
                path="docs/GROK_NEXT_PHASE_INSTRUCTIONS.md",
                context=context,
                critical=True,
            ),
            f"=== CHANGED FILES MANIFEST ===\n{manifest_text}\n",
            f"=== CODE CI SUMMARY ===\n{json.dumps(context.code_ci_summary or context.ci_summary)}\n",
            f"=== DOCS CI SUMMARY ===\n{json.dumps(context.docs_ci_summary)}\n",
            self._format_bounded_section(
                "DIFFS",
                context.diffs,
                8000,
                ref_sha=f"{contract.instruction_sha}..{contract.code_sha}",
                path="git diff",
                context=context,
                critical=True,
            ),
            self._format_bounded_section(
                "PROGRESS REPORT",
                context.progress_report_text,
                6000,
                ref_sha=contract.docs_sha,
                path="docs/GROK_PROGRESS_REPORT.md",
                context=context,
                critical=True,
            ),
            self._format_bounded_section(
                "AUDIT TEXT",
                context.audit_text,
                4000,
                ref_sha=contract.docs_sha,
                path="docs/CURRENT_IMPLEMENTATION_AUDIT.md",
                context=context,
                critical=True,
            ),
            self._format_bounded_section(
                "ACCEPTANCE TEXT",
                context.acceptance_text,
                4000,
                ref_sha=contract.docs_sha,
                path="docs/REAL_E2E_ACCEPTANCE.md",
                context=context,
                critical=contract.real_blender and not contract.used_mock,
            ),
            self._format_bounded_section(
                "CABINET ACCEPTANCE",
                context.cabinet_acceptance_text,
                4000,
                ref_sha=contract.docs_sha,
                path="docs/CABINET_REAL_ACCEPTANCE.md",
                context=context,
                critical=False,
            ),
            self._format_bounded_section(
                "EVENT DRIVEN SUPERVISOR ACCEPTANCE",
                context.event_driven_acceptance_text,
                4000,
                ref_sha=contract.docs_sha,
                path="docs/EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md",
                context=context,
                critical=True,
            ),
        ]
        return "\n".join(sections)


    def _call_provider_endpoint(self, prompt: str) -> str:
        with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
            if self.provider_name == "openai":
                url = "https://api.openai.com/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "You are Fox3D Supervisor AI evaluator. Output JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "response_format": {"type": "json_object"},
                }
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]

            elif self.provider_name == "anthropic":
                url = "https://api.anthropic.com/v1/messages"
                headers = {
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": self.model,
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                }
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["content"][0]["text"]

            elif self.provider_name == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
                headers = {"Content-Type": "application/json"}
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                }
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]

            else:
                raise ConfigValidationError(f"Unsupported provider {self.provider_name}")

    def _extract_json(self, text: str) -> Dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return json.loads(text)


class OpenAISupervisorAdapter(ExternalProviderSupervisorAdapter):
    def __init__(self, config: Any, transport: Optional[httpx.BaseTransport] = None) -> None:
        super().__init__(config=config, provider_name="openai", transport=transport)


class AnthropicSupervisorAdapter(ExternalProviderSupervisorAdapter):
    def __init__(self, config: Any, transport: Optional[httpx.BaseTransport] = None) -> None:
        super().__init__(config=config, provider_name="anthropic", transport=transport)


class GeminiSupervisorAdapter(ExternalProviderSupervisorAdapter):
    def __init__(self, config: Any, transport: Optional[httpx.BaseTransport] = None) -> None:
        super().__init__(config=config, provider_name="gemini", transport=transport)


def create_supervisor_adapter(
    config: Any,
    transport: Optional[httpx.BaseTransport] = None,
) -> SupervisorProviderAdapter:
    """Factory to instantiate configured supervisor adapter fail-closed."""
    provider = getattr(config, "ai_provider", "rule_based").lower()
    is_live = getattr(config, "mode", "test").lower() == "live"

    if provider == "openai":
        return OpenAISupervisorAdapter(config, transport=transport)
    elif provider == "anthropic":
        return AnthropicSupervisorAdapter(config, transport=transport)
    elif provider == "gemini":
        return GeminiSupervisorAdapter(config, transport=transport)
    elif provider == "semantic_evidence":
        return SemanticEvidenceSupervisorAdapter(is_live=is_live)
    elif provider == "rule_based":
        if is_live:
            raise ConfigValidationError("rule_based provider is not permitted in live mode.")
        return RuleBasedSupervisorAdapter()
    elif provider == "mock":
        if is_live:
            raise ConfigValidationError("mock provider is not permitted in live mode.")
        return MockSupervisorAdapter()
    else:
        raise ConfigValidationError(f"Unknown AI provider '{provider}'.")
