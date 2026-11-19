# Legacy commerce snapshot ownership

Provider files now carry `"formatVersion": 2`. In that format `items` holds rows the server wrote, with `tenantId` taken from the request's verified tenant header (never from the row body), and `legacyItems` holds quarantined pre-upgrade rows.

A file without `formatVersion` was written before tenant stamping. The old import endpoint stored whatever `tenantId` the caller sent, so a tenant could have saved a row claiming another tenant. Every row of such a file is therefore treated as unknown ownership, including rows that carry a `tenantId`: on load they are moved into quarantine, the claimed value is kept only as the informational `claimedTenantId`, and the next write persists them under `legacyItems`. Quarantined rows are excluded from `active()`, `get()`, tenant queries (`GET /api/commerce/snapshots`) and supplier comparisons. A `tenantId` found on a row in `legacyItems` is ignored. Rows that lack a string `snapshotId` are kept verbatim in `legacyItems` but cannot be assigned.

Do not infer the owner from `claimedTenantId`, from the caller, or from the default tenant. Back up the provider JSON files and determine ownership from independent records before assigning individual IDs. With the application stopped, in a trusted local maintenance session, use `scripts/assign_commerce_legacy.py`. Dry-run lists each quarantined `snapshotId` and informational `claimedTenantId` and does not rewrite provider files:

```
python scripts/assign_commerce_legacy.py --provider-root <provider_directory> --dry-run
python scripts/assign_commerce_legacy.py --provider-root <provider_directory> --dry-run --kind fx
```

Assignment takes an explicit `--tenant` that the operator verified independently. `--backup` must be a separate regular file, or a directory containing `<kind>.json`, whose bytes equal the current provider file; the live file and a hard link of it are refused. The script then locks and reloads the file, refuses missing IDs, duplicate IDs, and destination collisions, and writes atomically through `SnapshotStore.assign_legacy`. It updates the snapshot hash to reflect the tenant. One JSONL record is appended to `--audit` for the attempt. Running the same assignment again does not assign a second time, including when the operator passes the original backup again: that backup still contains the snapshot IDs, the provider file stays as it was, and the audit action is `already-assigned`. A snapshot becomes visible only to the tenant named in `--tenant`. Repeat a refused collision only after resolving it; no HTTP endpoint grants ownership. Restore the backup to undo an assignment, taking care not to overwrite later imports. Older application versions cannot read the `formatVersion` 2 layout's `legacyItems`; to roll back, restore the pre-upgrade backup.

Supplier comparisons look up the FX snapshot by the verified tenant and snapshot ID (`SupplierQuoteService.compare(..., tenant_id=...)`). Callers without a tenant only match unscoped rows written by server code (`import_fx` without `tenant_id`); they never see tenant-owned or quarantined rows.

Timestamps without an offset are interpreted as UTC. Dates denote UTC midnight for query and effective times; a date-only expiration includes the entire UTC day. Invalid stored bounds are excluded from active results.
