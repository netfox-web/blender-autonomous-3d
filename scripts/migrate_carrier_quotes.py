"""One-time inspection and tenant attribution migration for legacy tenantless carrier quotes.

Usage examples:
  # List all legacy tenantless carrier quotes (and any shipment tenant references):
  python scripts/migrate_carrier_quotes.py --root .fox3d-data --check

  # Dry-run migration (infer from shipments + fallback to default tenant):
  python scripts/migrate_carrier_quotes.py --root .fox3d-data --tenant tenant-a --dry-run

  # Apply migration with explicit per-quote attribution and default tenant:
  python scripts/migrate_carrier_quotes.py --root .fox3d-data --tenant tenant-a --assign q1=tenant-b
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from fox3d.logistics import (  # noqa: E402
    cli_main,
    inspect_tenantless_carrier_quotes,
    migrate_tenantless_carrier_quotes,
    unassign_migrated_carrier_quotes,
)

__all__ = [
    "cli_main",
    "inspect_tenantless_carrier_quotes",
    "main",
    "migrate_tenantless_carrier_quotes",
    "unassign_migrated_carrier_quotes",
]


def main(argv: list[str] | None = None) -> int:
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
