# Kế hoạch xây dựng Frontend cho Full-Duplex Repair-to-Commit Benchmark Visualizer

## 1. Context

Giao diện benchmark hiện tại lấy cảm hứng từ τ-bench text visualizer: task grid, pass@k, task detail, user scenario, expected actions, assertions. Cách này phù hợp cho text benchmark, nhưng chưa đủ cho **Full-Duplex Repair-to-Commit (FDRC)**.

FDRC không chỉ cần biết agent có gọi đúng tool hay không. Reviewer cần nhìn được:

```text
User chen ngang ở thời điểm nào?
Assistant có đang nói thật không?
Repair/cancel transcript có được nhận đúng không?
Assistant yield/stop sau bao nhiêu ms?
Tool commit xảy ra trước hay sau repair?
Tool call có phải old intent không?
Final state có side-effect sai không?
Episode có đủ evidence để tính performance không?
```

Do đó frontend FDRC phải là **forensic replay console**, không chỉ là leaderboard/pass-score dashboard.

---

## 2. Product Goals

Frontend phải phục vụ ba nhóm người dùng:

| User | Câu hỏi cần trả lời |
|---|---|
| Researcher / Evaluator | Run này có reportable không? Denominator có đúng không? |
| Voice Engineer | Lỗi do audio, ASR, timing, tool schema, final state hay provider yield? |
| Product Owner | Rủi ro side-effect trong cabin có chấp nhận được không? |

Mục tiêu chính:

1. Ngăn báo cáo sai performance khi validity thấp.
2. Visualize full-duplex overlap và repair window trực quan.
3. Làm rõ side-effect: old intent commit, early commit, cancel not respected.
4. Giúp debug nhanh failure root cause.
5. So sánh native yield với client cancel yield.

---

## 3. UX Principle

### 3.1. Không dùng tư duy text benchmark thuần túy

Text τ-bench UI:

```text
Task-first → conversation → expected actions → score
```

FDRC τ-Voice UI:

```text
Validity-first → full-duplex timeline → repair window → tool/state side-effect → score
```

### 3.2. Main mental model

Mọi màn hình phải xoay quanh repair window:

```text
assistant_speech_start
→ user_interrupt_start
→ repair_audio_start
→ repair_transcript_done
→ assistant_yielded / assistant_speech_stop
→ tool_commit_allowed_after
→ tool_call
→ tool_result
→ final_state
```

### 3.3. Không để pass score che validity

Nếu `fdrc_validity_rate < 0.90`, UI phải hiện trạng thái:

```text
VALIDITY ONLY — PERFORMANCE NOT REPORTABLE
```

Không được để người dùng hiểu `raw_fdrc_pass_at_1` là official score.

---

## 4. Information Architecture

```text
FDRC Benchmark Visualizer
├── 1. Run Overview
├── 2. Overlay Catalog
├── 3. Episode Explorer
├── 4. Episode Detail: Full-Duplex Timeline
├── 5. Assertion Panel
├── 6. Tool / State Diff
├── 7. Failure Analysis
├── 8. Compare Runs
└── 9. Artifact / Provenance
```

Navigation đề xuất:

```text
Top bar:
  Run Selector | Overview | Episodes | Failures | Compare | Artifacts

Left filter rail:
  Domain
  Persona
  Yield Mode
  Validity
  Final Result
  Failure Type
  Intent Type
  Risk Level
```

---

## 5. Screen 1 — Run Overview

### 5.1. Purpose

Cho reviewer biết ngay run này có được phép báo cáo performance không.

### 5.2. Layout

