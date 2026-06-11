from __future__ import annotations

from collections import defaultdict

from .common import evaluate_common, summarize_shared
from .critical_slot_evaluator import evaluate_critical_slots
from .failure_taxonomy import FailureType, primary_failure


def evaluate_retention_episode(episode: dict, overlay: dict, task: dict) -> dict:
    result = evaluate_common(episode, task)
    slots = evaluate_critical_slots(
        overlay.get("expected_critical_slots", {}), result.get("captured_slots", {})
    )
    result["critical_slot_result"] = slots
    if not slots["passed"]:
        result["failure_types"].append(FailureType.CRITICAL_SLOT_ERROR)
        result["failure_types"] = list(dict.fromkeys(result["failure_types"]))
        result["primary_failure_type"] = primary_failure(result["failure_types"])
        result["scores"]["voice_pass"] = 0
        result["scores"]["final_pass"] = 0
    return result


def _rate(rows: list[dict]) -> float | None:
    return sum(row["scores"]["final_pass"] for row in rows) / len(rows) if rows else None


def summarize_retention(episodes: list[dict]) -> dict:
    by_mode = defaultdict(list)
    for episode in episodes:
        by_mode[episode["mode"]].append(episode)
    text = _rate(by_mode["text_baseline"])
    clean = _rate(by_mode["clean_voice"])
    cabin = _rate(by_mode["realistic_cabin_voice"])
    slots_correct = sum(e.get("critical_slot_result", {}).get("correct", 0) for e in episodes)
    slots_total = sum(e.get("critical_slot_result", {}).get("total", 0) for e in episodes)
    def gap(field: str) -> float | None:
        groups = defaultdict(list)
        for episode in episodes:
            if episode.get(field):
                groups[episode[field]].append(episode)
        rates = [_rate(rows) for rows in groups.values()]
        values = [value for value in rates if value is not None]
        return max(values) - min(values) if len(values) > 1 else None

    return {
        **summarize_shared(episodes),
        "text_pass_at_1": text,
        "clean_voice_pass_at_1": clean,
        "cabin_voice_pass_at_1": cabin,
        "clean_voice_retention": clean / text if text and clean is not None else None,
        "voice_capability_retention": cabin / text if text and cabin is not None else None,
        "voice_degradation_gap": text - cabin if text is not None and cabin is not None else None,
        "critical_slot_accuracy": slots_correct / slots_total if slots_total else 1.0,
        "accent_gap": gap("accent_region"),
        "speed_gap": gap("speech_speed"),
    }
