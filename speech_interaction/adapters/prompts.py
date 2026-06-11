from __future__ import annotations

import json
from pathlib import Path

CORE_PROMPT = """You are Vivi, a Vietnamese in-car voice assistant for VinFast vehicles.

You must:
1. Understand the user's Vietnamese request.
2. Select only tools from the provided tool list.
3. Fill tool arguments according to the provided JSON schema.
4. Never invent a tool.
5. Never claim an action succeeded unless the tool result confirms it.
6. Follow the domain policy.
7. Ask clarification when information is ambiguous.
8. Refuse or no-op when the task is unsafe or impossible.
9. In voice mode, handle user correction such as "à không", "không phải", "thôi", "hủy".
10. If the user corrects or cancels before action commit, suppress the old intent and follow the latest explicit user intent.
11. Respond concisely in Vietnamese.
"""


def load_domain_policy(domain: str) -> str:
    path = Path("data") / "tau2" / "domains" / domain / "policy.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_system_prompt(
    *,
    task: dict,
    overlay: dict,
    mode: str,
    tool_names: list[str],
) -> str:
    context = {
        "domain": task["domain"],
        "base_task_id": task["id"],
        "speech_overlay_id": overlay["speech_overlay_id"],
        "conversation_mode": mode,
        "initial_state_summary": task.get("initial_state", {}),
        "available_tools": tool_names,
        "task_specific_constraints": {
            "do_not_use_expected_answer": True,
            "no_information_search_domain": True,
            "commit_only_after_repair_window": overlay.get("benchmark_track")
            == "full_duplex_repair_to_commit",
        },
    }
    return (
        CORE_PROMPT
        + "\n\nDomain policy:\n"
        + load_domain_policy(task["domain"])
        + "\n\nEpisode context:\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )
