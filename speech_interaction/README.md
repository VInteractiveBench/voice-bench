# Vivi-τVoice-CarBench-VN

Vivi-τVoice-CarBench-VN is the Vietnamese in-car speech interaction layer for
VInteractiveBench. It evaluates task-grounded Vivi behavior in exactly two tracks:

1. Text-to-Voice Capability Retention
2. Full-Duplex Repair-to-Commit

The benchmark does not score voice naturalness or word error rate as the task outcome.
It deterministically evaluates official tool selection, argument validity, final state,
critical spoken slots, interruption yield behavior, and suppression of superseded intent.

## Data Ownership

`base_task_manifest.json` is a normalized index over logical domain tasks. Automotive
entries reference the existing `data/tau2/domains/automotive/tasks.json`; navigation and
media_phone entries reference their domain-owned task files in the same canonical tau2 data
tree. `speech_task_overlays.jsonl` owns only speech-specific conditions and repair timelines.

## Run

Evaluate externally produced Vivi episode logs:

```powershell
python run_text_baseline.py --episode-logs path/to/text.jsonl --output results/text_baseline
python run_voice_retention.py --episode-logs path/to/voice.jsonl --output results/voice_retention
python run_fdrc.py --episode-logs path/to/fdrc.jsonl --output results/fdrc
python generate_voice_report.py
```

Validate benchmark plumbing with deterministic oracle episodes:

```powershell
python run_text_baseline.py --reference-agent
python run_voice_retention.py --reference-agent
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
python run_text_baseline.py --agent openai_text --model gpt-4o-mini --output results/text_baseline
python run_voice_retention.py --agent openai_realtime --model gpt-realtime-mini --output results/voice_retention
python run_fdrc.py --agent openai_realtime --model gpt-realtime-mini --tick-ms 200 --output results/fdrc
```

Set `OPENAI_API_KEY` before using OpenAI-backed adapters. `gpt-4o-mini` is used only for
the low-cost text baseline; voice retention and FDRC require a realtime/audio adapter and
must not be reported from a text-only model. The adapters are intentionally provider-neutral
at the benchmark boundary so a future real Vivi adapter can replace only the agent layer.

Regenerate committed benchmark assets after modifying the source catalog:

```powershell
python scripts/generate_vivi_speech_assets.py
```
