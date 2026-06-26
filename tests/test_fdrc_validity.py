from __future__ import annotations

from src.evaluator.fdrc_validity import INVALID_TRANSCRIPT, classify_fdrc_validity


def _otherwise_valid_episode(repair_text: str | None):
    """An episode that passes every validity gate except (optionally) ASR match."""
    voice_events = [
        {"event": "assistant_speech_start", "t_ms": 100, "source": "observed"},
        {"event": "user_interrupt_start", "t_ms": 500, "source": "observed"},
        {"event": "repair_audio_start", "t_ms": 600, "source": "observed"},
        {"event": "repair_transcript_done", "t_ms": 800, "source": "observed"},
        {"event": "assistant_speech_stop", "t_ms": 900, "source": "observed"},
    ]
    normalized = [{"type": "user_audio_chunk_sent", "t_ms": 0}]
    if repair_text is not None:
        normalized.append({"type": "repair_transcript_done", "t_ms": 800, "text": repair_text})
    return {
        "voice_events": voice_events,
        "normalized_events": normalized,
        "tool_calls": [],
        "tool_results": [],
        "final_state": {},
    }


OVERLAY = {"repair_utterance": "đặt 24 độ"}


def test_garbage_repair_transcript_no_longer_invalidates_episode():
    # Native-audio providers mis-transcribe Vietnamese; ASR quality must not gate validity.
    episode = _otherwise_valid_episode("Dragii mei 20 de")
    out = classify_fdrc_validity(episode, OVERLAY)
    assert out["valid"] is True
    assert INVALID_TRANSCRIPT not in out["reasons"]
    assert out["repair_transcript_asr_match"] is False


def test_matching_repair_transcript_marks_asr_match_true():
    episode = _otherwise_valid_episode("đặt 24 độ ạ")
    out = classify_fdrc_validity(episode, OVERLAY)
    assert out["valid"] is True
    assert out["repair_transcript_asr_match"] is True


def test_no_repair_transcript_leaves_asr_match_unknown():
    episode = _otherwise_valid_episode(None)
    out = classify_fdrc_validity(episode, OVERLAY)
    assert out["valid"] is True
    assert out["repair_transcript_asr_match"] is None
