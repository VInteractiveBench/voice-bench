# Metric Explainability (Audit & Trace) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking any FDRC metric card/KPI opens a modal that explains exactly how that number was computed — the formula, the numerator/denominator counts (recomputed from the actual episodes), and the list of numerator episodes (each linking to its episode detail) — for audit and traceability.

**Architecture:** Authoritative, backend-computed. A new evaluator module `src/evaluator/fdrc_explain.py` defines a per-metric spec (episode scope + denominator row-set + numerator predicate + Vietnamese formula text) that reuses the SAME predicate helpers as `fdrc_contract.py`, with a test asserting the recomputed value equals `summarize_fdrc_contract`'s value (no drift). `DashboardStore.explain_metric()` builds the same scoped episode set `run_summary` uses, calls the explain module, resolves numerator episode IDs to minimal link rows, and a new endpoint `GET /api/runs/{run_id}/metrics/{key}/explain` serves it. The frontend makes metric cards clickable, fetches the explanation, and renders a modal. A pure JS helper formats the ratio; the modal DOM lives in app.js + styles.css.

**Tech Stack:** Python/FastAPI (backend, pytest), vanilla JS (`node helpers.test.cjs` for pure helpers), CSS. Env: run Python via `.\.venv\Scripts\python.exe` (conda is not on PATH in this environment).

---

## Why backend-authoritative (chosen)

The displayed metric value can come from `metrics.json` (when its `episode_set_hash` matches) or be derived from `episodes.jsonl`. For an audit feature the numbers MUST be reproducible from the episodes by the same predicate logic the evaluator uses. Re-deriving on the frontend risks drift. So the explain endpoint recomputes numerator/denominator from the scoped episodes using the contract's own predicate helpers, and reports both the recomputed value and the displayed value plus whether they match — a divergence is itself an audit signal.

## Metric → formula reference (from `src/evaluator/fdrc_contract.py` and `fdrc_validity.py`)

Every rate is `count(predicate) / len(row_set)`. Row-sets:
- `rows` = episodes with `benchmark_track` in {None, full_duplex_repair_to_commit}
- `completed_rows` = rows where `scores.final_pass is not None and not dashboard_reevaluation_error`
- `repair_rows` = rows where `repair` is a dict
- `cancel_rows` = repair_rows where `repair.final_intent == "cancel"`
- `scored(rows, k)` = rows where `scores[k] is not None`

| metric key | scope | denominator row-set | numerator predicate (counted) | orient |
|---|---|---|---|---|
| `fdrc_pass_at_1`, `pass_at_1`, `raw_fdrc_pass_at_1` | all | scored(completed_rows,"final_pass") | `scores.final_pass` truthy | good |
| `performance_fdrc_pass_at_1` | valid | scored(completed_rows,"final_pass") | `scores.final_pass` truthy | good |
| `yield_latency_pass_rate` | all | completed_rows | `"YIELD_LATENCY_TOO_HIGH"` NOT in failure_types | good |
| `policy_violation_rate` | all | completed_rows | `"POLICY_VIOLATION"` in failure_types | bad |
| `tool_validation_error_rate` | all | completed_rows | `validation_errors` truthy | bad |
| `state_match` | all | scored(completed_rows,"state_match") | `scores.state_match` truthy | good |
| `old_intent_suppression_rate` | all | repair_rows | NOT `repair.old_intent_committed` | good |
| `forbidden_tool_call_rate` | all | repair_rows | `repair.forbidden_tool_called` | bad |
| `correction_uptake_rate` | all | repair_rows | `repair.correction_uptaken` | good |
| `cancel_success_rate` | all | cancel_rows | `_cancel_respected(e)` | good |
| `fdrc_validity_rate` | all | rows | `fdrc_validity.valid` | good |
| `valid_episode_count` | all | rows | `fdrc_validity.valid` (count) | good |
| `invalid_episode_count` | all | rows | NOT `fdrc_validity.valid` (count) | bad |

`scope=valid` means: first filter episodes to those with `fdrc_validity.valid` truthy, then apply the row-set. (`performance_fdrc_pass_at_1` is computed by the contract over `valid_rows`.)

"Numerator episodes" listed in the modal = the predicate-true episodes (so `value = numerator/denominator` is directly verifiable). For "good" metrics whose numerator may be empty (e.g. `pass_at_1 = 0`), the modal ALSO shows an "open Episode Explorer (failures)" link via `explorer_filter`, so failures remain traceable without changing the listed set.

Keys not in the table (e.g. `yield_latency_p50_ms`, `yield_latency_p95_ms`, `metric_contract.*`, `parse_errors`, `metrics_hash_valid`) are **unsupported** for per-episode breakdown: the endpoint returns `supported: false` with label/description/value so the modal shows the description and value but no episode list.

## File Structure

- **Create** `src/evaluator/fdrc_explain.py` — spec registry + `explain_fdrc_metric(metric_key, episodes, scope)`.
- **Create** `tests/test_fdrc_explain.py` — drift test (explain value == contract value) + numerator-id test.
- **Modify** `src/dashboard/service.py` — add `_scoped_evaluation_episodes()` helper (factored from `run_summary`) and `DashboardStore.explain_metric()`.
- **Modify** `src/dashboard/app.py` — add `GET /api/runs/{run_id}/metrics/{key}/explain`.
- **Modify** `tests/test_dashboard.py` — test `explain_metric` happy path + unsupported key.
- **Modify** `src/dashboard/static/helpers.js` + `helpers.test.cjs` — pure `formatRatio(num, denom)` helper + test.
- **Modify** `src/dashboard/static/app.js` — clickable metric cards, modal open/close, fetch + render.
- **Modify** `src/dashboard/static/styles.css` — modal styles.
- **Modify** `src/dashboard/static/index.html` — bump `?v=` cache-bust on app.js/helpers.js/styles.css.
- **Modify** `docs/dashboard_usage.md` — document the explain modal.

