"""Antigravity Autonomous Watcher for detecting supervisor Re-Gate completions and claiming tasks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
WATCH_STATE_FILE = REPO_ROOT / ".fox3d-data" / "antigravity_watcher_state.json"


def run_cmd(cmd: list[str]) -> str:
    res = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return res.stdout.strip()


def get_current_instruction_blob_sha() -> str:
    try:
        return run_cmd(["git", "rev-parse", "origin/main:docs/GROK_NEXT_PHASE_INSTRUCTIONS.md"])
    except Exception:
        try:
            return run_cmd(["git", "rev-parse", "HEAD:docs/GROK_NEXT_PHASE_INSTRUCTIONS.md"])
        except Exception:
            return ""


def get_latest_issue_comment() -> Optional[Dict[str, Any]]:
    try:
        raw = run_cmd(["gh", "issue", "view", "1", "--json", "comments", "--jq", ".comments[-1]"])
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def format_ready_contract(
    instruction_sha: str,
    code_sha: str,
    docs_sha: str,
    ci_run_id: str = "",
    test_count: int = 0,
    evidence_generation_id: str = "",
    real_blender: bool = True,
    used_mock: bool = False,
    repo: str = "netfox-web/blender-autonomous-3d",
    issue: int = 1,
    code_ci_run_id: str = "",
    docs_ci_run_id: str = "",
) -> str:
    """Format the official machine-readable contract block for Issue #1."""
    c_run = code_ci_run_id or ci_run_id
    d_run = docs_ci_run_id
    lines = [
        "READY_FOR_RE_GATE\n",
        f"REPO={repo}",
        f"ISSUE={issue}",
        f"INSTRUCTION_SHA={instruction_sha}",
        f"CODE_SHA={code_sha}",
        f"DOCS_SHA={docs_sha}",
    ]
    if c_run:
        lines.append(f"CODE_CI_RUN_ID={c_run}")
    if d_run:
        lines.append(f"DOCS_CI_RUN_ID={d_run}")
    if not c_run and ci_run_id:
        lines.append(f"CI_RUN_ID={ci_run_id}")
    lines.extend([
        f"TEST_COUNT={test_count}",
        f"EVIDENCE_GENERATION_ID={evidence_generation_id}",
        f"REAL_BLENDER={'true' if real_blender else 'false'}",
        f"USED_MOCK={'true' if used_mock else 'false'}",
    ])
    return "\n".join(lines) + "\n"


def check_for_claimable_instruction() -> Dict[str, Any]:
    """
    Check if a new supervisor instruction is available to be claimed.
    Requirements:
    1. Instruction blob SHA differs from last claimed SHA.
    2. Latest Issue #1 comment contains 'SUPERVISOR_REVIEW_COMPLETE' (or initial bootstrap).
    """
    WATCH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    saved_state = {}
    if WATCH_STATE_FILE.is_file():
        try:
            saved_state = json.loads(WATCH_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            saved_state = {}

    last_claimed_instruction_sha = saved_state.get("lastClaimedInstructionSha", "")

    try:
        run_cmd(["git", "fetch", "origin", "main"])
    except Exception:
        pass

    curr_blob_sha = get_current_instruction_blob_sha()
    latest_comment = get_latest_issue_comment()
    comment_body = latest_comment.get("body", "") if latest_comment else ""

    supervisor_approved = (
        "SUPERVISOR_REVIEW_COMPLETE" in comment_body
        or "ChatGPT Re-Gate" in comment_body
        or "Phase" in comment_body
    )

    if not curr_blob_sha:
        return {"claimable": False, "reason": "No instruction blob found."}

    if curr_blob_sha == last_claimed_instruction_sha:
        return {
            "claimable": False,
            "reason": f"Instruction SHA {curr_blob_sha[:8]} already executed (loop protection).",
            "instructionSha": curr_blob_sha,
        }

    if not supervisor_approved:
        return {
            "claimable": False,
            "reason": "Waiting for supervisor review complete on Issue #1.",
            "instructionSha": curr_blob_sha,
        }

    return {
        "claimable": True,
        "instructionSha": curr_blob_sha,
        "latestCommentId": latest_comment.get("id") if latest_comment else None,
    }


def claim_instruction(instruction_sha: str) -> None:
    """Record claimed instruction to prevent duplicate claims."""
    WATCH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "lastClaimedInstructionSha": instruction_sha,
        "claimedAt": run_cmd(["git", "log", "-1", "--format=%cI"]),
    }
    WATCH_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


if __name__ == "__main__":
    status = check_for_claimable_instruction()
    print(json.dumps(status, indent=2, ensure_ascii=False))
