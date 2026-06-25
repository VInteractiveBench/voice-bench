from __future__ import annotations

import argparse
import os

from src.env import load_benchmark_env
from src.evaluator.policy_gating_evaluator import (
    evaluate_policy_gating_episode,
    summarize_policy_gating,
)
from src.io import load_base_tasks, load_overlays
from src.orchestrator.full_duplex_orchestrator import provider_for_agent
from src.orchestrator.policy_outcome import annotate_policy_episode
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
from src.schema import POLICY_TRACK, preflight_validate_assets

MODE = "voice_policy_gating"


def main() -> None:
    load_benchmark_env()
    parser = argparse.ArgumentParser(description="Evaluate Vivi policy-grounded voice command gating.")
    parser.add_argument("--domains", default="automotive,navigation,media_phone")
    parser.add_argument("--overlays", default="src/speech_task_overlays.jsonl")
    parser.add_argument("--personas", default="vi_north_normal,vi_central_normal,vi_south_normal")
    parser.add_argument("--episode-logs")
    parser.add_argument("--reference-agent", action="store_true")
    parser.add_argument("--agent", choices=["openai_realtime", "gemini_live"], default=None)
    parser.add_argument("--model", default="gpt-realtime-mini")
    parser.add_argument("--output")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--run-kind",
        choices=["provider", "reference", "sample", "internal", "imported", "unknown"],
    )
    parser.add_argument("--merge-existing", action="store_true")
    args = parser.parse_args()
    if args.agent == "gemini_live" and args.model == "gpt-realtime-mini":
        args.model = os.getenv("GEMINI_MODEL") or "gemini-2.0-flash-live-001"
    if args.output is None:
        args.output = (
            "results/reference/policy_gating"
            if args.reference_agent
            else "results/provider/policy_gating"
        )
    domains = set(args.domains.split(","))
    tasks = load_base_tasks()
    preflight_validate_assets(tasks, load_overlays(args.overlays))
    overlays = select_overlays(args.overlays, POLICY_TRACK, domains)
    if args.agent:
        episodes = run_agent_episodes(
            agent=args.agent,
            model=args.model,
            overlays=overlays,
            tasks=tasks,
            modes=[MODE],
            personas=args.personas.split(","),
        )
        overlay_map = {o["speech_overlay_id"]: o for o in overlays}
        for episode in episodes:
            overlay = overlay_map.get(episode.get("speech_overlay_id"))
            if overlay is not None:
                annotate_policy_episode(episode, overlay)
    else:
        episodes = load_or_build_episodes(
            args.episode_logs,
            overlays,
            tasks,
            [MODE],
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
        provider=provider_for_agent(args.agent) if args.agent else None,
        model=args.model if args.agent else None,
        adapter=args.agent or ("reference_agent" if args.reference_agent else None),
    )
    evaluated = evaluate_episodes(episodes, overlays, tasks, evaluate_policy_gating_episode)
    evaluated = merge_existing_episodes(args.output, evaluated, enabled=args.merge_existing)
    save_results(args.output, evaluated, summarize_policy_gating(evaluated))


if __name__ == "__main__":
    main()
