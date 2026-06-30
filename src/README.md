# Vivi-τVoice-CarBench-VN

Vivi-τVoice-CarBench-VN is the Vietnamese in-car speech interaction layer for
VInteractiveBench. It evaluates task-grounded Vivi behavior in exactly two tracks:

1. Policy-Grounded Voice Command Gating
2. Full-Duplex Repair-to-Commit

The benchmark does not score voice naturalness or word error rate as the task outcome.
It deterministically evaluates the execute/clarify/refuse/defer decision, official tool
selection, argument validity, final state, forbidden-tool prevention, interruption yield
behavior, and suppression of superseded intent.

## Data Ownership

`base_task_manifest.json` is a normalized index over logical domain tasks. Automotive
entries reference the existing `data/tau2/domains/automotive/tasks.json`; navigation and
media_phone entries reference their domain-owned task files in the same canonical tau2 data
tree. `data/jsonl/speech_task_overlays.jsonl` owns only speech-specific conditions and repair timelines.

## Run

Evaluate externally produced Vivi episode logs:

```powershell
python run_policy_gating.py --episode-logs path/to/policy.jsonl --output results/policy_gating
python run_fdrc.py --episode-logs path/to/fdrc.jsonl --output results/fdrc
```

Validate benchmark plumbing with deterministic oracle episodes:

```powershell
python run_policy_gating.py --reference-agent
python run_fdrc.py --reference-agent
```

Reference-agent results are synthetic and must never be reported as Vivi performance.

## Episode Contract

Each JSONL episode must identify `base_task_id`, `speech_overlay_id`, `mode`, final state,
assistant/user transcripts, tool calls, captured critical slots, validation/policy errors,
and timestamped voice events. FDRC episodes must log `user_interrupt_start` and
`assistant_yielded`; tool calls should include `t_ms` when commit timing is available.

## OpenAI-as-Vivi Surrogate

When no production Vivi API is available, run OpenAI as a Vivi surrogate. All OpenAI tool
calls still pass through `MockToolServer`, and the deterministic evaluator re-validates
scope, schema, final state, critical slots, and full-duplex behavior.

```powershell
python run_policy_gating.py --agent openai_realtime --model gpt-realtime-mini --output results/policy_gating
python run_fdrc.py --agent openai_realtime --model gpt-realtime-mini --tick-ms 200 --output results/fdrc
```

Set `OPENAI_API_KEY` before using OpenAI-backed adapters. FDRC requires a realtime/audio
adapter; the policy-gating track is deterministic-first and runs on transcripts/structured
decisions. The adapters are intentionally provider-neutral at the benchmark boundary so a
future real Vivi adapter can replace only the agent layer.

Regenerate committed benchmark assets after modifying the source catalog:

```powershell
python scripts/generate_vivi_speech_assets.py
```