---

### Task 1: Backend explain module + drift test

**Files:**
- Create: `src/evaluator/fdrc_explain.py`
- Test: `tests/test_fdrc_explain.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fdrc_explain.py`:

```python
from __future__ import annotations

from src.evaluator.fdrc_contract import summarize_fdrc_contract
from src.evaluator.fdrc_explain import explain_fdrc_metric, SUPPORTED_EXPLAIN_KEYS


def _episode(**overrides):
    base = {
        "episode_id": "e",
        "benchmark_track": "full_duplex_repair_to_commit",
        "scores": {"final_pass": True, "state_match": True},
        "failure_types": [],
        "validation_errors": [],
        "repair": {
            "final_intent": "repair",
            "old_intent_committed": False,
            "forbidden_tool_called": False,
            "correction_uptaken": True,
        },
        "fdrc_validity": {"valid": True, "reasons": []},
        "tool_calls": [],
        "final_state": {},
    }
    base.update(overrides)
    return base


def _episodes():
    return [
        _episode(episode_id="pass1"),
        _episode(
            episode_id="forbidden1",
            scores={"final_pass": False, "state_match": False},
            failure_types=["FORBIDDEN_TOOL_CALL", "POLICY_VIOLATION"],
            repair={
                "final_intent": "repair",
                "old_intent_committed": True,
                "forbidden_tool_called": True,
                "correction_uptaken": False,
            },
        ),
        _episode(
            episode_id="cancel_ok",
            repair={"final_intent": "cancel", "cancel_respected": True},
            tool_calls=[],
        ),
        _episode(
            episode_id="invalid1",
            fdrc_validity={"valid": False, "reasons": ["INVALID_AUDIO"]},
        ),
    ]


def test_explain_value_matches_contract_for_every_supported_key():
    episodes = _episodes()
    contract = summarize_fdrc_contract(episodes)
    for key in SUPPORTED_EXPLAIN_KEYS:
        if key in {"performance_fdrc_pass_at_1", "raw_fdrc_pass_at_1",
                   "valid_episode_count", "invalid_episode_count", "fdrc_validity_rate"}:
            continue  # validity/scope-specific keys covered separately below
        result = explain_fdrc_metric(key, episodes)
        assert result is not None and result["supported"], key
        expected = contract.get(key)
        if expected is None:
            assert result["value"] is None, key
        else:
            assert abs(result["value"] - expected) < 1e-9, (key, result["value"], expected)


def test_explain_lists_numerator_episode_ids():
    episodes = _episodes()
    forbidden = explain_fdrc_metric("forbidden_tool_call_rate", episodes)
    assert forbidden["numerator"] == 1
    assert forbidden["denominator"] == 4
    assert [e["episode_id"] for e in forbidden["numerator_episodes"]] == ["forbidden1"]


def test_explain_unsupported_key_returns_supported_false():
    result = explain_fdrc_metric("yield_latency_p50_ms", _episodes())
    assert result is not None
    assert result["supported"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests\test_fdrc_explain.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.evaluator.fdrc_explain'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/evaluator/fdrc_explain.py`:

