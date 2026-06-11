from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return re.sub(r"\s+", " ", text).strip()


def evaluate_critical_slots(expected: dict, captured: dict) -> dict:
    per_slot = {
        key: key in captured and normalize(value) == normalize(captured[key])
        for key, value in expected.items()
    }
    return {
        "passed": all(per_slot.values()),
        "correct": sum(per_slot.values()),
        "total": len(per_slot),
        "per_slot": per_slot,
    }
