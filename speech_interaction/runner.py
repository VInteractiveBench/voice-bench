from __future__ import annotations

import csv
import json
import asyncio
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Callable

from .io import load_base_tasks, load_overlays, read_jsonl, write_json, write_jsonl
from .orchestrator.full_duplex_orchestrator import run_agent_episode
from .schema import MODE_TO_AUDIO_CONDITION, invalid_episode_result, validate_episode_log


def select_overlays(path: str, track: str, domains: set[str] | None = None) -> list[dict]:
    rows = [row for row in load_overlays(path) if row["benchmark_track"] == track]
    return [row for row in rows if domains is None or row["domain"] in domains]


def reference_episode(task: dict, overlay: dict, mode: str, persona: str) -> dict:
    expected_calls = overlay.get("expected_tool_calls", task.get("expected_tool_calls", []))
    events = deepcopy(overlay.get("voice_timeline", []))
    interrupt = next(
        (e["t_ms"] for e in events if e.get("event") == "user_interrupt_start"), None
    )
    if interrupt is not None:
        events.append({"t_ms": interrupt + 400, "event": "assistant_yielded"})
    persona_parts = persona.removeprefix("vi_").rsplit("_", 1)
    return {
        "episode_id": f"{overlay['speech_overlay_id']}:{mode}:{persona}",
        "base_task_id": task["id"],
        "speech_overlay_id": overlay["speech_overlay_id"],
        "benchmark_track": overlay["benchmark_track"],
        "domain": task["domain"],
        "mode": mode,
        "accent_region": persona_parts[0],
        "speech_speed": persona_parts[1],
        "audio_condition_id": MODE_TO_AUDIO_CONDITION[mode],
        "initial_state": deepcopy(task.get("initial_state", {})),
        "final_state": deepcopy(overlay.get("expected_final_state", task.get("expected_final_state", {}))),
        "user_transcript": [overlay.get("spoken_utterance") or overlay.get("initial_spoken_utterance", "")],
        "assistant_transcript": ["Đã thực hiện yêu cầu cuối cùng của bạn."],
        "captured_slots": deepcopy(overlay.get("expected_critical_slots", {})),
        "tool_calls": [{**deepcopy(call), "t_ms": 4600} for call in expected_calls],
        "tool_results": [{"success": True} for _ in expected_calls],
        "validation_errors": [],
        "policy_violations": [],
        "voice_events": events,
        "latency": {"response_latency_ms": 300, "yield_latency_ms": 400 if interrupt else None},
        "scores": {},
        "failure_types": [],
    }


def load_or_build_episodes(
    episode_logs: str | None,
    overlays: list[dict],
    tasks: dict[str, dict],
    modes: list[str],
    personas: list[str],
    reference_agent: bool,
) -> list[dict]:
    if episode_logs:
        return read_jsonl(episode_logs)
    if not reference_agent:
        raise ValueError("--episode-logs is required unless --reference-agent is set")
    return [
        reference_episode(tasks[overlay["base_task_id"]], overlay, mode, persona)
        for overlay in overlays
        for mode in modes
        for persona in personas
    ]


async def run_agent_episodes_async(
    *,
    agent: str,
    model: str,
    overlays: list[dict],
    tasks: dict[str, dict],
    modes: list[str],
    personas: list[str],
    tick_ms: int = 200,
) -> list[dict]:
    episodes = []
    for overlay in overlays:
        task = tasks[overlay["base_task_id"]]
        for mode in modes:
            for persona in personas:
                episodes.append(
                    await run_agent_episode(
                        agent=agent,
                        model=model,
                        task=task,
                        overlay=overlay,
                        mode=mode,
                        persona=persona,
                        tick_ms=tick_ms,
                    )
                )
    return episodes


def run_agent_episodes(**kwargs) -> list[dict]:
    return asyncio.run(run_agent_episodes_async(**kwargs))