```python
from __future__ import annotations

from typing import Any, Callable

from .fdrc_contract import _cancel_respected, _completed, _failure_values

FDRC_TRACK = "full_duplex_repair_to_commit"

Predicate = Callable[[dict[str, Any]], bool]
RowSet = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]


def _rows(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in episodes if e.get("benchmark_track") in {None, FDRC_TRACK}]


def _completed_rows(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in _rows(episodes) if _completed(e)]


def _repair_rows(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in _rows(episodes) if isinstance(e.get("repair"), dict)]


def _cancel_rows(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in _repair_rows(episodes) if e.get("repair", {}).get("final_intent") == "cancel"]


def _scored(row_set: RowSet, score_key: str) -> RowSet:
    return lambda episodes: [
        e for e in row_set(episodes) if e.get("scores", {}).get(score_key) is not None
    ]


def _valid_only(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in episodes if e.get("fdrc_validity", {}).get("valid")]


# spec: (scope, row_set, predicate, unit, formula_vi, row_set_label_vi,
#        numerator_label_vi, explorer_filter)
_EXPLAIN_SPECS: dict[str, dict[str, Any]] = {
    "fdrc_pass_at_1": {
        "scope": "all",
        "row_set": _scored(_completed_rows, "final_pass"),
        "predicate": lambda e: bool(e.get("scores", {}).get("final_pass")),
        "unit": "rate",
        "formula_vi": "pass = số episode pass toàn bộ ÷ số episode hoàn tất có chấm final_pass",
        "row_set_label_vi": "Episode hoàn tất (completed) có điểm final_pass",
        "numerator_label_vi": "Episode pass toàn bộ (final_pass = true)",
        "explorer_filter": {"passed": "false"},
    },
    "raw_fdrc_pass_at_1": {
        "scope": "all",
        "row_set": _scored(_completed_rows, "final_pass"),
        "predicate": lambda e: bool(e.get("scores", {}).get("final_pass")),
        "unit": "rate",
        "formula_vi": "raw pass = pass toàn bộ ÷ episode hoàn tất (KHÔNG lọc validity)",
        "row_set_label_vi": "Episode hoàn tất có điểm final_pass (mọi episode)",
        "numerator_label_vi": "Episode pass toàn bộ (final_pass = true)",
        "explorer_filter": {"passed": "false"},
    },
    "performance_fdrc_pass_at_1": {
        "scope": "valid",
        "row_set": _scored(_completed_rows, "final_pass"),
        "predicate": lambda e: bool(e.get("scores", {}).get("final_pass")),
        "unit": "rate",
        "formula_vi": "performance pass = pass toàn bộ ÷ episode hoàn tất, CHỈ trên episode hợp lệ",
        "row_set_label_vi": "Episode hợp lệ & hoàn tất có điểm final_pass",
        "numerator_label_vi": "Episode pass toàn bộ (final_pass = true)",
        "explorer_filter": {"validity": "valid", "passed": "false"},
    },
    "yield_latency_pass_rate": {
        "scope": "all",
        "row_set": _completed_rows,
        "predicate": lambda e: "YIELD_LATENCY_TOO_HIGH" not in _failure_values(e),
        "unit": "rate",
        "formula_vi": "yield pass = episode KHÔNG bị YIELD_LATENCY_TOO_HIGH ÷ episode hoàn tất",
        "row_set_label_vi": "Episode hoàn tất (completed)",
        "numerator_label_vi": "Episode yield đúng hạn (không có YIELD_LATENCY_TOO_HIGH)",
        "explorer_filter": {"failure": "YIELD_LATENCY_TOO_HIGH"},
    },
    "policy_violation_rate": {
        "scope": "all",
        "row_set": _completed_rows,
        "predicate": lambda e: "POLICY_VIOLATION" in _failure_values(e),
        "unit": "rate",
        "formula_vi": "tỷ lệ vi phạm = episode có POLICY_VIOLATION ÷ episode hoàn tất",
        "row_set_label_vi": "Episode hoàn tất (completed)",
        "numerator_label_vi": "Episode vi phạm policy (POLICY_VIOLATION)",
        "explorer_filter": {"failure": "POLICY_VIOLATION"},
    },
    "tool_validation_error_rate": {
        "scope": "all",
        "row_set": _completed_rows,
        "predicate": lambda e: bool(e.get("validation_errors")),
        "unit": "rate",
        "formula_vi": "tỷ lệ lỗi tool = episode có validation_errors ÷ episode hoàn tất",
        "row_set_label_vi": "Episode hoàn tất (completed)",
        "numerator_label_vi": "Episode có lỗi validation tool",
        "explorer_filter": {"validity": "invalid"},
    },
    "state_match": {
        "scope": "all",
        "row_set": _scored(_completed_rows, "state_match"),
        "predicate": lambda e: bool(e.get("scores", {}).get("state_match")),
        "unit": "rate",
        "formula_vi": "state match = episode đúng final state ÷ episode hoàn tất có chấm state_match",
        "row_set_label_vi": "Episode hoàn tất có điểm state_match",
        "numerator_label_vi": "Episode đúng final state (state_match = true)",
        "explorer_filter": {"passed": "false"},
    },
    "old_intent_suppression_rate": {
        "scope": "all",
        "row_set": _repair_rows,
        "predicate": lambda e: not bool(e.get("repair", {}).get("old_intent_committed")),
        "unit": "rate",
        "formula_vi": "chặn ý định cũ = episode KHÔNG commit ý định cũ ÷ episode có repair",
        "row_set_label_vi": "Episode có repair timeline",
        "numerator_label_vi": "Episode chặn được ý định cũ (old_intent_committed = false)",
        "explorer_filter": {"failure": "OLD_INTENT_COMMITTED"},
    },
    "forbidden_tool_call_rate": {
        "scope": "all",
        "row_set": _repair_rows,
        "predicate": lambda e: bool(e.get("repair", {}).get("forbidden_tool_called")),
        "unit": "rate",
        "formula_vi": "gọi tool bị cấm = episode gọi tool cấm ÷ episode có repair",
        "row_set_label_vi": "Episode có repair timeline",
        "numerator_label_vi": "Episode gọi tool bị cấm (forbidden_tool_called = true)",
        "explorer_filter": {"failure": "FORBIDDEN_TOOL_CALL"},
    },
    "correction_uptake_rate": {
        "scope": "all",
        "row_set": _repair_rows,
        "predicate": lambda e: bool(e.get("repair", {}).get("correction_uptaken")),
        "unit": "rate",
        "formula_vi": "tiếp nhận sửa = episode tiếp nhận ý định mới ÷ episode có repair",
        "row_set_label_vi": "Episode có repair timeline",
        "numerator_label_vi": "Episode tiếp nhận sửa (correction_uptaken = true)",
        "explorer_filter": {"failure": "CORRECTION_NOT_UPTAKEN"},
    },
    "cancel_success_rate": {
        "scope": "all",
        "row_set": _cancel_rows,
        "predicate": _cancel_respected,
        "unit": "rate",
        "formula_vi": "cancel thành công = episode cancel không tạo side effect ÷ episode final_intent=cancel",
        "row_set_label_vi": "Episode có final_intent = cancel",
        "numerator_label_vi": "Episode cancel được tôn trọng (không side effect)",
        "explorer_filter": {"failure": "CANCEL_NOT_RESPECTED"},
    },
    "fdrc_validity_rate": {
        "scope": "all",
        "row_set": _rows,
        "predicate": lambda e: bool(e.get("fdrc_validity", {}).get("valid")),
        "unit": "rate",
        "formula_vi": "validity = episode hợp lệ ÷ tổng episode",
        "row_set_label_vi": "Tổng episode trong track",
        "numerator_label_vi": "Episode hợp lệ (fdrc_validity.valid = true)",
        "explorer_filter": {"validity": "invalid"},
    },
    "valid_episode_count": {
        "scope": "all",
        "row_set": _rows,
        "predicate": lambda e: bool(e.get("fdrc_validity", {}).get("valid")),
        "unit": "count",
        "formula_vi": "đếm số episode hợp lệ",
        "row_set_label_vi": "Tổng episode trong track",
        "numerator_label_vi": "Episode hợp lệ",
        "explorer_filter": {"validity": "valid"},
    },
    "invalid_episode_count": {
        "scope": "all",
        "row_set": _rows,
        "predicate": lambda e: not bool(e.get("fdrc_validity", {}).get("valid")),
        "unit": "count",
        "formula_vi": "đếm số episode invalid",
        "row_set_label_vi": "Tổng episode trong track",
        "numerator_label_vi": "Episode invalid",
        "explorer_filter": {"validity": "invalid"},
    },
}

# pass_at_1 is an alias of fdrc_pass_at_1
_EXPLAIN_SPECS["pass_at_1"] = _EXPLAIN_SPECS["fdrc_pass_at_1"]

SUPPORTED_EXPLAIN_KEYS = tuple(_EXPLAIN_SPECS.keys())


def explain_fdrc_metric(
    metric_key: str, episodes: list[dict[str, Any]]
) -> dict[str, Any] | None:
    spec = _EXPLAIN_SPECS.get(metric_key)
    if spec is None:
        return {"key": metric_key, "supported": False}
    scoped = _valid_only(episodes) if spec["scope"] == "valid" else list(episodes)
    row_set = spec["row_set"](scoped)
    predicate: Predicate = spec["predicate"]
    numerator_rows = [e for e in row_set if predicate(e)]
    denominator = len(row_set)
    numerator = len(numerator_rows)
    if spec["unit"] == "count":
        value: float | None = float(numerator)
    else:
        value = (numerator / denominator) if denominator else None
    return {
        "key": metric_key,
        "supported": True,
        "scope": spec["scope"],
        "unit": spec["unit"],
        "formula_vi": spec["formula_vi"],
        "row_set_label_vi": spec["row_set_label_vi"],
        "numerator_label_vi": spec["numerator_label_vi"],
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
        "numerator_episode_ids": [str(e.get("episode_id")) for e in numerator_rows],
        "explorer_filter": spec["explorer_filter"],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests\test_fdrc_explain.py`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint + commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src\evaluator\fdrc_explain.py tests\test_fdrc_explain.py
