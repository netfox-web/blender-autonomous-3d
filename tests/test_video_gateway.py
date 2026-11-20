"""Offline video gateway checks. No live provider, network, or runtime."""
from __future__ import annotations

import json

import pytest

from fox3d.ids import sha256_bytes
from fox3d.pngutil import write_png
from fox3d.video_gateway import (
    H3MaxAdapter,
    LTX25Adapter,
    MockTransport,
    VideoAdapter,
    qa_candidate,
    submit_provider,
)
# Re-exported so pytest registers fixtures defined in the ground-truth module.
from test_video_ground_truth import _base_bundle as _base_bundle
from test_video_ground_truth import bundle as bundle
from test_video_ground_truth import candidate, record, store

QA_DECISIONS = {"PASS", "RETRY", "REJECT"}


def _assert_not_real(result):
    assert result["liveProviderReady"] is False
    assert result["networkExecuted"] is False
    assert type(result["status"]) is str
    assert "REAL" not in result["status"].upper()
    if type(result.get("provider")) is str:
        assert "REAL" not in result["provider"].upper()


class _Liar(VideoAdapter):
    def submit(self, package):
        return {
            "status": "REAL",
            "provider": "REAL_PROVIDER",
            "liveProviderReady": True,
            "networkExecuted": True,
            "outputArtifacts": [{"url": "https://provider.example/clip"}],
        }


class _Boom(VideoAdapter):
    def submit(self, package):
        raise RuntimeError("provider exploded")


@pytest.mark.parametrize("adapter", [VideoAdapter(), H3MaxAdapter(), LTX25Adapter()])
def test_mock_transport_never_marks_real(adapter):
    transport = MockTransport(response={"status": "REAL", "liveProviderReady": True, "networkExecuted": True})
    result = submit_provider(adapter, {"sealed": True}, transport=transport, runtime=object())
    _assert_not_real(result)
    assert result["status"] == "BLOCKED_MOCK_TRANSPORT"
    assert transport.calls == 1
    assert result["outputArtifacts"] == []


def test_mock_transport_ignores_raising_send():
    transport = MockTransport(response=RuntimeError("offline"))
    result = submit_provider(_Liar(), {}, transport=transport, runtime=object())
    _assert_not_real(result)
    assert result["status"] == "BLOCKED_MOCK_TRANSPORT"


def test_missing_runtime_never_marks_real():
    result = submit_provider(_Liar(), {"sealed": True}, transport=object(), runtime=None)
    _assert_not_real(result)
    assert result["status"] == "BLOCKED_NO_RUNTIME"
    assert result["outputArtifacts"] == []


def test_adapter_exception_never_marks_real():
    result = submit_provider(_Boom(), {}, transport=object(), runtime=object())
    _assert_not_real(result)
    assert result["status"] == "BLOCKED_ADAPTER_ERROR"
    assert result["outputArtifacts"] == []


def test_lying_adapter_cannot_promote_real_when_runtime_object_exists():
    result = submit_provider(_Liar(), {}, transport=object(), runtime=object())
    _assert_not_real(result)
    assert result["liveProviderReady"] is False
    assert result["provider"] == "FUTURE_PROVIDER"


@pytest.mark.parametrize(
    "key",
    ["sku", "engineeringHash", "artworkHash", "placementHash"],
)
def test_identity_mismatch_qa_is_reject(bundle, key):
    forged = candidate(bundle)
    forged["identity"][key] = "foreign-value"
    decision = qa_candidate(bundle["m"], forged)
    assert decision["decision"] in QA_DECISIONS
    assert decision["decision"] == "REJECT"
    assert decision["visionQaReady"] is False


def test_qa_pass_retry_reject_are_the_only_decisions(bundle):
    passed = qa_candidate(bundle["m"], candidate(bundle))
    assert passed["decision"] == "PASS"

    drifted = candidate(bundle)
    path = bundle["tmp"] / "drift.png"
    write_png(path, 32, 32, bytes([255, 0, 0]) * 1024)
    data = path.read_bytes()
    drifted["frames"][0]["artifacts"]["beauty"] = {
        "path": str(path),
        "sha256": sha256_bytes(data),
        "size": len(data),
    }
    retried = qa_candidate(bundle["m"], drifted)
    assert retried["decision"] == "RETRY"

    rejected = candidate(bundle)
    rejected["manifestHash"] = "0" * 64
    refused = qa_candidate(bundle["m"], rejected)
    assert refused["decision"] == "REJECT"
    assert {passed["decision"], retried["decision"], refused["decision"]} == QA_DECISIONS


def test_reject_cannot_enter_final(bundle):
    forged = candidate(bundle)
    forged["identity"]["sku"] = "foreign-sku"
    journal = store(bundle)
    saved = record(journal, bundle, forged)
    assert saved["qa"]["decision"] == "REJECT"
    assert saved["publishState"] == "QA_REJECTED"
    assert saved["finalCommerceVideo"] is False
    with pytest.raises(ValueError, match="rejected_candidate_cannot_publish"):
        journal.publish(bundle["m"], "attempt1", final=True)
    path = journal.root / bundle["m"]["identity"]["tenantId"] / bundle["m"]["generationId"] / "attempt1.json"
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["publishState"] == "QA_REJECTED"
    assert persisted["finalCommerceVideo"] is False
    assert persisted["liveProviderReady"] is False
    assert "REAL" not in persisted["publishState"]
