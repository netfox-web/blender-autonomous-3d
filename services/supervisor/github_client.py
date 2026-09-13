"""GitHub API client with verification of commits, CI runs, and comments."""

from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import httpx

from services.supervisor.config import SupervisorConfig


class GitHubVerificationError(Exception):
    """Raised when GitHub state validation fails (e.g. CI failed, commit unreachable)."""
    pass


class GitHubClientInterface(ABC):
    @abstractmethod
    def verify_commit_on_main(self, sha: str) -> bool:
        """Verify that sha exists and is reachable from main."""
        pass

    @abstractmethod
    def get_ci_run_details(self, run_id: str) -> Dict[str, Any]:
        """Fetch workflow run details."""
        pass

    @abstractmethod
    def verify_ci_run(self, run_id: str, expected_code_sha: str) -> Dict[str, Any]:
        """
        Verify that:
        1. run_id head_sha matches expected_code_sha
        2. overall conclusion == 'success'
        3. both ubuntu-latest and windows-latest jobs succeeded
        """
        pass

    @abstractmethod
    def get_file_content(self, path: str, ref: str = "main") -> str:
        """Fetch file content at ref."""
        pass

    @abstractmethod
    def get_commits_since(self, base_sha: str, head_sha: str = "main") -> List[Dict[str, Any]]:
        """Fetch commits between base_sha and head_sha."""
        pass

    @abstractmethod
    def get_diff_between(self, base_sha: str, head_sha: str = "main") -> str:
        """Fetch diff between base_sha and head_sha."""
        pass

    @abstractmethod
    def commit_instruction_file(
        self,
        file_path: str,
        content: str,
        commit_message: str,
        branch: str = "main",
    ) -> str:
        """Commit an updated instruction file and return the new commit SHA."""
        pass

    @abstractmethod
    def add_issue_comment(self, issue_number: int, comment_body: str) -> str:
        """Post a comment to an issue and return comment id."""
        pass

    @abstractmethod
    def get_latest_issue_comments(self, issue_number: int, count: int = 10) -> List[Dict[str, Any]]:
        """Fetch the most recent comments for an issue."""
        pass