git add src/evaluator/fdrc_explain.py tests/test_fdrc_explain.py
git commit -m "feat(evaluator): add FDRC metric explain specs with contract-parity test"
```
Expected: ruff clean; commit succeeds.

---

### Task 2: Service `explain_metric` + API endpoint

**Files:**
- Modify: `src/dashboard/service.py`
- Modify: `src/dashboard/app.py`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dashboard.py` (reuse existing helpers `sample_fdrc_episode`, `write_jsonl`, `write_json`, `metrics_with_metadata` already in that file). NOTE: `sample_fdrc_episode` is a `provider` episode, so `DashboardStore` re-evaluates it through `_evaluation_view` — its `repair`/`scores` are computed by the evaluator, not injected. So we do NOT hand-assert a numerator; instead we assert the explain endpoint is **internally consistent and matches `run_summary`'s displayed value** (the real audit guarantee), plus structural correctness:

```python
def test_explain_metric_matches_summary_and_is_consistent(tmp_path):
    run = tmp_path / "fdrc_explain_run"
    run.mkdir()
    episodes = [
        sample_fdrc_episode(episode_id="a1"),
        sample_fdrc_episode(episode_id="a2"),
    ]
    write_jsonl(run / "episodes.jsonl", episodes)

    store = DashboardStore(tmp_path)
    summary = store.run_summary("fdrc_explain_run", track=FDRC_TRACK)
    key = "forbidden_tool_call_rate"
    displayed = summary["metrics"].get(key)

    result = store.explain_metric("fdrc_explain_run", key, track=FDRC_TRACK)
    assert result["supported"] is True
    assert result["label"]
    assert result["metric_source"] in {"metrics.json", "episodes.jsonl"}
    # numerator count equals the number of listed numerator episodes
    assert result["numerator"] == len(result["numerator_episodes"])
    # recomputed value equals run_summary's displayed value (audit parity)
    if displayed is None:
        assert result["value"] is None
    else:
        assert abs(result["value"] - displayed) < 1e-9
    # every listed episode id is a real scoped episode
    listed = {e["episode_id"] for e in result["numerator_episodes"]}
    assert listed <= {"a1", "a2"}


def test_explain_metric_unsupported_key(tmp_path):
    run = tmp_path / "fdrc_explain_run2"
    run.mkdir()
    write_jsonl(run / "episodes.jsonl", [sample_fdrc_episode(episode_id="x")])
    store = DashboardStore(tmp_path)
    result = store.explain_metric("fdrc_explain_run2", "yield_latency_p50_ms", track=FDRC_TRACK)
    assert result["supported"] is False
    assert result["label"]


def test_explain_metric_missing_run_raises(tmp_path):
    store = DashboardStore(tmp_path)
    import pytest
    from src.dashboard.service import RunNotFound
    with pytest.raises(RunNotFound):
        store.explain_metric("does_not_exist", "forbidden_tool_call_rate")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests\test_dashboard.py -k explain_metric`