```text
┌────────────────────────────────────────────────────────────────────┐
│ FDRC Run: fdrc_smoke_automotive_native                             │
│ Provider: OpenAI Realtime | Model: gpt-realtime-mini                │
│ Yield Mode: native_yield | Tick: 200 ms | Run Kind: provider        │
│ Reportability: VALIDITY ONLY                                       │
└────────────────────────────────────────────────────────────────────┘

┌──────────────┬──────────────┬──────────────┬──────────────┐
│ Validity     │ Official FDRC│ Raw FDRC     │ Valid / Total│
│ 87.5%        │ N/A          │ 12.5%        │ 7 / 8        │
└──────────────┴──────────────┴──────────────┴──────────────┘

┌──────────────┬──────────────┬──────────────┬──────────────┐
│ Correction   │ Old Intent   │ Cancel       │ Yield P95    │
│ Uptake       │ Suppression  │ Success      │ 3401 ms      │
└──────────────┴──────────────┴──────────────┴──────────────┘
```

### 5.3. Metric cards

Thứ tự ưu tiên:

1. `fdrc_validity_rate`
2. `performance_fdrc_pass_at_1`
3. `valid_episode_count / total_episode_count`
4. `raw_fdrc_pass_at_1`
5. `correction_uptake_rate`
6. `old_intent_suppression_rate`
7. `cancel_success_rate`
8. `performance_yield_latency_p50_ms`
9. `performance_yield_latency_p95_ms`
10. `validity_failure_counts`

### 5.4. Reportability badge

| Status | Meaning | UI behavior |
|---|---|---|
| `NOT_REPORTABLE` | Metadata/hash missing hoặc validity quá thấp | Disable official score |
| `VALIDITY_ONLY` | Có thể debug nhưng chưa report performance | Warning banner |
| `REPORTABLE_DOMAIN` | Domain-level performance hợp lệ | Show official score |
| `REPORTABLE_FULL_MATRIX` | Full matrix reportable | Enable export report |

### 5.5. Domain x persona matrix

```text
┌─────────────┬───────────────┬───────────────┬───────────────┐
│ Domain      │ North Normal  │ Central Normal│ South Normal  │
│ Automotive  │ 1/8 pass      │ not run       │ not run       │
│ Navigation  │ not run       │ not run       │ not run       │
│ MediaPhone  │ not run       │ not run       │ not run       │
└─────────────┴───────────────┴───────────────┴───────────────┘
```

Matrix cell nên hiện:

```text
valid / total
performance pass, nếu reportable
primary dominant failure, nếu fail
```

---

## 6. Screen 2 — Overlay Catalog

### 6.1. Purpose

Thay task card kiểu text benchmark bằng FDRC overlay card.

### 6.2. Overlay card

```text
┌───────────────────────────────────────────────┐
│ Overlay: fdrc_auto_003                         │
│ Domain: automotive                             │
│ Type: correction_before_commit                 │
│ Risk: side_effect_critical                     │
│                                                │
│ Initial: Set driver temperature to 22°C        │
│ Repair:  No, make it 24°C instead             │
│                                                │
│ Expected: climate.set_temperature(driver, 24)  │
│ Forbidden: climate.set_temperature(driver, 22) │
│                                                │
│ Episodes: 8 total | 7 valid | 3 pass | 4 fail │
│ Dominant failure: YIELD_TIMEOUT                │
└───────────────────────────────────────────────┘
```

### 6.3. Filters

| Filter | Values |
|---|---|
| Domain | `automotive`, `navigation`, `media_phone` |
| Persona | `vi_north_*`, `vi_central_*`, `vi_south_*` |
| Yield mode | `native_yield`, `client_cancel_yield` |
| Validity | `valid`, `invalid`, `all` |
| Final result | `pass`, `fail`, `invalid` |
| Failure type | `YIELD_TIMEOUT`, `OLD_INTENT_COMMITTED`, etc. |
| Intent type | correction, cancel, change destination, change media, cancel call |
| Risk level | safety-critical, side-effect-critical, low-risk |

---

## 7. Screen 3 — Episode Explorer

### 7.1. Purpose

Bảng forensic để tìm nhanh fail/invalid episodes.

### 7.2. Table layout

