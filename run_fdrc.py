from __future__ import annotations

import argparse
import json
import os
import sys

from src.env import load_benchmark_env
from src.evaluator.fdrc_evaluator import evaluate_fdrc_episode, summarize_fdrc
from src.fdrc_run_inspector import (
    benchmark_report,
    comparable_fdrc_metrics,
    compare_layers,
    evaluator_metrics,
)
from src.io import load_base_tasks, load_overlays
from src.orchestrator.full_duplex_orchestrator import provider_for_agent
from src.runner import (
    annotate_episodes,
    evaluate_episodes,
    infer_run_kind,
    load_or_build_episodes,
    merge_existing_episodes,
    run_agent_episodes,
    save_results,
    select_overlays,
)
from src.schema import preflight_validate_assets
from src.tick_scheduler import schedule_timeline

FDRC_AUDIO_CONDITIONS = ("clean", "cabin_noise", "interaction_stress")
DEFAULT_FDRC_OVERLAYS = "data/jsonl/fdrc_golden_enriched_v2_90.jsonl"


def _inspection_command(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Inspect an existing FDRC run.")
    parser.add_argument("command", choices=["evaluate", "aggregate", "compare"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--results-dir", default="results")
    args = parser.parse_args(argv)
    if args.command == "evaluate":
        payload = benchmark_report(args.run_id, args.results_dir)
    elif args.command == "aggregate":
        payload = comparable_fdrc_metrics(evaluator_metrics(args.run_id, args.results_dir))
    else:
        payload = compare_layers(args.run_id, args.results_dir)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    load_benchmark_env()
    if len(sys.argv) > 1 and sys.argv[1] in {"evaluate", "aggregate", "compare"}:
        _inspection_command(sys.argv[1:])
        return
    parser = argparse.ArgumentParser(description="Evaluate Vivi full-duplex repair before commit.")
    parser.add_argument("--domains", default="automotive,navigation,media_phone")
    parser.add_argument("--overlays", default=DEFAULT_FDRC_OVERLAYS)
    parser.add_argument("--personas", default="vi_north_normal,vi_central_normal,vi_south_normal")
    parser.add_argument(
        "--audio-condition",
        choices=FDRC_AUDIO_CONDITIONS,
        default="interaction_stress",
        help="Legacy single audio condition for this run.",
    )
    parser.add_argument(
        "--audio-conditions",
        help="Comma-separated audio conditions. Overrides --audio-condition.",
    )
    parser.add_argument("--tick-ms", type=int, choices=[200], default=200)
    parser.add_argument(
        "--fdrc-yield-mode",
        choices=["native_yield", "client_cancel_yield"],
        default="native_yield",
        help="native_yield measures provider/model behavior; client_cancel_yield measures product-stack cancellation.",
    )
    parser.add_argument(
        "--user-simulator",
        choices=["off", "live", "replay"],
        default="off",
        help="off = scripted overlay turns (legacy); live = real LLM user simulator that "
        "listens and barges in dynamically (records a trace); replay = deterministic replay "
        "of a previously recorded live trace (falls back to live if none exists).",
    )
    parser.add_argument("--simulator-model", default="gpt-4o-mini")
    parser.add_argument("--sim-trace-dir", default="data/simulator_traces")
    parser.add_argument("--episode-logs")
    parser.add_argument("--reference-agent", action="store_true")
    parser.add_argument("--agent", choices=["openai_realtime", "gemini_live"], default=None)
    parser.add_argument("--model", default="gpt-realtime-mini")
    parser.add_argument("--output")
    parser.add_argument("--run-id")
    parser.add_argument("--run-kind", choices=["provider", "reference", "sample", "internal", "imported", "unknown"])
    parser.add_argument("--merge-existing", action="store_true")
    parser.add_argument(
        "--persona-from-overlay",
        action="store_true",
        help="Use each overlay's own accent_region/speech_speed (one episode per overlay) "
        "instead of multiplying overlays by the --personas list. For accent-balanced "
        "datasets where each overlay already encodes a specific accent.",
    )
    args = parser.parse_args()
    if args.agent == "gemini_live" and args.model == "gpt-realtime-mini":
        args.model = os.getenv("GEMINI_MODEL") or "gemini-2.0-flash-live-001"
    if args.output is None:
        args.output = (
            "results/reference/fdrc"
            if args.reference_agent
            else "results/provider/fdrc"
        )
    domains = set(args.domains.split(","))
    audio_conditions = [
        item.strip()
        for item in (args.audio_conditions or args.audio_condition).split(",")
        if item.strip()
    ]
    if not audio_conditions:
        parser.error("--audio-conditions must include at least one audio condition")
    invalid_audio_conditions = [
        item for item in audio_conditions if item not in FDRC_AUDIO_CONDITIONS
    ]
    if invalid_audio_conditions:
        parser.error(
            "--audio-conditions contains unsupported values: "
            + ", ".join(invalid_audio_conditions)
        )
    if args.user_simulator != "off" and not args.agent:
        parser.error("--user-simulator live/replay requires --agent (audio realtime run)")
    if args.user_simulator != "off":
        missing = [
            name
            for name in (
                "simulation_guidelines.md",
                "simulation_guidelines_voice.md",
                "simulation_guidelines_tools.md",
            )
            if not os.path.exists(os.path.join("data", "user_simulator", name))
        ]
        if missing:
            parser.error(
                "--user-simulator requires data/user_simulator guidelines; missing: "
                + ", ".join(missing)
            )
    tasks = load_base_tasks()
    normalized_overlays_path = args.overlays.replace("\\", "/")
    require_mvp_counts = normalized_overlays_path in {
        "data/jsonl/speech_task_overlays.jsonl",
        "src/speech_task_overlays.jsonl",
    }
    preflight_validate_assets(
        tasks,
        load_overlays(args.overlays),
        require_mvp_counts=require_mvp_counts,
    )
    overlays = select_overlays(args.overlays, "full_duplex_repair_to_commit", domains)
    if args.agent:
        episodes = run_agent_episodes(
            agent=args.agent,
            model=args.model,
            overlays=overlays,
            tasks=tasks,
            modes=["full_duplex_repair_to_commit"],
            personas=args.personas.split(","),
            tick_ms=args.tick_ms,
            fdrc_yield_mode=args.fdrc_yield_mode,
            persona_from_overlay=args.persona_from_overlay,
            audio_condition_ids=audio_conditions,
            simulator_mode=args.user_simulator,
            simulator_model=args.simulator_model,
            sim_trace_dir=args.sim_trace_dir,
        )
    else:
        episodes = load_or_build_episodes(
            args.episode_logs,
            overlays,
            tasks,
            ["full_duplex_repair_to_commit"],
            args.personas.split(","),
            args.reference_agent,
            audio_condition_ids=audio_conditions,
        )
    run_kind = args.run_kind or infer_run_kind(
        reference_agent=args.reference_agent,
        agent=args.agent,
        episode_logs=args.episode_logs,
        output=args.output,
    )
    episodes = annotate_episodes(
        episodes,
        run_id=args.run_id or args.output.split("/")[-1].split("\\")[-1],
        run_kind=run_kind,
        source_episode_log=args.episode_logs,
        agent="openai_as_vivi" if args.agent else None,
        provider=provider_for_agent(args.agent) if args.agent else None,
        model=args.model if args.agent else None,
        adapter=args.agent or ("reference_agent" if args.reference_agent else None),
    )
    for episode in episodes:
        episode["voice_events"] = schedule_timeline(
            episode.get("voice_events", []), args.tick_ms
        )
    evaluated = evaluate_episodes(episodes, overlays, tasks, evaluate_fdrc_episode)
    evaluated = merge_existing_episodes(args.output, evaluated, enabled=args.merge_existing)
    save_results(args.output, evaluated, summarize_fdrc(evaluated))


if __name__ == "__main__":
    main()
