from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any


def new_id() -> str:
    return str(uuid.uuid4())


def stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