```text
┌──────────────┬────────────┬────────────┬────────────┬────────────┬──────────────┬──────────────┐
│ Episode ID   │ Domain     │ Persona    │ Validity   │ Final Pass │ Yield ms     │ Primary Fail │
├──────────────┼────────────┼────────────┼────────────┼────────────┼──────────────┼──────────────┤
│ auto_003_n_n │ automotive │ north_norm │ VALID      │ FAIL       │ 2548         │ YIELD_TIMEOUT│
│ auto_004_n_n │ automotive │ north_norm │ INVALID    │ N/A        │ null         │ INVALID_AUDIO│
│ nav_002_s_f  │ navigation │ south_fast │ VALID      │ FAIL       │ 500          │ OLD_INTENT   │
└──────────────┴────────────┴────────────┴────────────┴────────────┴──────────────┴──────────────┘
```

### 7.3. Required columns

```text
episode_id
overlay_id
domain
persona
fdrc_yield_mode
validity_status
validity_reasons
final_pass
task_pass
policy_pass
voice_pass
primary_failure_type
initial_intent
final_intent
correction_text
yield_latency_ms
tool_commit_time_ms
old_intent_committed
correction_uptaken
cancel_success
state_match
```

### 7.4. Row status rules

| Condition | Row status |
|---|---|
| `fdrc_validity.valid == false` | Invalid row, no official score |
| `final_pass == 1` | Pass row |
| `final_pass == 0` and valid | Fail row |
| `primary_failure_type` exists | Show failure chip |

---

## 8. Screen 4 — Episode Detail: Full-Duplex Timeline

### 8.1. Purpose

Đây là màn hình quan trọng nhất. Nó phải giúp reviewer thấy toàn bộ repair-to-commit chain trong một timeline duy nhất.

### 8.2. Header

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Episode auto_003_vi_north_normal                                     │
│ Result: FAIL | Validity: VALID | Primary Failure: YIELD_TIMEOUT       │
│ Initial: set temperature 22°C → Repair: make it 24°C                 │
│ Expected: climate.set_temperature(driver, 24)                         │
│ Forbidden: climate.set_temperature(driver, 22)                        │
└──────────────────────────────────────────────────────────────────────┘
```

### 8.3. Two-column summary

```text
┌───────────────────────────────┬──────────────────────────────────────┐
│ Overlay Contract              │ Verdict Panel                        │
│ - task description            │ - Validity: VALID                    │
│ - initial intent              │ - Task pass: yes/no                  │
│ - repair utterance            │ - Policy pass: yes/no                │
│ - expected tool call          │ - Voice pass: yes/no                 │
│ - forbidden tool call         │ - Yield latency: 2548 ms             │
│ - expected final state        │ - Failure types                      │
└───────────────────────────────┴──────────────────────────────────────┘
```

### 8.4. Timeline lanes

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Full-Duplex Timeline                                                  │
│ 0ms        1000      2000      3000      4000      5000      6000     │
│ User audio        █████████      █████ repair █████                  │
│ User transcript   "Bật điều hòa..." "Không, tăng lên 24 độ cơ"       │
│ Assistant speech        ███████████████████████                       │
│ Assistant text          "Được, tôi sẽ đặt..."                         │
│ Events             A_start   Interrupt Repair_done Yield Tool_call    │
│ Tool calls                                      climate.set_temp(24)   │
│ State mutation                                  driver_temp = 24       │
│ Assertions          speaking_before_interrupt ✓ yield_latency ✗       │
└──────────────────────────────────────────────────────────────────────┘
```

Required lanes:

| Lane | Nội dung | Purpose |
|---|---|---|
| Time axis | ms/tick scale | Định vị events |
| User audio | audio chunks / speech activity | Chứng minh có audio ingress |
| User transcript | initial + repair transcript | Debug ASR/repair |
| Assistant speech | assistant speech activity | Chứng minh overlap |
| Assistant transcript | assistant text/audio transcript | Phát hiện old confirmation |
| Event markers | expected/observed markers | So sánh contract vs reality |
| Tool calls | tool name/args/timestamp | Phát hiện early/old commit |
| Tool results | result timestamp/status | Phát hiện missing result |
| State mutation | state changes | Phát hiện side-effect |
| Assertions | rule pass/fail | Debug nhanh |

