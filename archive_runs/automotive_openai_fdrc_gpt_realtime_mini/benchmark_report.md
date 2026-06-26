# FDRC Benchmark Report: automotive_openai_fdrc_gpt_realtime_mini

Benchmark status: `failed_evaluated`

## Metrics

| Metric | Value |
|---|---:|
| episode_count | 8 |
| completed_episode_count | 8 |
| partial_episode_count | 0 |
| fdrc_pass_at_1 | 0.0 |
| pass_at_1 | 0.0 |
| yield_latency_p50_ms | 2548.0 |
| yield_latency_p95_ms | 3401.0 |
| yield_latency_pass_rate | 0.125 |
| policy_violation_rate | 0.375 |
| state_match | 0.0 |
| tool_validation_error_rate | 0.375 |
| old_intent_suppression_rate | 0.875 |
| forbidden_tool_call_rate | 0.125 |
| correction_uptake_rate | 0.0 |
| cancel_success_rate | null |

## Null Reasons

| Metric | Reason | Denominator |
|---|---|---:|
| cancel_success_rate | no_cancel_cases | 0 |

## Failure Counts

| Failure Type | Count |
|---|---:|
| FINAL_STATE_MISMATCH | 8 |
| CORRECTION_NOT_UPTAKEN | 8 |
| TOOL_SELECTION_ERROR | 7 |
| YIELD_LATENCY_TOO_HIGH | 7 |
| TOOL_ARGUMENT_ERROR | 4 |
| VALIDATION_ERROR | 3 |
| FABRICATED_SUCCESS | 3 |
| POLICY_VIOLATION | 3 |
| MISSING_OBSERVED_EVENT | 2 |
| FORBIDDEN_TOOL_CALL | 1 |
| OLD_INTENT_COMMITTED | 1 |

## Episode Evidence

| Episode | Completed | Observed Events OK | Yield ms | Final State Match | Correction Uptake | Old Intent Suppressed | Forbidden Tool | Validation Error | Fail Reasons |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| fdrc_vehicle_001:full_duplex_repair_to_commit:vi_north_normal:openai_realtime:gpt-realtime-mini | true | false | 2617 | false | false | true | false | false | TOOL_SELECTION_ERROR, FINAL_STATE_MISMATCH, CORRECTION_NOT_UPTAKEN, YIELD_LATENCY_TOO_HIGH, MISSING_OBSERVED_EVENT |
| fdrc_vehicle_002:full_duplex_repair_to_commit:vi_north_normal:openai_realtime:gpt-realtime-mini | true | true | 47 | false | false | true | false | true | VALIDATION_ERROR, TOOL_SELECTION_ERROR, TOOL_ARGUMENT_ERROR, FINAL_STATE_MISMATCH, FABRICATED_SUCCESS, CORRECTION_NOT_UPTAKEN, POLICY_VIOLATION |
| fdrc_vehicle_003:full_duplex_repair_to_commit:vi_north_normal:openai_realtime:gpt-realtime-mini | true | true | 2858 | false | false | true | false | false | TOOL_SELECTION_ERROR, FINAL_STATE_MISMATCH, CORRECTION_NOT_UPTAKEN, YIELD_LATENCY_TOO_HIGH |
| fdrc_vehicle_004:full_duplex_repair_to_commit:vi_north_normal:openai_realtime:gpt-realtime-mini | true | true | 3216 | false | false | true | false | true | VALIDATION_ERROR, TOOL_SELECTION_ERROR, TOOL_ARGUMENT_ERROR, FINAL_STATE_MISMATCH, FABRICATED_SUCCESS, CORRECTION_NOT_UPTAKEN, YIELD_LATENCY_TOO_HIGH |
| fdrc_vehicle_005:full_duplex_repair_to_commit:vi_north_normal:openai_realtime:gpt-realtime-mini | true | true | 1018 | false | false | true | false | false | TOOL_SELECTION_ERROR, FINAL_STATE_MISMATCH, CORRECTION_NOT_UPTAKEN, YIELD_LATENCY_TOO_HIGH, POLICY_VIOLATION |
| fdrc_vehicle_006:full_duplex_repair_to_commit:vi_north_normal:openai_realtime:gpt-realtime-mini | true | false | 2175 | false | false | true | false | false | TOOL_SELECTION_ERROR, FINAL_STATE_MISMATCH, CORRECTION_NOT_UPTAKEN, YIELD_LATENCY_TOO_HIGH, MISSING_OBSERVED_EVENT |
| fdrc_vehicle_007:full_duplex_repair_to_commit:vi_north_normal:openai_realtime:gpt-realtime-mini | true | true | 3401 | false | false | true | false | true | VALIDATION_ERROR, TOOL_SELECTION_ERROR, TOOL_ARGUMENT_ERROR, FINAL_STATE_MISMATCH, FABRICATED_SUCCESS, CORRECTION_NOT_UPTAKEN, YIELD_LATENCY_TOO_HIGH |
| fdrc_vehicle_008:full_duplex_repair_to_commit:vi_north_normal:openai_realtime:gpt-realtime-mini | true | true | 2479 | false | false | false | true | false | TOOL_ARGUMENT_ERROR, FINAL_STATE_MISMATCH, FORBIDDEN_TOOL_CALL, OLD_INTENT_COMMITTED, CORRECTION_NOT_UPTAKEN, YIELD_LATENCY_TOO_HIGH, POLICY_VIOLATION |
