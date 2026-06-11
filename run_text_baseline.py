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
    save_results,
    run_agent_episodes,
    select_overlays,
)
from speech_interaction.schema import preflight_validate_assets


def main() -> None:
    load_benchmark_env()
    parser = argparse.ArgumentParser(description="Evaluate Vivi text baselines for retention tasks.")
    parser.add_argument("--domains", default="automotive,navigation,media_phone")
    parser.add_argument("--task-split", choices=["speech_retention"], default="speech_retention")
    parser.add_argument("--overlays", default="speech_interaction/speech_task_overlays.jsonl")
    parser.add_argument("--episode-logs")
    parser.add_argument("--reference-agent", action="store_true")
    parser.add_argument("--agent", choices=["openai_text"], default=None)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--output", default="results/text_baseline")
    args = parser.parse_args()
    domains = set(args.domains.split(","))
    tasks = load_base_tasks()
    preflight_validate_assets(tasks, load_overlays(args.overlays))
    overlays = select_overlays(args.overlays, "text_to_voice_retention", domains)
    if args.agent:
        episodes = run_agent_episodes(
            agent=args.agent,
            model=args.model,
            overlays=overlays,
            tasks=tasks,
            modes=["text_baseline"],
            personas=["vi_north_normal"],
        )
    else:
        episodes = load_or_build_episodes(
            args.episode_logs,
            overlays,
            tasks,
            ["text_baseline"],
            ["vi_north_normal"],
            args.reference_agent,
        )
    evaluated = evaluate_episodes(episodes, overlays, tasks, evaluate_retention_episode)
    evaluated = merge_existing_episodes(args.output, evaluated)
    save_results(args.output, evaluated, summarize_retention(evaluated))


if __name__ == "__main__":
    main()
