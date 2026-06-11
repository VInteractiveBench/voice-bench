from __future__ import annotations


class VoiceEventLogger:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def log(self, t_ms: int, event: str, **details) -> dict:
        row = {"t_ms": t_ms, "event": event, **details}
        self.events.append(row)
        return row
