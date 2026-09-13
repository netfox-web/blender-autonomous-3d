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

    def commit_instruction_file(
        self,
        file_path: str,
        content: str,
        commit_message: str,
        branch: str = "main",
    ) -> str:
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
        # Push to remote branch
        try:
            subprocess.run(
                ["git", "push", "origin", branch],
                cwd=str(self.config.repo_root),
                capture_output=True,
                check=True,
            )
        except Exception:
            # If push fails in offline / local testing environment, return local new commit sha
            pass
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
