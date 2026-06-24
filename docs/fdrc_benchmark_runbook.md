# Full-Duplex Repair-to-Commit Runbook

## Benchmark Tiers

| Tier | Purpose | Scope | Performance report |
|---|---|---:|---|
| Tier 0 Reference | Check evaluator and dashboard contract | 30 overlays x 3 personas = 90 episodes | No |
| Tier 1 Provider Smoke | Check realtime audio, timeline, tool path, and validity | 1 domain x `vi_north_normal` | Validity only |
| Tier 2 Provider Domain | Score one domain at a time | Existing domain overlays x selected personas | Yes, if validity is sufficient |
| Tier 3 Provider Full Matrix | Official provider surrogate report | 30 overlays x 9 personas = 270 episodes | Yes |

Current FDRC overlay coverage is intentionally reported as-is:

| Domain | Overlays | Default 3 personas | Full 9 personas |
|---|---:|---:|---:|
| `automotive` | 8 | 24 | 72 |
| `navigation` | 9 | 27 | 81 |
| `media_phone` | 13 | 39 | 117 |

## Commands

Reference plumbing check:

```powershell
.\.venv\Scripts\python.exe run_fdrc.py --reference-agent --output results\fdrc_reference_check
```

Provider smoke by domain:

```powershell
.\.venv\Scripts\python.exe run_fdrc.py --agent openai_realtime --model gpt-realtime-mini --domains automotive --personas vi_north_normal --fdrc-yield-mode native_yield --output results\fdrc_smoke_automotive
.\.venv\Scripts\python.exe run_fdrc.py --agent openai_realtime --model gpt-realtime-mini --domains navigation --personas vi_north_normal --fdrc-yield-mode native_yield --output results\fdrc_smoke_navigation
.\.venv\Scripts\python.exe run_fdrc.py --agent openai_realtime --model gpt-realtime-mini --domains media_phone --personas vi_north_normal --fdrc-yield-mode native_yield --output results\fdrc_smoke_media_phone
```

Full matrix after smoke validity is acceptable:

```powershell
.\.venv\Scripts\python.exe run_fdrc.py --agent openai_realtime --model gpt-realtime-mini --domains automotive,navigation,media_phone --personas vi_north_slow,vi_north_normal,vi_north_fast,vi_central_slow,vi_central_normal,vi_central_fast,vi_south_slow,vi_south_normal,vi_south_fast --fdrc-yield-mode native_yield --output results\fdrc_full_provider
```

## Metric Interpretation

| Metric | Meaning |
|---|---|
| `raw_fdrc_pass_at_1` | Pass rate across all episodes, including invalid evidence. Keep for forensic debugging. |
| `fdrc_validity_rate` | Fraction of episodes with sufficient observed evidence for performance scoring. |
| `performance_fdrc_pass_at_1` | Official pass rate on valid episodes only. |
| `validity_failure_counts` | Why episodes were excluded from performance denominator. |
| `performance_yield_latency_p50_ms` / `p95_ms` | Yield latency over valid episodes only. |

Reference-agent runs validate benchmark plumbing only and must not be reported as model or Vivi performance.