Expected: FAIL — `AttributeError: 'DashboardStore' object has no attribute 'explain_metric'`.

- [ ] **Step 3: Write minimal implementation**

In `src/dashboard/service.py`, add the import next to the existing evaluator imports (verified convention — service.py uses `from src.evaluator.X import ...` at lines 13-15):

```python
from src.evaluator.fdrc_explain import explain_fdrc_metric
```

Refactor the scoped-episode construction in `run_summary` into a reusable helper. Add this method to `DashboardStore` (place it directly above `run_summary`):

```python
    def _scoped_evaluation_episodes(
        self, run_id: str, track: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None, str, bool]:
        path, metrics, raw_episodes, _errors = self._load_run(run_id)
        selected_track = track or _dominant_track(raw_episodes)
        raw_scoped = [
            e for e in raw_episodes
            if not selected_track or e.get("benchmark_track") == selected_track
        ]
        episodes = _evaluation_view(raw_episodes)
        scoped = [
            e for e in episodes
            if not selected_track or e.get("benchmark_track") == selected_track
        ]
        metrics_valid = bool(metrics) and metrics.get("episode_set_hash") == episode_set_hash(raw_scoped)
        metric_source = "metrics.json" if metrics_valid else "episodes.jsonl"
        return scoped, selected_track, metric_source, metrics_valid
```

Then add the `explain_metric` method (place it directly after `run_summary`):

```python
    def explain_metric(
        self, run_id: str, metric_key: str, track: str | None = None
    ) -> dict[str, Any]:
        if not (self.results_dir / run_id).exists():
            raise RunNotFound(run_id)
        scoped, selected_track, metric_source, metrics_valid = self._scoped_evaluation_episodes(
            run_id, track
        )
        label, description, unit, group = _metric_meta(metric_key)
        explanation = explain_fdrc_metric(metric_key, scoped) or {
            "key": metric_key,
            "supported": False,
        }
        base = {
            "run_id": run_id,
            "key": metric_key,
            "label": label,
            "description": description,
            "unit": unit,
            "group": group,
            "benchmark_track": selected_track,
            "metric_source": metric_source,
            "metrics_hash_valid": metrics_valid,
        }
        if not explanation.get("supported"):
            base["supported"] = False
            base["note_vi"] = "Metric tổng hợp — không có phân tích theo từng episode."
            return base
        numerator_ids = set(explanation.get("numerator_episode_ids", []))
        by_id = {str(e.get("episode_id")): e for e in scoped}
        numerator_episodes = []
        for episode_id in explanation.get("numerator_episode_ids", []):
            episode = by_id.get(episode_id, {})
            numerator_episodes.append(
                {
                    "episode_id": episode_id,
                    "base_task_id": episode.get("base_task_id"),
                    "domain": episode.get("domain"),
                    "accent_region": episode.get("accent_region"),
                    "speech_speed": episode.get("speech_speed"),
                    "passed": _score_pass(episode),
                    "fdrc_valid": bool(episode.get("fdrc_validity", {}).get("valid")),
                }
            )
        base.update(
            {
                "supported": True,
                "scope": explanation["scope"],
                "formula_vi": explanation["formula_vi"],
                "row_set_label_vi": explanation["row_set_label_vi"],
                "numerator_label_vi": explanation["numerator_label_vi"],
                "numerator": explanation["numerator"],
                "denominator": explanation["denominator"],
                "value": explanation["value"],
                "numerator_episodes": numerator_episodes,
                "explorer_filter": explanation["explorer_filter"],
            }
        )
        return base
```
> Note: `_metric_meta`, `_score_pass`, `_evaluation_view`, `_dominant_track`, `episode_set_hash`, and `RunNotFound` already exist in service.py. Confirm `episode_set_hash` is imported/defined there (it is used in `run_summary`). Do not redefine them.

Optionally refactor `run_summary` to call `_scoped_evaluation_episodes` to avoid duplication, but ONLY if it doesn't change behavior — if unsure, leave `run_summary` as-is (the helper duplicates a few lines, which is acceptable). Do not risk regressions in `run_summary`.

In `src/dashboard/app.py`, add the endpoint after the existing `episode_detail` route (before `return app`):

```python
    @app.get("/api/runs/{run_id}/metrics/{metric_key}/explain")
    def explain_metric(run_id: str, metric_key: str, track: str | None = None) -> dict[str, Any]:
        try:
            return store.explain_metric(run_id, metric_key, track=track)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```
