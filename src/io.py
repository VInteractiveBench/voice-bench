from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent


def resolve_asset_path(path: str | Path) -> Path:
    target = Path(path)
    if target.exists():
        return target
    parts = target.parts
    if parts and parts[0] == "src":
        candidate = ROOT.joinpath(*parts[1:])
        if candidate.exists():
            return candidate
    return target


def read_json(path: str | Path) -> Any:
    # utf-8-sig tolerates a UTF-8 BOM that some editors prepend on save.
    return json.loads(resolve_asset_path(path).read_text(encoding="utf-8-sig"))


def read_jsonl(path: str | Path) -> list[dict]:
    rows = []
    for line in resolve_asset_path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def load_base_tasks(path: str | Path = ROOT / "base_task_manifest.json") -> dict[str, dict]:
    return {task["id"]: task for task in read_json(path)}


def load_overlays(path: str | Path = ROOT / "speech_task_overlays.jsonl") -> list[dict]:
    return read_jsonl(path)


def deep_subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and deep_subset(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and expected == actual
    return expected == actual