class GitHubClient(GitHubClientInterface):
    """Live GitHub client using GitHub REST API and optional gh CLI fallback."""

    def __init__(self, config: SupervisorConfig) -> None:
        self.config = config
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Fox3D-Supervisor",
        }
        if config.github_token:
            self.headers["Authorization"] = f"token {config.github_token}"

    def verify_commit_on_main(self, sha: str) -> bool:
        try:
            # Use local git if available in repo_root for fast reliable verification
            res = subprocess.run(
                ["git", "merge-base", "--is-ancestor", sha, f"origin/{self.config.allowed_branch}"],
                cwd=str(self.config.repo_root),
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass

        # Fallback to GitHub API compare
        try:
            url = f"{self.base_url}/repos/{self.config.repo_name}/compare/{self.config.allowed_branch}...{sha}"
            resp = httpx.get(url, headers=self.headers, timeout=15.0)
            if resp.status_code == 200:
                data = resp.json()
                # If behind or identical, sha is an ancestor of main
                return data.get("status") in ("behind", "identical")
        except Exception:
            pass
        return False

    def get_ci_run_details(self, run_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/repos/{self.config.repo_name}/actions/runs/{run_id}"
        resp = httpx.get(url, headers=self.headers, timeout=15.0)
        resp.raise_for_status()
        return resp.json()

    def verify_ci_run(self, run_id: str, expected_code_sha: str) -> Dict[str, Any]:
        run_data = self.get_ci_run_details(run_id)

        head_sha = run_data.get("head_sha", "")
        if not head_sha.startswith(expected_code_sha) and not expected_code_sha.startswith(head_sha):
            raise GitHubVerificationError(
                f"CI run {run_id} head_sha ({head_sha}) does not match expected CODE_SHA ({expected_code_sha})."
            )

        status = run_data.get("status", "")
        conclusion = run_data.get("conclusion", "")
        if status in ("in_progress", "queued", "waiting", "requested"):
            raise GitHubVerificationError(f"CI run {run_id} is still {status} (not concluded).")

        if conclusion != "success":
            raise GitHubVerificationError(f"CI run {run_id} conclusion is '{conclusion}', not 'success'.")

        # Check jobs
        jobs_url = run_data.get("jobs_url") or f"{self.base_url}/repos/{self.config.repo_name}/actions/runs/{run_id}/jobs"
        j_resp = httpx.get(jobs_url, headers=self.headers, timeout=15.0)
        j_resp.raise_for_status()
        jobs = j_resp.json().get("jobs", [])

        ubuntu_ok = False
        windows_ok = False
        for job in jobs:
            name = job.get("name", "").lower()
            job_conclusion = job.get("conclusion", "")
            if "ubuntu" in name and job_conclusion == "success":
                ubuntu_ok = True
            if "windows" in name and job_conclusion == "success":
                windows_ok = True

        if not ubuntu_ok or not windows_ok:
            raise GitHubVerificationError(
                f"CI run {run_id} jobs incomplete: ubuntu-success={ubuntu_ok}, windows-success={windows_ok}."
            )

        return {
            "run_id": run_id,
            "head_sha": head_sha,
            "conclusion": conclusion,
            "ubuntu_ok": ubuntu_ok,
            "windows_ok": windows_ok,
        }

    def get_file_content(self, path: str, ref: str = "main") -> str:
        # Prefer local repository working copy or git show if ref == "main" / HEAD
        try:
            res = subprocess.run(
                ["git", "show", f"{ref}:{path}"],
                cwd=str(self.config.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if res.returncode == 0:
                return res.stdout
        except Exception:
            pass

        url = f"{self.base_url}/repos/{self.config.repo_name}/contents/{path}?ref={ref}"
        resp = httpx.get(url, headers=self.headers, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        import base64
        return base64.b64decode(data.get("content", "")).decode("utf-8")

    def get_commits_since(self, base_sha: str, head_sha: str = "main") -> List[Dict[str, Any]]:
        try:
            res = subprocess.run(
                ["git", "log", f"{base_sha}..{head_sha}", "--pretty=format:%H|%an|%s"],
                cwd=str(self.config.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if res.returncode == 0 and res.stdout.strip():
                commits = []
                for line in res.stdout.splitlines():
                    if "|" in line:
                        parts = line.split("|", 2)
                        commits.append({"sha": parts[0], "author": parts[1], "message": parts[2]})
                return commits
        except Exception:
            pass
        return []

    def get_diff_between(self, base_sha: str, head_sha: str = "main") -> str:
        try:
            res = subprocess.run(
                ["git", "diff", f"{base_sha}..{head_sha}"],
                cwd=str(self.config.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if res.returncode == 0:
                return res.stdout
        except Exception:
            pass

        # Fallback to GitHub API compare
        try:
            url = f"{self.base_url}/repos/{self.config.repo_name}/compare/{base_sha}...{head_sha}"
            headers = dict(self.headers)
            headers["Accept"] = "application/vnd.github.v3.diff"
            resp = httpx.get(url, headers=headers, timeout=15.0)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
        return ""

    def commit_instruction_file(
        self,
        file_path: str,
        content: str,
        commit_message: str,
        branch: str = "main",
    ) -> str:
        # Rule 3: Only allow intended instruction paths
        allowed_paths = {
            "docs/GROK_NEXT_PHASE_INSTRUCTIONS.md",
            "docs/AGENT_NEXT_PHASE_INSTRUCTIONS.md",
        }
        if file_path not in allowed_paths:
            raise GitHubVerificationError(
                f"Path '{file_path}' is not an authorized supervisor instruction file path."
            )

        is_live = getattr(self.config, "mode", "test").lower() == "live"

        if is_live:
            # Rule 2: Pre-flight check: ensure clean tree and base
            status_res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.config.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if status_res.returncode == 0 and status_res.stdout.strip():
                raise GitHubVerificationError("Refusing to commit instruction on a dirty working tree.")

            diff_index_res = subprocess.run(
                ["git", "diff-index", "--quiet", "HEAD", "--"],
                cwd=str(self.config.repo_root),
            )
            if diff_index_res.returncode != 0:
                raise GitHubVerificationError("Refusing to commit instruction: staged or unstaged changes exist.")

            fetch_res = subprocess.run(
                ["git", "fetch", "origin", branch],
                cwd=str(self.config.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if fetch_res.returncode != 0:
                raise GitHubVerificationError(
                    f"Failed to fetch remote branch prior to instruction commit: {fetch_res.stderr.strip()}"
                )

            # Verify current branch is configured branch (disallow detached HEAD)
            branch_res = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(self.config.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            curr_branch = branch_res.stdout.strip()
            if curr_branch != branch or curr_branch == "HEAD":
                raise GitHubVerificationError(
                    f"Refusing to commit instruction on branch '{curr_branch}' (expected '{branch}', detached HEAD forbidden)."
                )

            # Verify local HEAD matches origin/branch
            local_head_res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.config.repo_root), capture_output=True, text=True)
            origin_head_res = subprocess.run(["git", "rev-parse", f"origin/{branch}"], cwd=str(self.config.repo_root), capture_output=True, text=True)
            local_head = local_head_res.stdout.strip()
            origin_head = origin_head_res.stdout.strip()
            if local_head != origin_head:
                raise GitHubVerificationError(
                    f"Local HEAD ({local_head}) does not match origin/{branch} ({origin_head}). Refusing write."
                )

        full_path = self.config.repo_root / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

        # Also update neutral alias if applicable
        if file_path == "docs/GROK_NEXT_PHASE_INSTRUCTIONS.md":
            alias_path = self.config.repo_root / "docs/AGENT_NEXT_PHASE_INSTRUCTIONS.md"
            alias_path.parent.mkdir(parents=True, exist_ok=True)
            alias_path.write_text(content, encoding="utf-8")
            subprocess.run(["git", "add", str(alias_path)], cwd=str(self.config.repo_root), check=True)

        subprocess.run(["git", "add", str(full_path)], cwd=str(self.config.repo_root), check=True)
        subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=str(self.config.repo_root),
            capture_output=True,
            check=True,
        )
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(self.config.repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        new_sha = res.stdout.strip()

        # Push to remote branch using explicit refspec
        push_res = subprocess.run(
            ["git", "push", "origin", f"HEAD:refs/heads/{branch}"],
            cwd=str(self.config.repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if push_res.returncode != 0:
            if is_live:
                # Rollback local commit to maintain clean working tree on failure
                subprocess.run(
                    ["git", "reset", "--hard", f"origin/{branch}"],
                    cwd=str(self.config.repo_root),
                    capture_output=True,
                )
                raise GitHubVerificationError(
                    f"git push failed in live mode (exit code {push_res.returncode}): {push_res.stderr.strip()}"
                )
            # In non-live/test mode, allow local commit if origin not reachable

        if is_live:
            # Re-fetch origin to verify remote HEAD and blob content
            subprocess.run(
                ["git", "fetch", "origin", branch],
                cwd=str(self.config.repo_root),
                capture_output=True,
                text=True,
            )
            verify_res = subprocess.run(
                ["git", "rev-parse", f"origin/{branch}"],
                cwd=str(self.config.repo_root),
                capture_output=True,
                text=True,
            )
            remote_head = verify_res.stdout.strip() if verify_res.returncode == 0 else ""
            if remote_head != new_sha:
                raise GitHubVerificationError(
                    f"Remote verification failed: origin/{branch} ({remote_head}) does not match new commit ({new_sha})."
                )

            # Verify remote blob content matches intended payload
            remote_content_res = subprocess.run(
                ["git", "show", f"origin/{branch}:{file_path}"],
                cwd=str(self.config.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if remote_content_res.returncode != 0 or remote_content_res.stdout.strip() != content.strip():
                raise GitHubVerificationError(
                    f"Remote content verification failed for '{file_path}' at origin/{branch}."
                )

        return new_sha

    def add_issue_comment(self, issue_number: int, comment_body: str) -> str:
        # Try local gh CLI
        try:
            res = subprocess.run(
                ["gh", "issue", "comment", str(issue_number), "--body", comment_body],
                cwd=str(self.config.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if res.returncode == 0:
                return "gh_comment_ok"
        except Exception:
            pass

        # Try API
        url = f"{self.base_url}/repos/{self.config.repo_name}/issues/{issue_number}/comments"
        resp = httpx.post(url, headers=self.headers, json={"body": comment_body}, timeout=15.0)
        resp.raise_for_status()
        return str(resp.json().get("id", ""))

    def get_latest_issue_comments(self, issue_number: int, count: int = 10) -> List[Dict[str, Any]]:
        try:
            res = subprocess.run(
                ["gh", "issue", "view", str(issue_number), "--json", "comments", "--jq", f".comments[-{count}:]"],
                cwd=str(self.config.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if res.returncode == 0 and res.stdout.strip():
                return json.loads(res.stdout.strip())
        except Exception:
            pass

        url = f"{self.base_url}/repos/{self.config.repo_name}/issues/{issue_number}/comments?per_page={count}"
        resp = httpx.get(url, headers=self.headers, timeout=15.0)
        resp.raise_for_status()
        return resp.json()