def evaluate_episodes(
    episodes: list[dict],
    overlays: list[dict],
    tasks: dict[str, dict],
    evaluator: Callable[[dict, dict, dict], dict],
) -> list[dict]:
    overlay_map = {row["speech_overlay_id"]: row for row in overlays}
    evaluated = []
    for episode in episodes:
        overlay = overlay_map.get(episode.get("speech_overlay_id"))
        task = tasks.get(episode.get("base_task_id"))
        if overlay is None or task is None:
            errors = []
            if overlay is None:
                errors.append(
                    {
                        "field": "episode.speech_overlay_id",
                        "reason": "unknown_overlay",
                        "value": episode.get("speech_overlay_id"),
                    }
                )
            if task is None:
                errors.append(
                    {
                        "field": "episode.base_task_id",
                        "reason": "unknown_task",
                        "value": episode.get("base_task_id"),
                    }
                )
            evaluated.append(invalid_episode_result(episode, errors))
            continue
        errors = validate_episode_log(episode, overlay, task)
        if errors:
            evaluated.append(invalid_episode_result(episode, errors))
            continue
        evaluated.append(evaluator(episode, overlay, task))
    return evaluated


def merge_existing_episodes(output: str, episodes: list[dict]) -> list[dict]:
    path = Path(output) / "episodes.jsonl"
    if not path.exists():
        return episodes
    merged: dict[str, dict] = {}
    for episode in [*read_jsonl(path), *episodes]:
        key = episode.get("episode_id") or json.dumps(
            {
                "base_task_id": episode.get("base_task_id"),
                "speech_overlay_id": episode.get("speech_overlay_id"),
                "mode": episode.get("mode"),
                "accent_region": episode.get("accent_region"),
                "speech_speed": episode.get("speech_speed"),
            },
            sort_keys=True,
        )
        merged[key] = episode
    return list(merged.values())


def save_results(output: str, episodes: list[dict], metrics: dict) -> None:
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    write_jsonl(target / "episodes.jsonl", episodes)
    write_json(target / "metrics.json", metrics)


def generate_report(retention_metrics: dict, fdrc_metrics: dict, episodes: list[dict], output: str) -> None:
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    failures = [e for e in episodes if not e.get("scores", {}).get("final_pass")]
    primary_counts = Counter(
        episode.get("primary_failure_type") or "UNKNOWN" for episode in failures
    )
    failure_counts = Counter(
        failure for episode in failures for failure in episode.get("failure_types", [])
    )
    lines = [
        "# Vivi-τVoice-CarBench-VN Report",
        "",
        "Synthetic reference-agent runs validate benchmark plumbing only and must not be reported as Vivi model performance.",
        "",
        "## Text-to-Voice Capability Retention",
        "",
        "| Metric | Value |",
        "|---|---:|",
        *[f"| {key} | {value} |" for key, value in retention_metrics.items()],
        "",
        "## Full-Duplex Repair-to-Commit",
        "",
        "| Metric | Value |",
        "|---|---:|",
        *[f"| {key} | {value} |" for key, value in fdrc_metrics.items()],
        "",
        "## Failure Summary",
        "",
        f"Failed episodes: {len(failures)}",
        "",
        "| Primary failure | Count |",
        "|---|---:|",
        *[f"| {key} | {value} |" for key, value in primary_counts.most_common()],
        "",
        "| Failure type | Count |",
        "|---|---:|",
        *[f"| {key} | {value} |" for key, value in failure_counts.most_common()],
    ]
    (target / "vivi_voice_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (target / "vivi_voice_failures.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["episode_id", "base_task_id", "speech_overlay_id", "primary_failure_type", "failure_types"],
        )
        writer.writeheader()
        for episode in failures:
            writer.writerow(
                {
                    "episode_id": episode.get("episode_id"),
                    "base_task_id": episode.get("base_task_id"),
                    "speech_overlay_id": episode.get("speech_overlay_id"),
                    "primary_failure_type": episode.get("primary_failure_type"),
                    "failure_types": json.dumps(episode.get("failure_types", []), ensure_ascii=False),
                }
            )
