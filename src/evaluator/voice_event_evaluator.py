from __future__ import annotations


def event_time(events: list[dict], event_name: str) -> int | None:
    matches = [e.get("t_ms") for e in events if e.get("event") == event_name]
    return next((value for value in matches if isinstance(value, int)), None)


def observed_event_time(events: list[dict], event_name: str) -> int | None:
    matches = [
        e.get("t_ms")
        for e in events
        if e.get("event") == event_name and e.get("source") == "observed"
    ]
    return next((value for value in matches if isinstance(value, int)), None)


def evaluate_yield(events: list[dict], max_yield_latency_ms: int) -> dict:
    interrupt = observed_event_time(events, "user_interrupt_start") or event_time(
        events, "user_interrupt_start"
    )
    yielded = observed_event_time(events, "assistant_yielded") or event_time(
        events, "assistant_yielded"
    )
    if yielded is None:
        yielded = observed_event_time(events, "assistant_speech_stop") or event_time(
            events, "assistant_speech_stop"
        )
    latency = yielded - interrupt if interrupt is not None and yielded is not None else None
    return {
        "yield_latency_ms": latency,
        "passed": latency is not None and 0 <= latency <= max_yield_latency_ms,
    }
