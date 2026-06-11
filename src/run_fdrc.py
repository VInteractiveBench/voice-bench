from __future__ import annotations

import argparse

from speech_interaction.env import load_benchmark_env
from speech_interaction.evaluator.fdrc_evaluator import evaluate_fdrc_episode, summarize_fdrc
from speech_interaction.io import load_base_tasks, load_overlays
from speech_interaction.runner import (
    evaluate_episodes,
    load_or_build_episodes,
    merge_existing_episodes,
    run_agent_episodes,
    save_results,
    select_overlays,
)
from speech_interaction.schema import preflight_validate_assets
from speech_interaction.tick_scheduler import schedule_timeline


def main() -> None:
    load_benchmark_env()
    parser = argparse.ArgumentParser(description="Evaluate Vivi full-duplex repair before commit.")
    parser.add_argument("--domains", default="automotive,navigation,media_phone")
    parser.add_argument("--overlays", default="speech_interaction/speech_task_overlays.jsonl")
    parser.add_argument("--personas", default="vi_north_normal,vi_central_normal,vi_south_normal")
    parser.add_argument("--audio-condition", choices=["interaction_stress"], default="interaction_stress")
    parser.add_argument("--tick-ms", type=int, choices=[200], default=200)
    parser.add_argument("--episode-logs")
    parser.add_argument("--reference-agent", action="store_true")
    parser.add_argument("--agent", choices=["openai_realtime"], default=None)
    parser.add_argument("--model", default="gpt-realtime-mini")
    parser.add_argument("--output", default="results/fdrc")
    args = parser.parse_args()
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
    for episode in episodes:
        episode["voice_events"] = schedule_timeline(
            episode.get("voice_events", []), args.tick_ms
        )
    evaluated = evaluate_episodes(episodes, overlays, tasks, evaluate_fdrc_episode)
    evaluated = merge_existing_episodes(args.output, evaluated)
    save_results(args.output, evaluated, summarize_fdrc(evaluated))


if __name__ == "__main__":
    main()
