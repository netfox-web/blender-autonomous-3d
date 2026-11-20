"""One-time inspection and tenant attribution migration for legacy tenantless or conflicting carrier quotes.

Pre-deployment / backup readiness requirement:
  Tenant-scoped backups (backup_pilot) treat carrier_quotes as TENANT_OWNED, exclude explicit
  global quotes, and fail-closed (BLOCKED) if any legacy tenantless quote, rolled-back quote
  (ownership=GLOBAL_REFERENCE without globalQuote), or conflicting quote (e.g. tenantId combined
  with globalQuote/isGlobal/allowGlobal/GLOBAL_REFERENCE, or ownership=TENANT_OWNED combined
  with global flags without tenantId) remains in logistics.json. Raw entries that are not JSON
  objects, and every copy of a quoteId that appears more than once, are also reported (issue
  non_object / duplicate_quote_id with rawIndex + recordFingerprint) and block backup until resolved.
  Before deployment or running tenant-scoped backups, verify tenantlessCount == 0:
    python scripts/migrate_carrier_quotes.py --root .fox3d-data --check --require-zero

Usage examples:
  # List all legacy tenantless or conflicting carrier quotes (and any shipment tenant references):
  python scripts/migrate_carrier_quotes.py --root .fox3d-data --check

  # Pre-deployment gate (exits with code 1 when tenantlessCount > 0):
  python scripts/migrate_carrier_quotes.py --root .fox3d-data --check --require-zero

  # Dry-run migration (infer from shipments + fallback to default tenant):
  python scripts/migrate_carrier_quotes.py --root .fox3d-data --tenant tenant-a --dry-run

  # Apply migration with explicit per-quote attribution and default tenant:
  python scripts/migrate_carrier_quotes.py --root .fox3d-data --tenant tenant-a --assign q1=tenant-b

  # Resolve a duplicated quoteId by keeping one copy (fingerprint from --check output; others removed
  # and printed in "removed"), or remove a non-object entry; add --dry-run to preview:
  python scripts/migrate_carrier_quotes.py --root .fox3d-data --keep-duplicate q1=<recordFingerprint>
  python scripts/migrate_carrier_quotes.py --root .fox3d-data --drop-invalid <recordFingerprint>
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from fox3d.logistics import (  # noqa: E402
    classify_carrier_quote,
    cli_main,
    inspect_tenantless_carrier_quotes,
    is_explicit_global_carrier_quote,
    is_tenantless_carrier_quote,
    is_valid_tenant_carrier_quote,
    migrate_tenantless_carrier_quotes,
    resolve_carrier_quote_records,
    unassign_migrated_carrier_quotes,
)

__all__ = [
    "classify_carrier_quote",
    "cli_main",
    "inspect_tenantless_carrier_quotes",
    "is_explicit_global_carrier_quote",
    "is_tenantless_carrier_quote",
    "is_valid_tenant_carrier_quote",
    "main",
    "migrate_tenantless_carrier_quotes",
    "resolve_carrier_quote_records",
    "unassign_migrated_carrier_quotes",
]


def main(argv: list[str] | None = None) -> int:
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
