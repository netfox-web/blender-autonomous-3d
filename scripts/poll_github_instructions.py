"""Poll GitHub for updates to instructions (docs/GROK_NEXT_PHASE_INSTRUCTIONS.md) and Issue #1.

Updates .fox3d-data/grok-github-poll.json and reports whether new instructions exist.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POLL_FILE = REPO_ROOT / ".fox3d-data" / "grok-github-poll.json"


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


def poll_github() -> dict:
    POLL_FILE.parent.mkdir(parents=True, exist_ok=True)
    previous_state = {}
    if POLL_FILE.is_file():
        try:
            previous_state = json.loads(POLL_FILE.read_text(encoding="utf-8"))
        except Exception:
            previous_state = {}

    # Fetch origin
    try:
        run_cmd(["git", "fetch", "origin", "main"])
    except Exception as e:
        print(f"Warning: git fetch failed: {e}", file=sys.stderr)

    origin_main_sha = run_cmd(["git", "rev-parse", "origin/main"])
    local_head_sha = run_cmd(["git", "rev-parse", "HEAD"])

    instruction_blob_sha = ""
    try:
        instruction_blob_sha = run_cmd(["git", "rev-parse", "origin/main:docs/GROK_NEXT_PHASE_INSTRUCTIONS.md"])
    except Exception:
        pass

    latest_comment = None
    try:
        raw_comment = run_cmd(["gh", "issue", "view", "1", "--json", "comments", "--jq", ".comments[-1]"])
        if raw_comment:
            latest_comment = json.loads(raw_comment)
    except Exception as e:
        print(f"Warning: gh issue query failed: {e}", file=sys.stderr)

    now_iso = datetime.now(timezone.utc).astimezone().isoformat()

    prev_origin_sha = previous_state.get("originMainSha", "")
    prev_instr_sha = previous_state.get("instructionFiles", {}).get("docs/GROK_NEXT_PHASE_INSTRUCTIONS.md", "")
    prev_comment_id = previous_state.get("issues", {}).get("1", {}).get("latestCommentId", "")

    new_commit = bool(prev_origin_sha and origin_main_sha != prev_origin_sha)
    new_instruction = bool(prev_instr_sha and instruction_blob_sha != prev_instr_sha)
    curr_comment_id = latest_comment.get("id") if latest_comment else ""
    new_comment = bool(prev_comment_id and curr_comment_id and curr_comment_id != prev_comment_id)

    status = "no_new_instructions"
    if new_instruction:
        status = "new_instruction_in_file"
    elif new_comment:
        status = "new_comment_in_issue_1"
    elif new_commit:
        status = "new_commit_on_origin_main"

    updated_state = {
        "lastPollAt": now_iso,
        "originMainSha": origin_main_sha,
        "localHeadAtPoll": local_head_sha,
        "instructionFiles": {
            "docs/GROK_NEXT_PHASE_INSTRUCTIONS.md": instruction_blob_sha,
            "docs/dispatch/README.md": previous_state.get("instructionFiles", {}).get("docs/dispatch/README.md", ""),
            "docs/GROK_PROGRESS_REPORT.md": previous_state.get("instructionFiles", {}).get("docs/GROK_PROGRESS_REPORT.md", ""),
        },
        "issues": {
            "1": {
                "title": "Grok autonomous development handoff",
                "updatedAt": latest_comment.get("createdAt", "") if latest_comment else "",
                "latestCommentId": curr_comment_id,
                "latestCommentAuthor": latest_comment.get("author", {}).get("login", "") if latest_comment else "",
                "snippet": (latest_comment.get("body", "")[:200] + "...") if latest_comment else "",
            }
        },
        "pollResult": {
            "status": status,
            "newCommit": new_commit,
            "newInstructionFile": new_instruction,
            "newIssueComment": new_comment,
        },
    }

    POLL_FILE.write_text(json.dumps(updated_state, indent=2, ensure_ascii=False), encoding="utf-8")
    return updated_state


if __name__ == "__main__":
    result = poll_github()
    print(json.dumps(result, indent=2, ensure_ascii=False))
