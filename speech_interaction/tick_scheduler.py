from __future__ import annotations


def schedule_timeline(timeline: list[dict], tick_ms: int = 200) -> list[dict]:
    if tick_ms <= 0:
        raise ValueError("tick_ms must be positive")
    return [
        {**event, "tick": event["t_ms"] // tick_ms}
        for event in sorted(timeline, key=lambda item: item["t_ms"])
    ]
