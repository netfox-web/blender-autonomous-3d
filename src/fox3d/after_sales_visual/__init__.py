"""Non-production after-sales visual evidence assistant.

The package is intentionally isolated from rendering, ERP writes and shipment
execution.  It only produces review candidates from approved snapshots.
"""

from .engine import DisabledVisualModelAdapter, FixtureObservationProvider, analyze_case, build_replacement_draft
from .models import AfterSalesCase, AfterSalesResult, HumanDecision

__all__ = [
    "AfterSalesCase",
    "AfterSalesResult",
    "DisabledVisualModelAdapter",
    "FixtureObservationProvider",
    "HumanDecision",
    "analyze_case",
    "build_replacement_draft",
]
