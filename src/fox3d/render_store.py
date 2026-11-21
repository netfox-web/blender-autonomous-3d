"""Tenant-partitioned atomic snapshots for render core records."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fox3d.durability import publish_bytes, unlink_owned
from fox3d.ids import stable_hash
from fox3d.storelock import FileLock


class RenderStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, tenant: str, key: str, value: dict[str, Any]) -> None:
        # Hash both components so caller-provided identifiers cannot escape the store.
        folder = self.root / stable_hash(tenant)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (stable_hash(key) + '.json')
        data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')
        with FileLock(target.with_suffix('.lock')):
            publish_bytes(lambda stream: stream.write(data), target)

    def delete(self, tenant: str, key: str) -> None:
        target = self.root / stable_hash(tenant) / (stable_hash(key) + '.json')
        with FileLock(target.with_suffix('.lock')):
            unlink_owned(target, missing_ok=True)

    def read(self, tenant: str, key: str) -> dict[str, Any] | None:
        """Read one tenant-partitioned snapshot; missing or invalid data is absent."""
        target = self.root / stable_hash(tenant) / (stable_hash(key) + '.json')
        try:
            record = json.loads(target.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return record if isinstance(record, dict) else None

    def read_all(self) -> list[dict[str, Any]]:
        records = []
        for path in self.root.glob('*/*.json'):
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if isinstance(record, dict):
                records.append(record)
        return records


class ParametricStore(dict[str, dict[str, Any]]):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self.store = RenderStore(root)
        for record in self.store.read_all():
            super().__setitem__(record['spec']['productId'], record)

    def __setitem__(self, key: str, value: dict[str, Any]) -> None:
        self.store.write(value['spec']['tenantId'], key, value)
        super().__setitem__(key, value)

    def pop(self, key: str, *args: Any) -> Any:
        if key in self:
            value = self[key]
            self.store.delete(value['spec']['tenantId'], key)
        return super().pop(key, *args)

    def __delitem__(self, key: str) -> None:
        self.store.delete(self[key]['spec']['tenantId'], key)
        super().__delitem__(key)

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key not in self:
            self[key] = default
        return self[key]
