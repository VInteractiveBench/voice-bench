from __future__ import annotations

import csv
import json
import sys
import asyncio
import hashlib
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .io import load_base_tasks, load_overlays, read_jsonl, write_json, write_jsonl
from .orchestrator.full_duplex_orchestrator import failed_episode_stub, run_agent_episode
from .schema import MODE_TO_AUDIO_CONDITION, invalid_episode_result, validate_episode_log

REFERENCE_KINDS = {"reference", "sample", "internal"}


def select_overlays(path: str, track: str, domains: set[str] | None = None) -> list[dict]:
    rows = [row for row in load_overlays(path) if row["benchmark_track"] == track]
    return [row for row in rows if domains is None or row["domain"] in domains]


def _conditioned_episode_id(
    overlay: dict,
    mode: str,
    persona: str,
    audio_condition_id: str | None = None,
    *parts: str,
) -> str:
    base = f"{overlay['speech_overlay_id']}:{mode}:{persona}"
    if audio_condition_id:
        base = f"{base}:{audio_condition_id}"
    suffix = ":".join(str(part) for part in parts if part)
    return f"{base}:{suffix}" if suffix else base


def reference_episode(
    task: dict,
    overlay: dict,
    mode: str,
    persona: str,
    audio_condition_id: str | None = None,
) -> dict:
    expected_calls = overlay.get("expected_tool_calls", task.get("expected_tool_calls", []))
    events = deepcopy(overlay.get("voice_timeline", []))
    interrupt = next(
        (e["t_ms"] for e in events if e.get("event") == "user_interrupt_start"), None
    )
    if interrupt is not None:
        events.append({"t_ms": interrupt + 400, "event": "assistant_yielded"})
    persona_parts = persona.removeprefix("vi_").rsplit("_", 1)
    condition = audio_condition_id or MODE_TO_AUDIO_CONDITION[mode]
    if overlay.get("benchmark_track") == "voice_policy_command_gating":
        decision = (overlay.get("expected_behavior") or {}).get("type", "refuse")
        policy_tools = overlay.get("expected_tools", []) if decision == "execute" else []
        return {
            "episode_id": _conditioned_episode_id(
                overlay, mode, persona, audio_condition_id
            ),
            "base_task_id": task["id"],
            "speech_overlay_id": overlay["speech_overlay_id"],
            "benchmark_track": overlay["benchmark_track"],
            "domain": task["domain"],
            "mode": mode,
            "accent_region": persona_parts[0],
            "speech_speed": persona_parts[1],
            "audio_condition_id": condition,
            "run_kind": "reference",
            "is_reference": True,
            "agent": "reference_agent",
            "provider": None,
            "model": None,
            "adapter": "reference_agent",
            "source_episode_log": None,
            "initial_state": deepcopy(overlay.get("vehicle_state", {})),
            "final_state": deepcopy(overlay.get("expected_final_state", {})),
            "user_transcript": [overlay.get("user_utterance", "")],
            "assistant_transcript": [
                "Đã thực hiện." if decision == "execute"
                else "Xin lỗi, không thể thực hiện theo yêu cầu này."
            ],
            "captured_slots": {},
            "decision": decision,
            "clarification_targets": (overlay.get("required_question") or {}).get("must_ask_about", [])
            if decision == "clarify" else [],
            "response_claims_execution": decision == "execute",
            "tool_calls": [deepcopy(call) for call in policy_tools],
            "tool_results": [{"success": True} for _ in policy_tools],
            "validation_errors": [],
            "policy_violations": [],
            "voice_events": [],
            "latency": {"response_latency_ms": 300, "yield_latency_ms": None},
            "scores": {},
            "failure_types": [],
        }
    return {
        "episode_id": _conditioned_episode_id(
            overlay, mode, persona, audio_condition_id
        ),
        "base_task_id": task["id"],
        "speech_overlay_id": overlay["speech_overlay_id"],
        "benchmark_track": overlay["benchmark_track"],
        "domain": task["domain"],
        "mode": mode,
        "accent_region": persona_parts[0],
        "speech_speed": persona_parts[1],
        "audio_condition_id": condition,
        "run_kind": "reference",
        "is_reference": True,
        "agent": "reference_agent",
        "provider": None,
        "model": None,
        "adapter": "reference_agent",
        "source_episode_log": None,
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


def infer_run_kind(
    *,
    reference_agent: bool,
    agent: str | None,
    episode_logs: str | None,
    output: str,
) -> str:
    name = Path(output).name
    if reference_agent:
        return "reference"
    if name.startswith("_") or "internal" in name:
        return "internal"
    if "sample" in name:
        return "sample"
    if agent:
        return "provider"
    if episode_logs:
        return "imported"
    return "unknown"


def _episode_hash_payload(episode: dict) -> dict:
    return {key: value for key, value in episode.items() if key != "episode_set_hash"}


def episode_set_hash(episodes: list[dict]) -> str:
    payload = json.dumps(
        [_episode_hash_payload(episode) for episode in episodes],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dominant_track(episodes: list[dict]) -> str | None:
    tracks = Counter(
        episode.get("benchmark_track")
        for episode in episodes
        if episode.get("benchmark_track")
    )
    return tracks.most_common(1)[0][0] if tracks else None


def _stable_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _unique_values(episodes: list[dict], key: str) -> list[str]:
    return sorted(
        {
            str(episode.get(key))
            for episode in episodes
            if episode.get(key) not in (None, "")
        }
    )


def _episode_persona(episode: dict) -> str | None:
    if episode.get("persona"):
        return str(episode["persona"])
    accent = episode.get("accent_region")
    speed = episode.get("speech_speed")
    if accent and speed:
        return f"vi_{accent}_{speed}"
    return None


def build_run_metadata(episodes: list[dict]) -> dict:
    digest = episode_set_hash(episodes)
    run_ids = _unique_values(episodes, "run_id")
    run_kinds = _unique_values(episodes, "run_kind")
    overlay_ids = _unique_values(episodes, "speech_overlay_id")
    personas = sorted(
        {
            persona
            for persona in (_episode_persona(episode) for episode in episodes)
            if persona
        }
    )
    return {
        "run_id": run_ids[0] if len(run_ids) == 1 else None,
        "run_kind": run_kinds[0] if len(run_kinds) == 1 else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmark": dominant_track(episodes),
        "benchmark_track": dominant_track(episodes),
        "providers": _unique_values(episodes, "provider"),
        "models": _unique_values(episodes, "model"),
        "adapters": _unique_values(episodes, "adapter"),
        "fdrc_yield_modes": _unique_values(episodes, "fdrc_yield_mode"),
        "tick_ms": 200,
        "episode_set_hash": digest,
        "overlay_hash": _stable_hash(overlay_ids),
        "persona_hash": _stable_hash(personas),
        "domains": _unique_values(episodes, "domain"),
        "personas": personas,
        "audio_conditions": _unique_values(episodes, "audio_condition_id"),
        "episode_count": len(episodes),
        "provider_episode_count": sum(
            1 for episode in episodes if episode.get("run_kind") == "provider"
        ),
        "reference_episode_count": sum(
            1 for episode in episodes if episode.get("run_kind") in REFERENCE_KINDS
        ),
    }


def annotate_episodes(
    episodes: list[dict],
    *,
    run_id: str,
    run_kind: str,
    source_episode_log: str | None,
    agent: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    adapter: str | None = None,
    created_at: str | None = None,
) -> list[dict]:
    stamped = []
    created = created_at or datetime.now(timezone.utc).isoformat()
    is_reference = run_kind in REFERENCE_KINDS
    for episode in episodes:
        row = deepcopy(episode)
        row["run_id"] = run_id
        row["run_kind"] = run_kind
        row["is_reference"] = bool(row.get("is_reference", is_reference))
        row["agent"] = agent if agent is not None else row.get("agent")
        row["provider"] = provider if provider is not None else row.get("provider")
        row["model"] = model if model is not None else row.get("model")
        row["adapter"] = adapter if adapter is not None else row.get("adapter")
        row["created_at"] = created
        row["source_episode_log"] = source_episode_log
        if not row.get("persona"):
            row["persona"] = _episode_persona(row)
        stamped.append(row)
    digest = episode_set_hash(stamped)
    for row in stamped:
        row["episode_set_hash"] = digest
    return stamped


def load_or_build_episodes(
    episode_logs: str | None,
    overlays: list[dict],
    tasks: dict[str, dict],
    modes: list[str],
    personas: list[str],
    reference_agent: bool,
    audio_condition_ids: list[str] | None = None,
) -> list[dict]:
    if episode_logs:
        return read_jsonl(episode_logs)
    if not reference_agent:
        raise ValueError("--episode-logs is required unless --reference-agent is set")
    return [
        reference_episode(
            tasks[overlay["base_task_id"]],
            overlay,
            mode,
            persona,
            audio_condition_id=audio_condition_id,
        )
        for overlay in overlays
        for mode in modes
        for persona in personas
        for audio_condition_id in (audio_condition_ids or [None])
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
    fdrc_yield_mode: str = "native_yield",
    persona_from_overlay: bool = False,
    audio_condition_ids: list[str] | None = None,
    simulator_mode: str = "off",
    simulator_model: str = "gpt-4o-mini",
    sim_trace_dir: str = "data/simulator_traces",
) -> list[dict]:
    episodes = []
    for overlay in overlays:
        task = tasks[overlay["base_task_id"]]
        # Accent-balanced datasets (e.g. fdrc_balanced_v2) bake one accent per
        # overlay, so the persona must come from the overlay itself — multiplying
        # by the persona list would duplicate every row across accents.
        episode_personas = (
            [f"vi_{overlay['accent_region']}_{overlay['speech_speed']}"]
            if persona_from_overlay
            else personas
        )
        for mode in modes:
            for persona in episode_personas:
                for audio_condition_id in (audio_condition_ids or [None]):
                    episodes.append(
                        await _run_one_episode_resilient(
                            agent=agent,
                            model=model,
                            task=task,
                            overlay=overlay,
                            mode=mode,
                            persona=persona,
                            tick_ms=tick_ms,
                            fdrc_yield_mode=fdrc_yield_mode,
                            audio_condition_id=audio_condition_id,
                            simulator_mode=simulator_mode,
                            simulator_model=simulator_model,
                            sim_trace_dir=sim_trace_dir,
                        )
                    )
    return episodes


async def _run_one_episode_resilient(*, agent, model, task, overlay, mode, persona,
                                     tick_ms, fdrc_yield_mode, audio_condition_id,
                                     simulator_mode, simulator_model, sim_trace_dir):
    """Run one episode; on a transient runtime failure (e.g. a realtime websocket drop)
    retry once, then record a failed-episode stub so a single bad episode never aborts
    the whole batch (which would discard every already-completed episode)."""
    last_error: BaseException | None = None
    for attempt in (1, 2):
        try:
            return await run_agent_episode(
                agent=agent, model=model, task=task, overlay=overlay, mode=mode,
                persona=persona, tick_ms=tick_ms, fdrc_yield_mode=fdrc_yield_mode,
                audio_condition_id=audio_condition_id, simulator_mode=simulator_mode,
                simulator_model=simulator_model, sim_trace_dir=sim_trace_dir,
            )
        except Exception as exc:  # noqa: BLE001 - episode isolation is intentional
            last_error = exc
            overlay_id = overlay.get("speech_overlay_id")
            print(
                f"[runner] episode failed (attempt {attempt}/2) "
                f"overlay={overlay_id} persona={persona} agent={agent}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
    return failed_episode_stub(
        agent=agent, model=model, task=task, overlay=overlay, mode=mode,
        persona=persona, audio_condition_id=audio_condition_id,
        error=last_error, fdrc_yield_mode=fdrc_yield_mode,
    )


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


def merge_existing_episodes(output: str, episodes: list[dict], *, enabled: bool = True) -> list[dict]:
    if not enabled:
        return episodes
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


def metrics_with_metadata(episodes: list[dict], metrics: dict) -> dict:
    digest = episode_set_hash(episodes)
    tracks = {episode.get("benchmark_track") for episode in episodes if episode.get("benchmark_track")}
    run_metadata = build_run_metadata(episodes)
    run_metadata = {
        **run_metadata,
        "is_reference": any(bool(episode.get("is_reference")) for episode in episodes),
        "mixed_track": len(tracks) > 1,
    }
    return {
        **metrics,
        "benchmark_track": dominant_track(episodes),
        "episode_set_hash": digest,
        "run_metadata": run_metadata,
        "metadata_hash": _stable_hash(run_metadata),
    }


def save_results(output: str, episodes: list[dict], metrics: dict) -> None:
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    enriched_metrics = metrics_with_metadata(episodes, metrics)
    write_jsonl(target / "episodes.jsonl", episodes)
    write_json(target / "metrics.json", enriched_metrics)
    write_json(target / "run_metadata.json", enriched_metrics["run_metadata"])


def _episode_kind(episode: dict) -> str:
    if episode.get("is_reference"):
        return "reference"
    return str(episode.get("run_kind") or "unknown")


def reliability_summary(episodes: list[dict]) -> dict:
    kinds = Counter(_episode_kind(episode) for episode in episodes)
    tracks = {episode.get("benchmark_track") for episode in episodes if episode.get("benchmark_track")}
    return {
        "provider_count": kinds.get("provider", 0),
        "reference_count": kinds.get("reference", 0)
        + kinds.get("sample", 0)
        + kinds.get("internal", 0),
        "unknown_count": kinds.get("unknown", 0),
        "invalid_fdrc_timing_episodes": sum(
            1
            for episode in episodes
            if episode.get("benchmark_track") == "full_duplex_repair_to_commit"
            and "MISSING_OBSERVED_EVENT" in (episode.get("failure_types") or [])
        ),
        "mixed_track": len(tracks) > 1,
    }


def generate_report(
    fdrc_metrics: dict,
    episodes: list[dict],
    output: str,
    *,
    allow_reference: bool = False,
) -> None:
    if not allow_reference and any(_episode_kind(episode) != "provider" for episode in episodes):
        raise ValueError(
            "Report inputs include reference, sample, internal, imported, or unknown episodes. "
            "Pass --allow-reference to generate a non-performance report."
        )
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    failures = [e for e in episodes if not e.get("scores", {}).get("final_pass")]
    primary_counts = Counter(
        episode.get("primary_failure_type") or "UNKNOWN" for episode in failures
    )
    failure_counts = Counter(
        failure for episode in failures for failure in episode.get("failure_types", [])
    )
    reliability = reliability_summary(episodes)
    lines = [
        "# Vivi-τVoice-CarBench-VN Report",
        "",
        "Synthetic reference-agent runs validate benchmark plumbing only and must not be reported as Vivi model performance.",
        "",
        "## Reliability Summary",
        "",
        "| Field | Value |",
        "|---|---:|",
        *[f"| {key} | {value} |" for key, value in reliability.items()],
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