### 8.5. Required markers

```text
assistant_speech_start
user_interrupt_start
repair_audio_start
repair_transcript_done
assistant_yielded
assistant_speech_stop
tool_commit_allowed_after
tool_call
tool_result
final_state_observed
```

### 8.6. Timeline interactions

| Interaction | Behavior |
|---|---|
| Zoom to repair window | Auto zoom `user_interrupt_start ± 2000 ms` |
| Hover marker | Show event name, source, t_ms, raw payload |
| Click tool call | Open expected vs observed args diff |
| Click transcript segment | Highlight corresponding audio chunk |
| Toggle expected/observed | Show contract vs provider evidence |
| Playback sync | Audio cursor follows timeline, nếu có audio artifact |
| Show invalid evidence | Missing event pinned on timeline |

---

## 9. Screen 5 — Assertion Panel

### 9.1. Purpose

Không chỉ hiển thị fail/pass tổng. Phải hiển thị từng rule.

```text
FDRC Assertions

Validity
[pass] assistant_speech_start observed
[pass] user_interrupt_start observed
[pass] repair_audio_start observed
[pass] repair_transcript_done observed
[fail] assistant_yielded observed within threshold

Repair
[pass] assistant was speaking before interrupt
[pass] repair transcript matched expected repair utterance
[fail] correction uptake
[pass] forbidden old intent was not committed

Commit Safety
[pass] no tool call before repair_transcript_done
[pass] no tool call before tool_commit_allowed_after
[fail] final state mismatch

Final Result
task_pass: false
policy_pass: false
voice_pass: false
final_pass: false
```

### 9.2. Assertion groups

| Group | Rules |
|---|---|
| Validity | observed evidence, audio, transcript, tool result, final state |
| Repair | correction uptake, cancel respect, transcript match |
| Timing | speaking before interrupt, yield latency, commit after repair |
| Tool | expected call, forbidden call, duplicate commit |
| State | expected vs observed state |
| Final | task/policy/voice/final pass |

---

## 10. Screen 6 — Tool / State Diff

### 10.1. Purpose

FDRC đo side-effect, nên tool/state diff là P0.

### 10.2. Correction case

```text
Expected Tool Call
climate.set_temperature({
  zone: "driver",
  temperature_c: 24
})

Observed Tool Call
climate.set_temperature({
  zone: "driver",
  temperature_c: 22
})

Diff
temperature_c:
  expected: 24
  observed: 22

Verdict
OLD_INTENT_COMMITTED
CORRECTION_NOT_UPTAKEN
FINAL_STATE_MISMATCH
```

### 10.3. Cancel case

```text
Expected:
no tool call
final_state unchanged

Observed:
phone.call_contact({ contact: "Mẹ" })

Verdict:
CANCEL_NOT_RESPECTED
FORBIDDEN_TOOL_CALL
OLD_INTENT_COMMITTED
```

### 10.4. Display modes

| Mode | Purpose |
|---|---|
| Compact diff | Reviewer đọc nhanh |
| JSON diff | Engineer debug schema |
| State tree | Product owner thấy side-effect |
| Raw tool log | Provider/tool adapter debugging |

---

## 11. Screen 7 — Failure Analysis

### 11.1. Purpose

Aggregate root cause across run.

### 11.2. Required charts

