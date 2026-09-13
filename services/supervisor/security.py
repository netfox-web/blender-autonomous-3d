"""Security helpers for webhook signature verification, sender authorization, and safety checks."""

from __future__ import annotations

import hashlib
import hmac
from typing import Optional, Sequence


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
    branch_ref: Optional[str] = None,
    allowed_repo: str = "netfox-web/blender-autonomous-3d",
    allowed_branch: str = "main",
) -> None:
    """Ensure webhook belongs to the allowed repository and branch."""
    if not repo_name or repo_name.lower() != allowed_repo.lower():
        raise SecurityError(f"Repository '{repo_name}' is not allowed (expected '{allowed_repo}').")

    if branch_ref is not None:
        expected_ref = f"refs/heads/{allowed_branch}"
        if branch_ref != expected_ref and branch_ref != allowed_branch:
            raise SecurityError(f"Branch '{branch_ref}' is not allowed (expected '{allowed_branch}').")


def authorize_sender(
    sender_login: str,
    author_association: str,
    allowed_senders: Sequence[str],
    allowed_associations: Sequence[str] = ("OWNER", "MEMBER", "COLLABORATOR"),
) -> None:
    """
    Authorize commenter to issue READY_FOR_RE_GATE.
    Default-deny unknown public commenters.
    """
    login_clean = (sender_login or "").strip().lower()
    allowed_clean = [s.strip().lower() for s in allowed_senders]
    assoc_clean = (author_association or "").strip().upper()

    if login_clean in allowed_clean:
        return

    if assoc_clean in [a.upper() for a in allowed_associations]:
        return

    raise SecurityError(
        f"Unauthorized sender '{sender_login}' (association: '{author_association}'). Default-deny public commenter."
    )


def verify_admin_auth(
    auth_header: Optional[str],
    admin_key: str,
    is_live: bool = False,
    client_host: str = "",
) -> bool:
    """Verify administrator authentication for observability and control endpoints."""
    # Allow loopback in non-live mode without admin_key
    if not is_live and (client_host in ("127.0.0.1", "localhost", "::1")):
        return True

    if not admin_key:
        # In live mode, missing admin_key must fail closed
        if is_live:
            return False
        return True

    if not auth_header:
        return False

    token = auth_header
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()

    return hmac.compare_digest(token.strip(), admin_key.strip())
