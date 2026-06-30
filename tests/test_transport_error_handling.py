"""A persistent transport/DNS failure must be recorded as an infrastructure error
(the model was never measured) and EXCLUDED from the FDRC validity denominator,
not counted as a model failure that tanks reportability."""
from __future__ import annotations

import socket

from src.adapters import is_account_error, is_transport_error
from src.evaluator.fdrc_validity import summarize_fdrc_validity
from src.orchestrator.full_duplex_orchestrator import failed_episode_stub

OVERLAY = {
    "speech_overlay_id": "fdrc_v2_001",
    "benchmark_track": "full_duplex_repair_to_commit",
    "repair_utterance": "đổi sang chế độ eco",
}
TASK = {"id": "base_001", "domain": "automotive", "initial_state": {}}


def _stub(error: BaseException) -> dict:
    return failed_episode_stub(
        agent="openai_realtime", model="gpt-realtime-mini", task=TASK,
        overlay=OVERLAY, mode="full_duplex_repair_to_commit",
        persona="vi_north_normal", audio_condition_id="clean", error=error,
    )


def test_dns_error_is_classified_as_transport():
    exc = socket.gaierror(11001, "getaddrinfo failed")
    assert is_transport_error(exc) is True


def test_transport_stub_is_tagged_infra_not_model_failure():
    stub = _stub(socket.gaierror(11001, "getaddrinfo failed"))
    assert stub.get("error_kind") == "transport"
    assert "EPISODE_TRANSPORT_ERROR" in stub["failure_types"]
    assert "EPISODE_RUNTIME_ERROR" not in stub["failure_types"]


def test_non_transport_stub_stays_runtime_error():
    stub = _stub(ValueError("model returned malformed item"))
    assert stub.get("error_kind") != "transport"
    assert "EPISODE_RUNTIME_ERROR" in stub["failure_types"]


def test_validity_excludes_transport_deaths_from_denominator():
    # 4 episodes the model actually ran (all valid) + 6 dead on DNS.
    ran = [
        {"fdrc_validity": {"valid": True}} for _ in range(4)
    ]
    dead = [_stub(socket.gaierror(11001, "getaddrinfo failed")) for _ in range(6)]
    summary = summarize_fdrc_validity(ran + dead)
    # validity is computed over the 4 measured episodes, not 10
    assert summary["fdrc_validity_rate"] == 1.0
    assert summary["infra_error_count"] == 6
    assert summary["measured_episode_count"] == 4


class _FakeConnectionClosed(Exception):
    """Mimics websockets.ConnectionClosedError, which is NOT a builtin ConnectionError."""


def test_insufficient_quota_is_classified_as_account_error():
    exc = _FakeConnectionClosed(
        "received 1013 (try again later) insufficient_quota.insufficient_quota"
    )
    assert is_account_error(exc) is True
    assert is_transport_error(exc) is False


def test_quota_stub_is_tagged_account_and_excluded_from_validity():
    quota = _FakeConnectionClosed("received 1013 (try again later) insufficient_quota")
    stub = _stub(quota)
    assert stub.get("error_kind") == "account"
    assert "EPISODE_ACCOUNT_ERROR" in stub["failure_types"]
    ran = [{"fdrc_validity": {"valid": True}} for _ in range(2)]
    summary = summarize_fdrc_validity(ran + [stub])
    assert summary["fdrc_validity_rate"] == 1.0
    assert summary["infra_error_count"] == 1
    assert summary["measured_episode_count"] == 2


def test_validity_unchanged_when_no_infra_errors():
    rows = [{"fdrc_validity": {"valid": True}}, {"fdrc_validity": {"valid": False, "reasons": ["INVALID_AUDIO"]}}]
    summary = summarize_fdrc_validity(rows)
    assert summary["fdrc_validity_rate"] == 0.5
    assert summary["infra_error_count"] == 0