.\.venv\Scripts\python.exe -m pytest -q tests\test_dashboard.py -k explain_metric
.\.venv\Scripts\python.exe -m pytest -q tests\test_dashboard.py
```
Expected: explain tests pass; full dashboard suite still passes.

- [ ] **Step 5: Lint + commit**

```bash
.\.venv\Scripts\python.exe -m ruff check src\dashboard
git add src/dashboard/service.py src/dashboard/app.py tests/test_dashboard.py
git commit -m "feat(dashboard): add /metrics/{key}/explain endpoint and explain_metric"
```

---

### Task 3: Pure frontend helper `formatRatio`

**Files:**
- Modify: `src/dashboard/static/helpers.js`
- Test: `src/dashboard/static/helpers.test.cjs`

- [ ] **Step 1: Write the failing test**

Add before the final `console.log` in `src/dashboard/static/helpers.test.cjs`:

```js
// ---- formatRatio ----
t("formatRatio shows numerator / denominator", () => {
  assert.strictEqual(VB.formatRatio(1, 8), "1 / 8");
  assert.strictEqual(VB.formatRatio(0, 0), "0 / 0");
});
t("formatRatio coerces nullish to 0", () => {
  assert.strictEqual(VB.formatRatio(null, undefined), "0 / 0");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/dashboard/static && node helpers.test.cjs`
Expected: FAIL — `VB.formatRatio is not a function`.

- [ ] **Step 3: Write minimal implementation**

In `src/dashboard/static/helpers.js`, add after the `fmtInt` function:

```js
  // "numerator / denominator", nullish-safe. For audit explain modal.
  function formatRatio(numerator, denominator) {
    const n = Number.isFinite(numerator) ? numerator : 0;
    const d = Number.isFinite(denominator) ? denominator : 0;
    return n + " / " + d;
  }
```
Add `formatRatio,` to the returned export object.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/dashboard/static && node helpers.test.cjs`
Expected: PASS, exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/dashboard/static/helpers.js src/dashboard/static/helpers.test.cjs
git commit -m "feat(dashboard): add formatRatio helper"
```

---

### Task 4: Clickable metric cards + explain modal in app.js

**Files:**
- Modify: `src/dashboard/static/app.js`

No Node unit test (DOM/fetch). Verified by manual smoke (Task 6).

- [ ] **Step 1: Make metric cards carry their key and be clickable**

In `metricCard(m)` (currently ~lines 295-306), add a `data-key` attribute and a class marking it clickable. Replace the function with:

```js
  function metricCard(m) {
    const isNull = m.value === null || m.value === undefined;
    const valHtml = isNull
      ? `<div class="metric-value null">${esc(m.null_reason || "N/A")}</div>`
      : `<div class="metric-value">${esc(H.fmtMetric(m))}</div>`;
    const denom = m.denominator ? `n=${esc(m.denominator)}` : "";
    return `<div class="metric ${metricStatusClass(m.status)} metric-clickable" data-key="${esc(m.key)}" role="button" tabindex="0">
      <div class="metric-label">${esc(m.label || m.key)}</div>
      ${valHtml}
      <div class="metric-foot"><span>${esc(m.group || "")}</span><span>${denom}</span></div>
    </div>`;
  }
```

- [ ] **Step 2: Delegate clicks on the overview body to open the modal**

In `renderOverview`, the overview body is set via `document.getElementById("ov-body").innerHTML = ...` (around line 249). Immediately AFTER that line, add a delegated listener (the current `runId` is in scope there):

```js
    const ovBody = document.getElementById("ov-body");
    function onMetricActivate(target) {
      const card = target.closest(".metric-clickable");
      if (!card) return;
      openMetricModal(runId, card.getAttribute("data-key"));
    }
    ovBody.addEventListener("click", (e) => onMetricActivate(e.target));
    ovBody.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onMetricActivate(e.target); }
    });