| Chart | Meaning |
|---|---|
| Failure Pareto | Lỗi nào chiếm nhiều nhất |
| Validity failure breakdown | `INVALID_AUDIO`, `INVALID_EVIDENCE`, etc. |
| Domain x failure heatmap | Domain nào fail vì gì |
| Persona x failure heatmap | Accent/speed ảnh hưởng thế nào |
| Yield latency distribution | P50/P95/P99, threshold line |
| Commit timing scatter | `tool_call_time - repair_transcript_done`; âm là early commit |
| Old intent rate by domain | Rủi ro side-effect |
| Native vs client cancel delta | Product mitigation effect |

### 11.3. Failure taxonomy chips

```text
ASR_REPAIR_MISS
YIELD_TIMEOUT
OLD_INTENT_COMMITTED
REPAIR_NOT_UPTAKEN
EARLY_COMMIT
CANCEL_NOT_RESPECTED
SCHEMA_MAPPING_ERROR
FINAL_STATE_MISMATCH
DUPLICATE_FINAL_COMMIT
MISSING_OBSERVED_EVENT
INVALID_AUDIO
INVALID_EVIDENCE
INVALID_TRANSCRIPT
INVALID_TOOL_RESULT
INVALID_FINAL_STATE
```

---

## 12. Screen 8 — Compare Runs

### 12.1. Purpose

So sánh trước/sau fix hoặc native/client-cancel.

### 12.2. Compare modes

```text
Reference vs Provider
Native Yield vs Client Cancel Yield
Clean vs Cabin / Interaction Stress
OpenAI Realtime model A vs model B
Prompt/schema version A vs B
Before fix vs After fix
```

### 12.3. Layout

```text
┌───────────────────────┬───────────────────────┐
│ Run A: native_yield    │ Run B: client_cancel   │
├───────────────────────┼───────────────────────┤
│ Validity: 92%          │ Validity: 96%          │
│ FDRC pass: 25%         │ FDRC pass: 75%         │
│ Yield P95: 3401 ms     │ Yield P95: 480 ms      │
│ Old intent: 37.5%      │ Old intent: 0%         │
└───────────────────────┴───────────────────────┘

Episode Pair Timeline
A: assistant continues old confirmation after interrupt
B: client cancel stops assistant at 400 ms, no old intent commit
```

### 12.4. Delta metrics

```text
Δ validity_rate
Δ performance_fdrc_pass_at_1
Δ correction_uptake_rate
Δ old_intent_suppression_rate
Δ cancel_success_rate
Δ yield_latency_p95_ms
Δ forbidden_tool_call_rate
```

---

## 13. Data Contract for Frontend

### 13.1. Static files MVP

```text
/public/results/
  fdrc_smoke_automotive_native/
    run_metadata.json
    metrics.json
    episodes.jsonl
```

Frontend load static files and parse JSONL client-side. Với 270 episodes, chưa cần database.

### 13.2. Run summary type

```ts
export type RunSummary = {
  run_id: string;
  run_kind: "reference" | "provider" | "sample" | "internal" | "imported" | "unknown";
  provider?: string;
  model?: string;
  adapter?: string;
  fdrc_yield_mode: "native_yield" | "client_cancel_yield";
  tick_ms: 200;
  episode_set_hash?: string;
  domains: string[];
  personas: string[];
  reportability_status: "NOT_REPORTABLE" | "VALIDITY_ONLY" | "REPORTABLE_DOMAIN" | "REPORTABLE_FULL_MATRIX";
  metrics: FdrcMetrics;
};
```

### 13.3. Metrics type

```ts
export type FdrcMetrics = {
  total_episode_count: number;
  valid_episode_count: number;
  invalid_episode_count: number;
  fdrc_validity_rate: number | null;
  raw_fdrc_pass_at_1: number | null;
  performance_fdrc_pass_at_1: number | null;
  correction_uptake_rate: number | null;
  old_intent_suppression_rate: number | null;
  forbidden_tool_call_rate: number | null;
  cancel_success_rate: number | null;
  performance_yield_latency_p50_ms: number | null;
  performance_yield_latency_p95_ms: number | null;
  performance_yield_latency_pass_rate: number | null;
  validity_failure_counts: Array<{ key: string; count: number }>;
};
```

