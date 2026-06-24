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

FDRC_PROMPT = """Full-duplex repair-to-commit rules:
1. Treat the latest user utterance as authoritative.
2. If the user says a correction such as "à không", "không phải", "đổi thành", or "ý tôi là", ignore the old intent and execute only the corrected final intent.
3. If the user says "thôi", "hủy", "bỏ đi", or any cancellation, do not call any side-effect tool.
4. Do not commit a tool call while the user is still correcting or before the repair utterance has been processed.
5. If you are already speaking and the user interrupts, stop responding to the old intent and handle the interruption.
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
    prompt = CORE_PROMPT
    if overlay.get("benchmark_track") == "full_duplex_repair_to_commit":
        prompt += "\n\n" + FDRC_PROMPT
    return (
        prompt
        + "\n\nDomain policy:\n"
        + load_domain_policy(task["domain"])
        + "\n\nEpisode context:\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )
