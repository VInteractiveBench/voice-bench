"""One-episode smoke test of the OpenAI Realtime (imitation Vivi) path.

Runs a single clean-voice retention overlay and a single FDRC overlay through the
live Realtime adapter, bypassing the 30+30 MVP preflight, to prove the voice and
full-duplex runner paths execute end to end against a real model.
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
    from src.evaluator.fdrc_evaluator import evaluate_fdrc_episode

    model = os.getenv("SMOKE_REALTIME_MODEL", "gpt-realtime")
    tasks = load_base_tasks()
    overlays = load_overlays("src/speech_task_overlays.jsonl")
    retention = next(o for o in overlays if o["benchmark_track"] == "text_to_voice_retention")
    fdrc = next(o for o in overlays if o["benchmark_track"] == "full_duplex_repair_to_commit")

    print(f"== VOICE RETENTION (clean) : {retention['speech_overlay_id']} | model={model} ==")
    ep = run_agent_episodes(
        agent="openai_realtime", model=model, overlays=[retention], tasks=tasks,
        modes=["clean_voice"], personas=["vi_north_normal"],
    )[0]
    print("tool_calls:", ep["tool_calls"])
    print("assistant:", ep["assistant_transcript"][:2])
    print("failure_types:", ep["failure_types"])
    ev = evaluate_retention_episode(ep, retention, tasks[retention["base_task_id"]])
    print("scores:", ev.get("scores"))

    print(f"\n== FDRC : {fdrc['speech_overlay_id']} | model={model} ==")
    ep2 = run_agent_episodes(
        agent="openai_realtime", model=model, overlays=[fdrc], tasks=tasks,
        modes=["full_duplex_repair_to_commit"], personas=["vi_north_normal"], tick_ms=200,
    )[0]
    print("tool_calls:", ep2["tool_calls"])
    print("failure_types:", ep2["failure_types"])
    ev2 = evaluate_fdrc_episode(ep2, fdrc, tasks[fdrc["base_task_id"]])
    print("scores:", ev2.get("scores"))
    print("repair:", ev2.get("repair"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
