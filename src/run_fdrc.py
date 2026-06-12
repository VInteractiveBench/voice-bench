from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--overlays", default="src/speech_task_overlays.jsonl")
    parser.add_argument("--personas", default="vi_north_normal,vi_central_normal,vi_south_normal")
    parser.add_argument("--audio-condition", choices=["interaction_stress"], default="interaction_stress")
    parser.add_argument("--tick-ms", type=int, choices=[200], default=200)
    parser.add_argument("--episode-logs")
    parser.add_argument("--reference-agent", action="store_true")
    parser.add_argument("--agent", choices=["openai_realtime"], default=None)
    parser.add_argument("--model", default="gpt-realtime-mini")
    parser.add_argument("--output")
    parser.add_argument("--run-id")
    parser.add_argument("--run-kind", choices=["provider", "reference", "sample", "internal", "imported", "unknown"])
    parser.add_argument("--merge-existing", action="store_true")
    args = parser.parse_args()
    if args.output is None:
        args.output = (
            "results/reference/fdrc"
            if args.reference_agent
            else "results/provider/fdrc"
        )
    domains = set(args.domains.split(","))
    tasks = load_base_tasks()
    preflight_validate_assets(tasks, load_overlays(args.overlays))
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
        )
    else:
        episodes = load_or_build_episodes(
            args.episode_logs,
            overlays,
            tasks,
            ["full_duplex_repair_to_commit"],
            args.personas.split(","),
            args.reference_agent,
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
        provider="openai" if args.agent else None,
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