### 13.4. Episode type

```ts
export type FdrcEpisode = {
  episode_id: string;
  run_id: string;
  overlay_id: string;
  domain: "automotive" | "navigation" | "media_phone";
  persona: string;
  fdrc_yield_mode: "native_yield" | "client_cancel_yield";

  fdrc_validity: {
    valid: boolean;
    status: "VALID" | "INVALID";
    reasons: string[];
    observed_repair_transcript?: string;
    missing_observed_events?: string[];
  };

  scores: {
    task_pass: 0 | 1;
    policy_pass: 0 | 1;
    voice_pass: 0 | 1;
    final_pass: 0 | 1;
  };

  repair: {
    initial_intent?: string;
    final_intent?: string;
    correction_text?: string;
    old_intent_committed?: boolean;
    correction_uptaken?: boolean;
    forbidden_tool_called?: boolean;
    duplicate_final_commit?: boolean;
    assistant_speaking_before_interrupt?: boolean;
    missing_observed_events?: string[];
    tool_commit_time_ms?: number | null;
  };

  latency: {
    yield_latency_ms?: number | null;
  };

  voice_events: TimelineEvent[];
  normalized_events: NormalizedEvent[];
  tool_calls: ToolCall[];
  tool_results: ToolResult[];
  final_state: Record<string, unknown>;
  state_diff?: StateDiff;
  failure_types: string[];
  primary_failure_type?: string | null;
};
```

### 13.5. Timeline event type

```ts
export type TimelineEvent = {
  event: string;
  source: "expected" | "observed";
  t_ms: number;
  tick?: number;
  payload?: Record<string, unknown>;
};
```

---

## 14. Frontend Architecture

### 14.1. Recommended stack

```text
React + TypeScript + Vite
TanStack Table for episode explorer
SVG custom timeline component
D3 scale only for timeline coordinate mapping
Monaco Editor or react-json-view for raw JSON
Zustand or URL state for filters
```

Không nên dùng chart framework quá nặng cho timeline. Timeline cần custom SVG để kiểm soát lanes, markers, zoom và expected/observed overlay.

### 14.2. Component tree

```text
App
├── Layout
│   ├── TopNav
│   ├── RunSelector
│   └── FilterRail
├── RunOverview
│   ├── ReportabilityBadge
│   ├── MetricCards
│   ├── DomainPersonaMatrix
│   └── ValidityFailureSummary
├── OverlayCatalog
│   ├── OverlayCardGrid
│   └── OverlayFilters
├── EpisodeExplorer
│   ├── EpisodeFilterBar
│   ├── EpisodeTable
│   └── FailureChips
├── EpisodeDetail
│   ├── EpisodeHeader
│   ├── OverlayContractPanel
│   ├── VerdictPanel
│   ├── FullDuplexTimeline
│   │   ├── TimelineScale
│   │   ├── UserAudioLane
│   │   ├── UserTranscriptLane
│   │   ├── AssistantSpeechLane
│   │   ├── AssistantTranscriptLane
│   │   ├── EventMarkerLane
│   │   ├── ToolCallLane
│   │   ├── ToolResultLane
│   │   ├── StateMutationLane
│   │   └── AssertionLane
│   ├── AssertionPanel
│   ├── ToolStateDiff
│   └── RawEventInspector
├── FailureAnalysis
│   ├── FailurePareto
│   ├── ValidityBreakdown
│   ├── DomainFailureHeatmap
│   ├── PersonaFailureHeatmap
│   ├── YieldLatencyDistribution
│   └── CommitTimingScatter
└── CompareRuns
    ├── RunCompareSelector
    ├── CompareMetricCards
    ├── DeltaTable
    └── PairedEpisodeTimeline
```

### 14.3. Routing