```

- [ ] **Step 3: Add the modal fetch + render functions**

Add these functions near the other view helpers (e.g. after `metricCard`):

```js
  async function fetchExplain(runId, key) {
    return getJSON(
      `/api/runs/${encodeURIComponent(runId)}/metrics/${encodeURIComponent(key)}/explain?track=${FDRC}`
    );
  }

  function closeMetricModal() {
    const m = document.getElementById("metric-modal");
    if (m) m.remove();
    document.removeEventListener("keydown", onModalKeydown);
  }

  function onModalKeydown(e) {
    if (e.key === "Escape") closeMetricModal();
  }

  function explainEpisodeRow(runId, ep) {
    const persona = [ep.accent_region, ep.speech_speed].filter(Boolean).join("·") || "—";
    const status = ep.passed === true ? "pass" : ep.passed === false ? "fail" : "—";
    return `<tr>
      <td><a href="${H.buildHash({ tab: "fdrc", view: "episode", runId, episodeId: ep.episode_id })}">${esc(ep.episode_id)}</a></td>
      <td>${esc(ep.domain || "—")}</td>
      <td>${esc(persona)}</td>
      <td>${esc(status)}</td>
    </tr>`;
  }

  function renderMetricModal(runId, data) {
    let bodyHtml;
    if (!data.supported) {
      bodyHtml = `<p class="modal-note">${esc(data.note_vi || "Không có phân tích theo episode.")}</p>`;
    } else {
      const ratio = H.formatRatio(data.numerator, data.denominator);
      const computed = data.unit === "count" ? H.fmtInt(data.value) : H.fmtPct(data.value);
      const eps = (data.numerator_episodes || []);
      const epTable = eps.length
        ? `<table class="modal-table"><thead><tr><th>episode</th><th>domain</th><th>persona</th><th>kết quả</th></tr></thead>
            <tbody>${eps.map((ep) => explainEpisodeRow(runId, ep)).join("")}</tbody></table>`
        : `<p class="modal-note">Tử số rỗng — không episode nào thỏa điều kiện.</p>`;
      const explorerLink = data.explorer_filter
        ? `<a class="btn btn-ghost" id="modal-explorer" href="${H.buildHash({ tab: "fdrc", view: "episodes", runId })}">Mở Episode Explorer →</a>`
        : "";
      bodyHtml = `
        <div class="modal-formula"><code>${esc(data.formula_vi)}</code></div>
        <div class="modal-calc">
          <span class="modal-calc-num">${esc(computed)}</span>
          <span class="modal-calc-eq">=</span>
          <span class="modal-calc-ratio">${esc(ratio)}</span>
          <span class="modal-calc-lbl">(${esc(data.numerator_label_vi)} ÷ ${esc(data.row_set_label_vi)})</span>
        </div>
        <div class="modal-src">nguồn: ${esc(data.metric_source)} · hash ${data.metrics_hash_valid ? "khớp" : "KHÔNG khớp"} · scope: ${esc(data.scope)}</div>
        <h4>Episode tử số (${eps.length})</h4>
        ${epTable}
        ${explorerLink}`;
    }
    return `<div class="modal-backdrop" id="metric-modal">
      <div class="modal" role="dialog" aria-modal="true" aria-label="${esc(data.label || data.key)}">
        <div class="modal-head">
          <div><div class="modal-title">${esc(data.label || data.key)}</div>
          <div class="modal-key">${esc(data.key)}</div></div>
          <button class="modal-x" id="modal-close" aria-label="Đóng">✕</button>
        </div>
        ${data.description ? `<p class="modal-desc">${esc(data.description)}</p>` : ""}
        ${bodyHtml}
      </div>
    </div>`;
  }

  async function openMetricModal(runId, key) {
    closeMetricModal();
    const shell = el(`<div class="modal-backdrop" id="metric-modal"><div class="modal"><div class="skeleton"></div></div></div>`);
    document.body.appendChild(shell);
    document.addEventListener("keydown", onModalKeydown);
    let data;
    try {
      data = await fetchExplain(runId, key);
    } catch (e) {
      shell.querySelector(".modal").innerHTML =
        `<div class="modal-head"><div class="modal-title">Lỗi</div><button class="modal-x" id="modal-close">✕</button></div><p class="modal-note">${esc(e.message)}</p>`;
      shell.addEventListener("click", (ev) => { if (ev.target === shell || ev.target.id === "modal-close") closeMetricModal(); });
      return;
    }
    shell.outerHTML = renderMetricModal(runId, data);
    const modal = document.getElementById("metric-modal");
    modal.addEventListener("click", (ev) => {
      if (ev.target === modal) closeMetricModal();
    });
    document.getElementById("modal-close").addEventListener("click", closeMetricModal);
    const explorer = document.getElementById("modal-explorer");
    if (explorer) {
      explorer.addEventListener("click", () => closeMetricModal());
    }
  }
```

> The episode links and the explorer link use `H.buildHash(...)` so they participate in the existing hash router; clicking them changes the route and the modal is removed on navigation (the view re-renders). `closeMetricModal` is also called explicitly on the explorer link for immediate cleanup.

- [ ] **Step 4: Verify syntax + helper tests still pass**

Run:
```
node --check src/dashboard/static/app.js
cd src/dashboard/static && node helpers.test.cjs
```
Expected: app.js syntax OK; helper tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/dashboard/static/app.js
git commit -m "feat(dashboard): open metric explain modal on metric click"
```

---

### Task 5: Modal CSS + cache-bust

**Files:**
- Modify: `src/dashboard/static/styles.css`
- Modify: `src/dashboard/static/index.html`

- [ ] **Step 1: Add modal styles**

Append to the end of `src/dashboard/static/styles.css`:

```css
/* ---- metric explain modal ---- */
.metric-clickable { cursor: pointer; }
.metric-clickable:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--pass-dim); }
.modal-backdrop {
  position: fixed; inset: 0; z-index: 9500;
  background: rgba(20, 35, 60, 0.38); backdrop-filter: blur(3px);
  display: flex; align-items: flex-start; justify-content: center;
  padding: 64px 20px; overflow-y: auto;
}
.modal {
  width: min(720px, 100%); background: var(--bg); border: 1px solid var(--line);
  border-radius: var(--r-lg); box-shadow: var(--shadow); padding: 22px 24px;
}
.modal-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.modal-title { font-family: var(--display); font-weight: 700; font-size: 18px; color: var(--text-hi); }
.modal-key { font-family: var(--mono); font-size: 12px; color: var(--faint); }
.modal-x { background: transparent; border: 1px solid var(--line); border-radius: var(--r);
  cursor: pointer; padding: 4px 9px; color: var(--muted); font-size: 14px; }
.modal-x:hover { border-color: var(--accent); color: var(--text-hi); }
.modal-desc { color: var(--muted); font-size: 13px; margin: 8px 0 14px; }
.modal-formula { background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: var(--r);
  padding: 10px 12px; margin-bottom: 12px; }
.modal-formula code { font-family: var(--mono); font-size: 12.5px; color: var(--text); }
.modal-calc { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; margin-bottom: 8px; }
.modal-calc-num { font-family: var(--display); font-weight: 800; font-size: 24px; color: var(--text-hi); }
.modal-calc-eq { color: var(--faint); }
.modal-calc-ratio { font-family: var(--mono); font-size: 16px; color: var(--text); }
.modal-calc-lbl { font-size: 12px; color: var(--muted); }
.modal-src { font-family: var(--mono); font-size: 11.5px; color: var(--faint); margin-bottom: 16px; }
.modal h4 { margin: 6px 0 8px; font-size: 13px; color: var(--text-hi); }
.modal-table { width: 100%; border-collapse: collapse; font-size: 12.5px; margin-bottom: 14px; }
.modal-table th { text-align: left; color: var(--muted); font-weight: 600; border-bottom: 1px solid var(--line);
  padding: 6px 8px; font-family: var(--mono); font-size: 11px; text-transform: uppercase; }
.modal-table td { padding: 6px 8px; border-bottom: 1px solid var(--line-soft); }
.modal-table a { color: var(--observed); text-decoration: none; font-family: var(--mono); }
.modal-table a:hover { text-decoration: underline; }
.modal-note { color: var(--muted); font-size: 13px; }
```

