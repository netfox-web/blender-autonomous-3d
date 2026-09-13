"""Security helpers for webhook signature verification and safety checks."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional


class SecurityError(Exception):
    """Raised when security or signature checks fail."""
    pass


def verify_github_signature(
    payload_bytes: bytes,
    signature_header: Optional[str],
    secret: str,
) -> bool:
    """Verify GitHub webhook payload HMAC-SHA256 signature."""
    if not secret:
        raise SecurityError("GITHUB_WEBHOOK_SECRET is not configured.")
    if not signature_header:
        return False

    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False

    received_sig = signature_header[len(prefix):].strip()
    computed_sig = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(received_sig, computed_sig)


def validate_repo_and_branch(
    repo_name: str,
    branch_ref: Optional[str],
    allowed_repo: str = "netfox-web/blender-autonomous-3d",
    allowed_branch: str = "main",
) -> None:
    """Ensure webhook belongs to the allowed repository and branch."""
    if repo_name.lower() != allowed_repo.lower():
        raise SecurityError(f"Repository '{repo_name}' is not allowed (expected '{allowed_repo}').")

    if branch_ref is not None:
        expected_ref = f"refs/heads/{allowed_branch}"
        if branch_ref != expected_ref and branch_ref != allowed_branch:
            raise SecurityError(f"Branch '{branch_ref}' is not allowed (expected '{allowed_branch}').")