```text
/                                     -> Run overview
/runs/:runId                          -> Run overview
/runs/:runId/overlays                 -> Overlay catalog
/runs/:runId/episodes                 -> Episode explorer
/runs/:runId/episodes/:episodeId      -> Episode detail
/runs/:runId/failures                 -> Failure analysis
/compare?runA=...&runB=...            -> Compare runs
```

---

## 15. Visual Design System

### 15.1. Semantic status colors

Không dùng màu trang trí. Màu phải mang nghĩa trạng thái.

| Status | Meaning |
|---|---|
| Green | Pass / valid / expected satisfied |
| Yellow | Warning / partial / validity risk |
| Red | Fail / invalid / policy violation |
| Gray | Not run / not applicable / reference only |
| Blue | Observed provider event |
| Purple | Tool/state mutation |

Expected vs observed phải phân biệt bằng cả màu và kiểu nét:

| Event source | Style |
|---|---|
| Expected | Dashed line |
| Observed | Solid line |

### 15.2. Badges

```text
VALID
INVALID_AUDIO
INVALID_EVIDENCE
INVALID_TRANSCRIPT
INVALID_TOOL_RESULT
INVALID_FINAL_STATE
PASS
FAIL
VALIDITY_ONLY
REPORTABLE
REFERENCE_ONLY
```

### 15.3. Layout density

Reviewer cần forensic detail nhưng không được rối. Mỗi screen dùng hierarchy:

```text
1. Status summary
2. Key evidence
3. Detailed diff
4. Raw JSON fallback
```

---

## 16. Timeline Design Detail

### 16.1. Coordinate mapping

```ts
const x = scaleLinear()
  .domain([0, episodeDurationMs])
  .range([leftPadding, width - rightPadding]);
```

### 16.2. Lane heights

```text
Time axis:              24 px
User audio:             40 px
User transcript:        48 px
Assistant speech:       40 px
Assistant transcript:   48 px
Event markers:          48 px
Tool calls:             48 px
Tool results:           36 px
State mutation:         40 px
Assertions:             40 px
```

### 16.3. Repair window highlight

Highlight region:

```text
from user_interrupt_start
to max(repair_transcript_done, assistant_yielded, tool_call)
```

### 16.4. Commit safety visualization

If tool call occurs before `repair_transcript_done` or `tool_commit_allowed_after`, show red connector:

```text
repair_transcript_done ───── expected safe boundary
        tool_call ▲ occurs before boundary -> EARLY_COMMIT
```

### 16.5. Yield latency visualization

```text
Yield latency = assistant_yielded.t_ms - user_interrupt_start.t_ms
```

Show threshold line:

```text
user_interrupt_start + max_yield_latency_ms
```

If `assistant_yielded` after threshold, mark `YIELD_TIMEOUT`.

---

## 17. Data Loading and State Management

### 17.1. MVP static loader

```ts
async function loadRun(runId: string) {
  const [metadata, metrics, episodesText] = await Promise.all([
    fetch(`/results/${runId}/run_metadata.json`).then(r => r.json()),
    fetch(`/results/${runId}/metrics.json`).then(r => r.json()),
    fetch(`/results/${runId}/episodes.jsonl`).then(r => r.text()),
  ]);

  const episodes = episodesText
    .trim()
    .split("\n")
    .filter(Boolean)
    .map(line => JSON.parse(line));

  return { metadata, metrics, episodes };
}
```

### 17.2. Derived selectors

Frontend nên derive:

```text
filteredEpisodes
validEpisodes
invalidEpisodes
failureCounts
domainPersonaMatrix
overlaySummaries
yieldLatencyDistribution
commitTimingDeltas
nativeVsClientCancelDelta
```

Backend nên cung cấp sẵn nếu có API, nhưng MVP frontend có thể tự tính cho 270 episodes.

### 17.3. URL state

Filters nên lưu trên URL để share forensic view.

```text
/runs/fdrc_smoke/episodes?domain=automotive&validity=invalid&failure=INVALID_EVIDENCE
```

---

