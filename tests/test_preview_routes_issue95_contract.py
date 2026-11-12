"""Issue #95 is the authoritative work order for PR #102 preview-route coverage.

PR #102 never received a first-round 「🤖 獨立審查」 comment (the earliest on the PR is #133,
which is already labeled 複審). This module keeps re-review lanes from losing the original
acceptance bullets: every requirement maps to a concrete test in test_preview_routes_api.py.
"""
from __future__ import annotations

import importlib

import pytest

import tests.test_preview_routes_api as preview_routes_api

# Bullets copied from Issue #95 / #88 backlog item 6 (preview API tests).
ISSUE_95_REQUIREMENTS: dict[str, list[str]] = {
    "idle_when_no_job": ["test_idle_status"],
    "cancel_then_idempotent": ["test_cancel_lifecycle_is_idempotent"],
    "other_tenant_cannot_cancel": ["test_other_tenant_cannot_cancel"],
    "unknown_sku_404": ["test_unknown_sku_returns_404"],
    "health_not_real_blender": [
        "test_health_reports_mock_unavailable",
        "test_health_reports_runtime_unavailable",
    ],
    "smoke_mock_truth_labels": ["test_smoke_reports_mock_truth"],
}


def test_issue_95_every_requirement_has_tests():
    for tests in ISSUE_95_REQUIREMENTS.values():
        for name in tests:
            assert hasattr(preview_routes_api, name), name


def test_issue_95_at_least_ten_collected_cases():
  """Issue #95 asks for 10+ cases; golden+recipe parametrization expands several tests."""
  module = importlib.import_module("tests.test_preview_routes_api")
  collected = 0
  for item in dir(module):
      if not item.startswith("test_"):
          continue
      obj = getattr(module, item)
      marks = getattr(obj, "pytestmark", ())
      params = [m for m in marks if m.name == "parametrize"]
      if not params:
          collected += 1
          continue
      product = 1
      for mark in params:
          product *= len(mark.args[1])
      collected += product
  assert collected >= 10, collected


@pytest.mark.parametrize("requirement,test_names", ISSUE_95_REQUIREMENTS.items())
def test_issue_95_requirement_key_is_documented(requirement: str, test_names: list[str]):
    assert requirement
    assert test_names
