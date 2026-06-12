from __future__ import annotations

import argparse

from src.env import load_benchmark_env
from src.evaluator.retention_evaluator import (
    evaluate_retention_episode,
    summarize_retention,
)
from src.io import load_base_tasks, load_overlays
from src.runner import (
    annotate_episodes,
    evaluate_episodes,
    infer_run_kind,
    load_or_build_episodes,
    merge_existing_episodes,
    save_results,
    run_agent_episodes,
    select_overlays,
)
from src.schema import preflight_validate_assets


def main() -> None:
    load_benchmark_env()
    parser = argparse.ArgumentParser(description="Evaluate Vivi text baselines for retention tasks.")
    parser.add_argument("--domains", default="automotive,navigation,media_phone")
    parser.add_argument("--task-split", choices=["speech_retention"], default="speech_retention")
    parser.add_argument("--overlays", default="src/speech_task_overlays.jsonl")
    parser.add_argument("--episode-logs")
    parser.add_argument("--reference-agent", action="store_true")
    parser.add_argument("--agent", choices=["openai_text"], default=None)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--output")
    parser.add_argument("--run-id")
    parser.add_argument("--run-kind", choices=["provider", "reference", "sample", "internal", "imported", "unknown"])
    parser.add_argument("--merge-existing", action="store_true")
    args = parser.parse_args()
    if args.output is None:
        args.output = (
            "results/reference/text_baseline"
            if args.reference_agent
            else "results/provider/text_baseline"
        )
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
    evaluated = evaluate_episodes(episodes, overlays, tasks, evaluate_retention_episode)
    evaluated = merge_existing_episodes(args.output, evaluated, enabled=args.merge_existing)
    save_results(args.output, evaluated, summarize_retention(evaluated))


if __name__ == "__main__":
    main()
