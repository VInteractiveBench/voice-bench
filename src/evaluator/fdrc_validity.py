from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .voice_event_evaluator import observed_event_time

VALID = "VALID"
INVALID_AUDIO = "INVALID_AUDIO"
INVALID_EVIDENCE = "INVALID_EVIDENCE"
INVALID_TRANSCRIPT = "INVALID_TRANSCRIPT"
INVALID_TOOL_RESULT = "INVALID_TOOL_RESULT"
INVALID_FINAL_STATE = "INVALID_FINAL_STATE"

REFERENCE_KINDS = {"reference", "sample", "internal"}


def _is_reference_episode(episode: dict[str, Any]) -> bool:
    return bool(episode.get("is_reference")) or episode.get("run_kind") in REFERENCE_KINDS


def _tokens(text: str) -> set[str]:
    normalized = text.casefold()
    return {
        token
        for token in re.findall(r"[\wÀ-ỹ]+", normalized, flags=re.UNICODE)
        if len(token) >= 2
    }


def _observed_transcript_after(
    events: list[dict[str, Any]], after_ms: int | None
) -> str | None:
    for event in events:
        if event.get("type") not in {"user_transcript_done", "repair_transcript_done"}:
            continue
        t_ms = event.get("t_ms")
        if not isinstance(t_ms, int):
            continue
        if after_ms is not None and t_ms < after_ms:
            continue
        text = event.get("text")
        if isinstance(text, str) and text.strip():
            return text
    return None


def _transcript_matches_expected(observed: str | None, expected: str) -> bool:
    if not observed:
        return False
    expected_tokens = _tokens(expected)
    observed_tokens = _tokens(observed)
    if not expected_tokens:
        return True
    return bool(expected_tokens & observed_tokens)


def classify_fdrc_validity(
    episode: dict[str, Any],
    overlay: dict[str, Any],
) -> dict[str, Any]:
    if _is_reference_episode(episode):
        return {"status": VALID, "valid": True, "reasons": []}

    reasons: list[str] = []
    events = [event for event in episode.get("voice_events", []) or [] if isinstance(event, dict)]
    normalized = [
        event for event in episode.get("normalized_events", []) or [] if isinstance(event, dict)
    ]
    required_observed_events = [
        "assistant_speech_start",
        "user_interrupt_start",
        "repair_audio_start",
        "repair_transcript_done",
    ]
    missing_observed = [
        event_name
        for event_name in required_observed_events
        if observed_event_time(events, event_name) is None
    ]
    if observed_event_time(events, "assistant_yielded") is None and observed_event_time(
        events, "assistant_speech_stop"
    ) is None:
        missing_observed.append("assistant_yielded")
    if missing_observed:
        reasons.append(INVALID_EVIDENCE)

    has_audio_evidence = any(
        event.get("type") == "user_audio_chunk_sent" for event in normalized
    ) or observed_event_time(events, "repair_audio_start") is not None
    if not has_audio_evidence:
        reasons.append(INVALID_AUDIO)

    interrupt = observed_event_time(events, "user_interrupt_start")
    repair_transcript = _observed_transcript_after(normalized, interrupt)
    if repair_transcript and not _transcript_matches_expected(
        repair_transcript, overlay.get("repair_utterance", "")
    ):
        reasons.append(INVALID_TRANSCRIPT)

    tool_calls = episode.get("tool_calls", []) or []
    if tool_calls:
        tool_results = episode.get("tool_results", []) or []
        has_tool_result_event = any(
            event.get("type") == "tool_result" and isinstance(event.get("t_ms"), int)
            for event in normalized
        )
        if len(tool_results) != len(tool_calls) or not has_tool_result_event:
            reasons.append(INVALID_TOOL_RESULT)

    if not isinstance(episode.get("final_state"), dict):
        reasons.append(INVALID_FINAL_STATE)

    deduped = list(dict.fromkeys(reasons))
    return {
        "status": VALID if not deduped else "INVALID",
        "valid": not deduped,
        "reasons": deduped,
        "observed_repair_transcript": repair_transcript,
        "missing_observed_events": missing_observed,
    }


def summarize_fdrc_validity(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(episodes)
    valid_rows = [episode for episode in episodes if episode.get("fdrc_validity", {}).get("valid")]
    invalid_rows = [episode for episode in episodes if episode not in valid_rows]
    reason_counts = Counter(
        reason
        for episode in invalid_rows
        for reason in episode.get("fdrc_validity", {}).get("reasons", []) or ["INVALID_UNKNOWN"]
    )
    return {
        "valid_episode_count": len(valid_rows),
        "invalid_episode_count": len(invalid_rows),
        "fdrc_validity_rate": len(valid_rows) / total if total else None,
        "validity_failure_counts": [
            {"key": key, "count": count} for key, count in reason_counts.most_common()
        ],
    }
