from __future__ import annotations

import argparse

from speech_interaction.env import load_benchmark_env
from speech_interaction.evaluator.retention_evaluator import (
    evaluate_retention_episode,
    summarize_retention,
)
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


def main() -> None:
    load_benchmark_env()
    parser = argparse.ArgumentParser(description="Evaluate Vivi clean and cabin voice retention.")
    parser.add_argument("--domains", default="automotive,navigation,media_phone")
    parser.add_argument("--overlays", default="speech_interaction/speech_task_overlays.jsonl")
    parser.add_argument("--personas", default="vi_north_normal,vi_central_normal,vi_south_normal")
    parser.add_argument("--audio-conditions", default="clean,cabin_noise")
    parser.add_argument("--episode-logs")
    parser.add_argument("--reference-agent", action="store_true")
    parser.add_argument("--agent", choices=["openai_realtime"], default=None)
    parser.add_argument("--model", default="gpt-realtime-mini")
    parser.add_argument("--output", default="results/voice_retention")
    args = parser.parse_args()
    domains = set(args.domains.split(","))
    condition_modes = {"clean": "clean_voice", "cabin_noise": "realistic_cabin_voice"}
    modes = [condition_modes[item] for item in args.audio_conditions.split(",")]
    tasks = load_base_tasks()
    preflight_validate_assets(tasks, load_overlays(args.overlays))
    overlays = select_overlays(args.overlays, "text_to_voice_retention", domains)
    if args.agent:
        episodes = run_agent_episodes(
            agent=args.agent,
            model=args.model,
            overlays=overlays,
            tasks=tasks,
            modes=modes,
            personas=args.personas.split(","),
        )
    else:
        episodes = load_or_build_episodes(
            args.episode_logs,
            overlays,
            tasks,
            modes,
            args.personas.split(","),
            args.reference_agent,
        )
    evaluated = evaluate_episodes(episodes, overlays, tasks, evaluate_retention_episode)
    evaluated = merge_existing_episodes(args.output, evaluated)
    save_results(args.output, evaluated, summarize_retention(evaluated))


if __name__ == "__main__":
    main()
