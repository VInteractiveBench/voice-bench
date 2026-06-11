from __future__ import annotations

import os
from pathlib import Path


def load_benchmark_env(env_path: str | Path = ".env", *, override: bool = True) -> None:
    """Load local benchmark credentials without requiring a shell-specific env step."""
    path = Path(env_path)
    if not path.exists():
        return

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_env_value(value.strip())
        if key and (override or key not in os.environ):
            os.environ[key] = value

    _apply_provider_aliases(override=override)


def _strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _apply_provider_aliases(*, override: bool) -> None:
    if override or not os.getenv("GOOGLE_API_KEY"):
        for alias in ("GEMINI_API_KEY", "GEMINI_API_LIVE"):
            value = os.getenv(alias)
            if value:
                os.environ["GOOGLE_API_KEY"] = value
                break
