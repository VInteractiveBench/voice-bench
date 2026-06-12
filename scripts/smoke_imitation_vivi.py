"""One-episode smoke test of the OpenAI-as-Vivi (imitation Vivi) real agent path.

Runs a single retention overlay through the live OpenAI adapter -> MockToolServer
-> retention evaluator, bypassing the 30+30 MVP preflight so we make exactly one
real API call before committing to a full benchmark run.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    load_dotenv(ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        print("FAIL: OPENAI_API_KEY missing")
        return 1

    from src.io import load_base_tasks, load_overlays
    from src.runner import run_agent_episodes
    from src.evaluator.retention_evaluator import evaluate_retention_episode

    model = os.getenv("SMOKE_MODEL", "gpt-4.1-mini")
    tasks = load_base_tasks()
    overlays = [
        o
        for o in load_overlays("src/speech_task_overlays.jsonl")
        if o["benchmark_track"] == "text_to_voice_retention"
    ]
    target = overlays[0]
    print(f"Overlay: {target['speech_overlay_id']}  domain={target['domain']}  model={model}")
    print(f"Utterance: {target.get('spoken_utterance')}")
    print(f"Expected tool calls: {target.get('expected_tool_calls', tasks[target['base_task_id']].get('expected_tool_calls'))}")

    episodes = run_agent_episodes(
        agent="openai_text",
        model=model,
        overlays=[target],
        tasks=tasks,
        modes=["text_baseline"],
        personas=["vi_north_normal"],
    )
    episode = episodes[0]
    print("\n--- LIVE AGENT OUTPUT ---")
    print("assistant:", episode["assistant_transcript"])
    print("tool_calls:", episode["tool_calls"])
    print("tool_results:", episode["tool_results"])
    print("captured_slots:", episode["captured_slots"])
    print("failure_types:", episode["failure_types"])

    evaluated = evaluate_retention_episode(episode, target, tasks[target["base_task_id"]])
    print("\n--- EVALUATOR ---")
    print("scores:", evaluated.get("scores"))
    print("primary_failure_type:", evaluated.get("primary_failure_type"))
    print("failure_types:", evaluated.get("failure_types"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
