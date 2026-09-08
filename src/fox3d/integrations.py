"""Drop-in maps onto FoxStudio worker kinds and Fleet task types.

This module does not start FoxStudio or rewrite its queue. A FoxStudio
integrator imports `FOXSTUDIO_KIND_HANDLERS` and registers them next to
`image.generate.flux` / `video.generate.i2v`.
"""

from __future__ import annotations

from typing import Any

from fox3d.capabilities import FOXSTUDIO_OPERATION_BY_CAPABILITY, FLEET_TASK_TYPE_BY_CAPABILITY
from fox3d.platform import Platform


def foxstudio_handler(platform: Platform):
    def handle(job: dict[str, Any]) -> dict[str, Any]:
        return platform.execute_job(job)

    return handle


FOXSTUDIO_KIND_HANDLERS = {
    operation: "fox3d.integrations.foxstudio_handler"
    for operation in FOXSTUDIO_OPERATION_BY_CAPABILITY.values()
}

FLEET_TASK_TYPES = dict(FLEET_TASK_TYPE_BY_CAPABILITY)

# Existing FoxStudio drain control — reuse, do not reimplement HTTP.
FOXSTUDIO_DRAIN = {
    "method": "POST",
    "path": "/api/v1/settings/compute-targets/{targetKey}/control",
    "body": {"action": "drain", "reason": "preempt-for-ai-video"},
}