## 18. MVP Implementation Plan

### Day 1 — Data loader and Run Overview

Output:

```text
Load metrics.json + episodes.jsonl.
Show run metadata.
Show reportability badge.
Show validity/raw/performance metric cards.
Show validity failure counts.
```

### Day 2 — Episode Explorer

Output:

```text
Table with filters.
Sortable by validity, final_pass, yield_latency, primary_failure_type.
Click row opens episode detail.
```

### Day 3 — Episode Detail Shell

Output:

```text
Episode header.
Overlay contract panel.
Verdict panel.
Assertion panel.
Raw JSON inspector.
```

### Day 4 — Full-Duplex Timeline

Output:

```text
SVG timeline with time axis.
Lanes for user audio, assistant speech, events, tool calls, state mutation.
Repair window highlight.
Expected vs observed toggle.
```

### Day 5 — Tool / State Diff

Output:

```text
Expected vs observed tool call diff.
Expected vs observed final state diff.
Cancel case support.
Old intent committed visual warning.
```

### Day 6 — Failure Analysis

Output:

```text
Failure Pareto.
Validity breakdown.
Yield latency distribution.
Commit timing scatter.
Domain x failure summary.
```

### Day 7 — Compare Runs

Output:

```text
Run A/B selector.
Native yield vs client cancel comparison.
Delta metrics.
Paired episode timeline, if overlay/persona match.
```

---

## 19. Acceptance Criteria

Frontend đạt chuẩn khi reviewer có thể trả lời trong dưới 60 giây cho mỗi fail episode:

1. Episode này valid hay invalid?
2. Nếu invalid, thiếu evidence nào?
3. User chen ngang lúc nào?
4. Assistant có đang nói khi user chen ngang không?
5. Repair transcript thực tế là gì?
6. Assistant yield/stop sau bao nhiêu ms?
7. Tool call xảy ra trước hay sau repair?
8. Tool call có phải old intent không?
9. Final state khác expected ở đâu?
10. Lỗi chính thuộc audio/ASR/timing/tool/state/policy hay product cancellation?

---

## 20. Non-Goals for MVP

Không làm trong frontend MVP:

1. Realtime live monitoring dashboard.
2. 3D waveform hoặc audio visualization quá phức tạp.
3. Leaderboard public-grade.
4. Multi-user collaboration/review comments.
5. Authentication/authorization.
6. Full database-backed analytics.
7. Persona profile quá chi tiết.

---

## 21. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| UI quá giống text τ-bench | Không thấy full-duplex lỗi timing | Timeline-first episode detail |
| Score card quá nổi bật | Người dùng bỏ qua validity | Reportability badge và validity card đặt đầu |
| Timeline quá rối | Reviewer khó debug | Lane grouping + repair window zoom |
| Raw JSON thiếu | Engineer không debug được adapter | Raw event inspector luôn có |
| Expected/observed khó phân biệt | Misread event contract | Color + line style + source badge |
| State diff frontend tự tính sai | Sai forensic conclusion | Backend nên sinh `state_diff`; frontend chỉ render |

---

## 22. Final Recommendation

Frontend FDRC nên được thiết kế như một **benchmark forensic console** thay vì một dashboard điểm số.

Cấu trúc ưu tiên:

```text
Run Overview
→ Episode Explorer
→ Full-Duplex Timeline
→ Assertion Panel
→ Tool/State Diff
→ Failure Analysis
→ Compare Runs
```

P0 components:

```text
1. ReportabilityBadge
2. MetricCards with validity/raw/performance split
3. EpisodeTable with failure filters
4. FullDuplexTimeline
5. AssertionPanel
6. ToolStateDiff
7. RawEventInspector
```

Triết lý thiết kế cuối cùng:

```text
A good FDRC frontend does not merely show whether the agent passed.
It shows why the result is trustworthy, where the repair happened,
whether the assistant yielded, and whether the old intent caused a side-effect.
```
