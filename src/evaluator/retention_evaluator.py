from __future__ import annotations

from collections import defaultdict

from .common import evaluate_common, summarize_shared
from .critical_slot_evaluator import evaluate_critical_slots
from .failure_taxonomy import FailureType, primary_failure

RETENTION_MODES = ("text_baseline", "clean_voice", "realistic_cabin_voice")


def retention_pair_id(episode: dict) -> str:
    return "|".join(
        str(episode.get(key, ""))
        for key in ("domain", "base_task_id", "speech_overlay_id")
    )


def evaluate_retention_episode(episode: dict, overlay: dict, task: dict) -> dict:
    result = evaluate_common(episode, task)
    result["retention_pair_id"] = retention_pair_id(result)
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


def _score_rate(rows: list[dict], score: str) -> float | None:
    scored = [row for row in rows if row.get("scores", {}).get(score) is not None]
    return (
        sum(row.get("scores", {}).get(score) for row in scored) / len(scored)
        if scored
        else None
    )


def _slot_rate(rows: list[dict]) -> float | None:
    correct = sum(row.get("critical_slot_result", {}).get("correct", 0) for row in rows)
    total = sum(row.get("critical_slot_result", {}).get("total", 0) for row in rows)
    return correct / total if total else None


def _complete_pair_rows(episodes: list[dict]) -> tuple[list[dict], int, int]:
    groups = defaultdict(list)
    for episode in episodes:
        if episode.get("benchmark_track") == "text_to_voice_retention":
            groups[episode.get("retention_pair_id") or retention_pair_id(episode)].append(episode)
    complete_ids = {
        pair_id
        for pair_id, rows in groups.items()
        if all(any(row.get("mode") == mode for row in rows) for mode in RETENTION_MODES)
    }
    for episode in episodes:
        if episode.get("benchmark_track") == "text_to_voice_retention":
            episode["retention_pair_complete"] = (
                (episode.get("retention_pair_id") or retention_pair_id(episode)) in complete_ids
            )
    return (
        [
            row
            for pair_id, rows in groups.items()
            if pair_id in complete_ids
            for row in rows
        ],
        len(complete_ids),
        len(groups) - len(complete_ids),
    )


def _degradation(rows: list[dict]) -> dict:
    by_mode = defaultdict(list)
    for row in rows:
        by_mode[row.get("mode")].append(row)
    result = {}
    for voice_mode in ("clean_voice", "realistic_cabin_voice"):
        result[voice_mode] = {
            "final_pass": _diff_rate(by_mode["text_baseline"], by_mode[voice_mode], "final_pass"),
            "tool_exact_match": _diff_rate(by_mode["text_baseline"], by_mode[voice_mode], "tool_exact_match"),
            "argument_exact_match": _diff_rate(by_mode["text_baseline"], by_mode[voice_mode], "argument_exact_match"),
            "state_match": _diff_rate(by_mode["text_baseline"], by_mode[voice_mode], "state_match"),
            "critical_slot_accuracy": _slot_diff(by_mode["text_baseline"], by_mode[voice_mode]),
        }
    return result


def _diff_rate(text_rows: list[dict], voice_rows: list[dict], score: str) -> float | None:
    text = _score_rate(text_rows, score)
    voice = _score_rate(voice_rows, score)
    return text - voice if text is not None and voice is not None else None


def _slot_diff(text_rows: list[dict], voice_rows: list[dict]) -> float | None:
    text = _slot_rate(text_rows)
    voice = _slot_rate(voice_rows)
    return text - voice if text is not None and voice is not None else None


def summarize_retention(episodes: list[dict]) -> dict:
    complete_rows, complete_pair_count, incomplete_pair_count = _complete_pair_rows(episodes)
    metric_rows = complete_rows if complete_rows else episodes
    by_mode = defaultdict(list)
    for episode in metric_rows:
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
        "critical_slot_accuracy": slots_correct / slots_total if slots_total else None,
        "complete_pair_count": complete_pair_count,
        "incomplete_pair_count": incomplete_pair_count,
        "degradation_by_component": _degradation(complete_rows) if complete_rows else {},
        "accent_gap": gap("accent_region"),
        "speed_gap": gap("speech_speed"),
    }