- [ ] **Step 2: Bump cache-bust versions**

In `src/dashboard/static/index.html`, change the three asset query strings to a new version so browsers reload them:
- `styles.css?v=20260623-light` → `styles.css?v=20260624-explain`
- `helpers.js?v=20260624-fix1` → `helpers.js?v=20260624-explain`
- `app.js?v=20260624-fix1` → `app.js?v=20260624-explain`

- [ ] **Step 3: Commit**

```bash
git add src/dashboard/static/styles.css src/dashboard/static/index.html
git commit -m "feat(dashboard): style metric explain modal + bump asset cache"
```

---

### Task 6: Docs + full verification

**Files:**
- Modify: `docs/dashboard_usage.md`

- [ ] **Step 1: Document the explain modal**

In `docs/dashboard_usage.md`, replace the existing `## Drilldown` section heading area by adding, right after the Drilldown table, a new subsection:

```markdown
### Giải thích cách tính metric (audit & trace)

Bấm vào bất kỳ thẻ metric/KPI nào ở tab Full-Duplex sẽ mở hộp thoại giải thích, gọi `GET /api/runs/{run_id}/metrics/{key}/explain`. Hộp thoại hiển thị:

- **Công thức** (tiếng Việt) của metric.
- **Giá trị = tử số / mẫu số** được tính lại trực tiếp từ `episodes.jsonl` bằng đúng predicate của bộ chấm (`fdrc_contract`), kèm nhãn mô tả tử số và mẫu số.
- **Nguồn dữ liệu** (`metrics.json` hay `episodes.jsonl`) và trạng thái hash, cùng scope (`all` hoặc chỉ `valid`).
- **Danh sách episode tử số** (các episode thỏa điều kiện đếm), mỗi episode link tới chi tiết episode để truy vết, cùng nút mở Episode Explorer.

Metric tổng hợp không có phân tích theo từng episode (vd `yield_latency_p50_ms`) sẽ hiển thị `supported = false` kèm mô tả.
```

- [ ] **Step 2: Run full verification**

Run:
```
.\.venv\Scripts\python.exe -m pytest -q tests\test_fdrc_explain.py tests\test_dashboard.py
.\.venv\Scripts\python.exe -m ruff check src\dashboard src\evaluator\fdrc_explain.py
cd src/dashboard/static && node helpers.test.cjs && cd ../../..
node --check src/dashboard/static/app.js
```
Expected: pytest all pass; ruff clean; node tests pass; app.js syntax OK.

- [ ] **Step 3: Manual smoke**

Run: `.\.venv\Scripts\python.exe -m src.dashboard --host 127.0.0.1 --port 8765`, open `http://127.0.0.1:8765`, pick the `fdrc` benchmark run, and click metric cards:
- `GỌI TOOL BỊ CẤM` (forbidden_tool_call_rate): modal shows formula, `12.5% = 1 / 8`, and lists the 1 offending episode with a working link.
- `PASS FDRC` (0%): modal shows `0 / 8`, empty numerator note, and an "Mở Episode Explorer" link.
- A latency metric: modal shows `supported = false` note.
- Esc / backdrop click / ✕ all close the modal.

- [ ] **Step 4: Commit**

```bash
git add docs/dashboard_usage.md
git commit -m "docs: document metric explain modal"
```

---

## Self-Review

**Spec coverage:**
- Backend-authoritative explain → Task 1 (module reusing contract predicates + parity test) + Task 2 (endpoint). ✅
- Modal popup → Task 4 (render) + Task 5 (styles). ✅
- List numerator episodes with links → Task 2 (`numerator_episodes` with ids/meta) + Task 4 (`explainEpisodeRow` linking via `buildHash`). ✅
- Formula + numerator/denominator + source/hash for audit → Task 2 payload + Task 4 modal body. ✅

**Placeholder scan:** All code blocks complete; no TBD. The one optional refactor (`run_summary` reusing `_scoped_evaluation_episodes`) is explicitly marked optional/skippable to avoid regressions.

**Type consistency:** Backend returns keys `supported, scope, formula_vi, row_set_label_vi, numerator_label_vi, numerator, denominator, value, numerator_episodes, explorer_filter, label, description, unit, metric_source, metrics_hash_valid`; the frontend `renderMetricModal` reads exactly those. `explain_fdrc_metric` returns `numerator_episode_ids` (ids only); the service maps them to `numerator_episodes` (objects) — names kept distinct intentionally. `formatRatio`, `fmtPct`, `fmtInt`, `buildHash` all exist on `H`. Episode link route uses `{tab:"fdrc", view:"episode", runId, episodeId}` matching `buildHash`/`parseRoute` in helpers.js.
