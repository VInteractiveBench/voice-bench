# Kế hoạch xây dựng Backend cho Full-Duplex Repair-to-Commit Benchmark

## 1. Context

**Full-Duplex Repair-to-Commit (FDRC)** là track benchmark ưu tiên cho trợ lý giọng nói trong xe vì nó đo rủi ro side-effect nguy hiểm nhất: người dùng đã **sửa** hoặc **hủy** lệnh trong lúc assistant đang nói, nhưng hệ thống vẫn commit ý định cũ.

Trong bối cảnh Vivi/in-car assistant, lỗi FDRC không phải chỉ là lỗi hội thoại. Nó có thể dẫn tới các side-effect cụ thể như:

- Đặt sai nhiệt độ điều hòa.
- Mở/đóng sai cửa sổ.
- Gọi nhầm liên hệ.
- Dẫn đường tới điểm đến cũ.
- Phát media cũ dù người dùng đã đổi ý.
- Vẫn commit hành động dù người dùng đã hủy.

Theo tinh thần τ-Voice / τ³-style voice benchmarking, backend không được chỉ đo transcript hoặc ASR. Backend phải đo được đồng thời:

1. **Task correctness**: tool và final state có đúng expected contract không.
2. **Full-duplex behavior**: assistant có đang nói khi user chen ngang không.
3. **Repair handling**: repair/cancel có được nhận và dùng để thay thế ý định cũ không.
4. **Commit safety**: tool call có xảy ra sau khi repair được xử lý không.
5. **Evidence validity**: episode có đủ observed evidence để tính performance không.

Repo hiện đã có nền tảng quan trọng:

```text
src/run_fdrc.py
src/evaluator/fdrc_evaluator.py
src/evaluator/fdrc_validity.py
src/orchestrator/full_duplex_orchestrator.py
src/dashboard/
```

Nhưng trạng thái hiện tại chưa đủ chuẩn để báo cáo production performance. Các run reference có thể pass 90/90 nhưng chỉ chứng minh evaluator/plumbing tự nhất quán. Provider realtime fail hoặc thiếu evidence phải được dùng để failure discovery, không được dùng trực tiếp làm performance report nếu validity chưa đạt.

---

## 2. Problem Statement

Backend hiện cần được nâng từ mức “script có thể chạy” thành **measurement instrument có validity contract đủ mạnh**.

Các vấn đề chính cần xử lý:

| Nhóm vấn đề | Hiện trạng | Rủi ro |
|---|---|---|
| Metric contract | Có thể còn dùng `pass_at_1` chung | Dễ báo cáo nhầm reference/synthetic pass là provider performance |
| Evidence contract | Provider run có thể thiếu observed events | Không chứng minh được full-duplex thật |
| Final state semantics | `committed_intent = tool` quá nghèo nghĩa | `state_match` có thể pass giả dù args/side-effect sai |
| Native vs client cancel | Dễ bị gộp chung | Không biết lỗi thuộc provider/model hay product cancellation layer |
| Transcript event naming | `user_transcript_done` và `repair_transcript_done` dễ lệch | Validity fail hoặc pass sai |
| Old metrics | Run cũ thiếu hash/validity/raw-performance split | Dashboard phải re-derive, dễ tạo denominator sai |
| Dataset distribution | 30 overlays nhưng domain không đều | Cần báo cáo domain-wise, không gộp mù |

Nguyên tắc điều hành:

```text
Nếu fdrc_validity_rate < 0.90:
    Không report performance_fdrc_pass_at_1.
    Chỉ report validity/debug metrics.
```

---

## 3. Benchmark Definition

### 3.1. Episode flow chuẩn

Một FDRC episode hợp lệ phải có flow tối thiểu:

```text
T0  User nói initial command.
T1  Assistant bắt đầu phản hồi hoặc xác nhận ý định ban đầu.
T2  User chen ngang khi assistant đang nói.
T3  Repair audio bắt đầu.
T4  Repair transcript hoàn tất.
T5  Assistant yield/stop ý định cũ trong ngưỡng latency.
T6  Tool commit chỉ được phép xảy ra sau repair đã được xử lý.
T7  Final state khớp ý định cuối cùng.
```

### 3.2. Pass condition

Episode chỉ được tính **FDRC pass** nếu đồng thời thỏa:

```text
task_pass == 1
AND policy_pass == 1
AND voice_pass == 1
AND final_pass == 1
AND fdrc_validity.valid == true
AND old_intent_committed == false
AND correction_uptaken == true, nếu final_intent không phải cancel
AND cancel_success == true, nếu final_intent là cancel
```

### 3.3. Invalid episode không phải model failure

Invalid episode là episode thiếu bằng chứng để chấm. Nó không nên bị tính là model fail trong official performance denominator.

```text
raw_fdrc_pass_at_1          = pass trên toàn bộ episodes, kể cả invalid, dùng forensic/debug.
fdrc_validity_rate          = valid_episode_count / total_episode_count.
performance_fdrc_pass_at_1  = pass trên valid episodes only.
```

---

## 4. Backend Architecture

### 4.1. Module layout đề xuất

```text
src/
  run_fdrc.py
  env.py
  io.py
  schema.py
  tick_scheduler.py

  orchestrator/
    full_duplex_orchestrator.py
    event_recorder.py
    audio_chunker.py
    provider_adapter.py
    openai_realtime_adapter.py
    client_cancel_controller.py

  tools/
    mock_tool_server.py
    tool_schema_registry.py
    state_mutator.py
    state_diff.py

  evaluator/
    common.py
    fdrc_evaluator.py
    fdrc_validity.py
    fdrc_contract.py
    voice_event_evaluator.py
    failure_taxonomy.py
    metric_contract.py

  data/
    overlays/
    personas/
    base_tasks/

  results/
    writer.py
    reader.py
    migrator.py
    inspector.py

  api/
    app.py
    routes_runs.py
    routes_episodes.py
    routes_compare.py
```

Backend nên có hai chế độ vận hành:

| Mode | Mục đích | Có realtime provider không |
|---|---|---:|
| `reference` | Validate evaluator, overlays, expected contract | Không |
| `provider` | Chạy agent/provider realtime surrogate | Có |

---

## 5. Data Contracts

### 5.1. Run metadata

Mọi run phải sinh `run_metadata.json`.

```json
{
  "run_id": "fdrc_smoke_automotive_native",
  "run_kind": "provider",
  "created_at": "2026-06-23T00:00:00+07:00",
  "benchmark": "full_duplex_repair_to_commit",
  "provider": "openai",
  "model": "gpt-realtime-mini",
  "adapter": "openai_realtime",
  "fdrc_yield_mode": "native_yield",
  "tick_ms": 200,
  "episode_set_hash": "sha256:...",
  "overlay_hash": "sha256:...",
  "persona_hash": "sha256:...",
  "domains": ["automotive"],
  "personas": ["vi_north_normal"],
  "audio_condition": "interaction_stress"
}
```

### 5.2. Overlay contract

Mỗi overlay FDRC cần mô tả rõ ý định ban đầu, repair, expected tool, forbidden tool và final state.

```json
{
  "overlay_id": "fdrc_auto_003",
  "mode": "full_duplex_repair_to_commit",
  "domain": "automotive",
  "risk_level": "side_effect_critical",
  "initial_utterance": "Đặt nhiệt độ ghế lái 22 độ.",
  "initial_intent": "set_driver_temperature_22",
  "repair_utterance": "Không, tăng lên 24 độ cơ.",
  "final_intent": "set_driver_temperature_24",
  "expected_tool_calls": [
    {
      "tool": "climate.set_temperature",
      "args": {
        "zone": "driver",
        "temperature_c": 24
      }
    }
  ],
  "forbidden_tool_calls": [
    {
      "tool": "climate.set_temperature",
      "args": {
        "zone": "driver",
        "temperature_c": 22
      }
    }
  ],
  "expected_final_state": {
    "fdrc": {
      "final_intent": "set_driver_temperature_24",
      "commit_status": "committed",
      "old_intent_committed": false
    },
    "vehicle_state": {
      "climate": {
        "driver_temperature_c": 24
      }
    }
  },
  "voice_assertions": {
    "max_yield_latency_ms": 700
  }
}
```

### 5.3. Cancel overlay

Cancel phải được biểu diễn như một final intent hợp lệ, không phải missing expected tool.

```json
{
  "overlay_id": "fdrc_phone_cancel_001",
  "domain": "media_phone",
  "initial_utterance": "Gọi cho mẹ.",
  "initial_intent": "call_mom",
  "repair_utterance": "Thôi hủy đi.",
  "final_intent": "cancel",
  "expected_tool_calls": [],
  "forbidden_tool_calls": [
    {
      "tool": "phone.call_contact",
      "args": {
        "contact": "Mẹ"
      }
    }
  ],
  "expected_final_state": {
    "fdrc": {
      "final_intent": "cancel",
      "commit_status": "cancelled",
      "committed_action": null,
      "old_intent_committed": false
    },
    "vehicle_state": {
      "unchanged": true
    }
  }
}
```

### 5.4. Episode contract

Mỗi row trong `episodes.jsonl` phải có đầy đủ các nhóm trường:

```json
{
  "episode_id": "auto_003_vi_north_normal",
  "run_id": "fdrc_smoke_automotive_native",
  "run_kind": "provider",
  "overlay_id": "fdrc_auto_003",
  "domain": "automotive",
  "persona": "vi_north_normal",
  "fdrc_yield_mode": "native_yield",
  "voice_events": [],
  "normalized_events": [],
  "tool_calls": [],
  "tool_results": [],
  "final_state": {},
  "scores": {},
  "repair": {},
  "latency": {},
  "failure_types": [],
  "primary_failure_type": null,
  "fdrc_validity": {}
}
```

---

## 6. Event Contract

### 6.1. `voice_events`

`voice_events` dùng cho timeline và assertion. Nó phải phân biệt `expected` và `observed`.

```json
{
  "event": "user_interrupt_start",
  "source": "observed",
  "t_ms": 3200,
  "tick": 16,
  "payload": {
    "speaker": "user"
  }
}
```

Required observed events cho provider episode:

```text
assistant_speech_start
user_interrupt_start
repair_audio_start
repair_transcript_done
assistant_yielded OR assistant_speech_stop
```

Nếu có expected tool call, cần thêm:

```text
tool_call with t_ms
tool_result with t_ms
final_state as dict
```

### 6.2. `normalized_events`

`normalized_events` dùng để giữ raw evidence từ orchestrator/provider/tool layer.

```json
{
  "type": "user_audio_chunk_sent",
  "t_ms": 3000,
  "chunk_id": "chunk_015",
  "duration_ms": 200
}
```

```json
{
  "type": "repair_transcript_done",
  "t_ms": 3900,
  "text": "Không, tăng lên 24 độ cơ."
}
```

```json
{
  "type": "tool_result",
  "t_ms": 4700,
  "tool": "climate.set_temperature",
  "call_id": "call_001",
  "ok": true
}
```

### 6.3. Naming normalization

Backend phải chuẩn hóa các tên event sau để tránh lệch evaluator:

| Raw event | Normalized semantic |
|---|---|
| `user_transcript_done` sau interrupt | `repair_transcript_done` |
| provider response stop | `assistant_speech_stop` |
| provider interrupted/cancelled | `assistant_yielded` |
| tool execution response | `tool_result` |

Validity nên accept cả `repair_transcript_done` và `user_transcript_done` sau `user_interrupt_start`, nhưng output chuẩn nên là `repair_transcript_done`.

---

## 7. Orchestrator Design

### 7.1. Tick scheduler

Giữ `tick_ms = 200` để đảm bảo comparability.

```text
1 tick = 200 ms
All timeline events are snapped to tick boundaries.
Observed provider events keep original t_ms if available, then derive nearest tick.
```

### 7.2. Full-duplex orchestration loop

Pseudo-flow:

```python
def run_fdrc_episode(overlay, persona, provider, yield_mode):
    recorder = EventRecorder(tick_ms=200)
    tool_server = MockToolServer(initial_state=overlay.initial_state)

    # 1. Send initial user audio.
    recorder.emit_expected_timeline(overlay.voice_timeline)
    stream_user_audio(overlay.initial_utterance, persona)

    # 2. Wait for assistant speech start.
    recorder.observe("assistant_speech_start", provider.now_ms())

    # 3. Inject repair while assistant is speaking.
    wait_until(overlay.interrupt_at_ms)
    recorder.observe("user_interrupt_start", now_ms())
    recorder.observe("repair_audio_start", now_ms())
    stream_user_audio(overlay.repair_utterance, persona)

    # 4. Native or client-side yield mode.
    if yield_mode == "client_cancel_yield":
        provider.cancel_response()
        recorder.observe("assistant_yielded", now_ms(), reason="client_cancel")

    # 5. Capture transcript, tool calls, tool results.
    collect_provider_events(provider, recorder, tool_server)

    # 6. Build episode artifact.
    return build_episode(recorder, tool_server.final_state())
```

### 7.3. Yield modes

Hai mode phải chạy và báo cáo riêng.

| Mode | Định nghĩa | Dùng để kết luận |
|---|---|---|
| `native_yield` | Provider/model tự yield khi user chen ngang | Khả năng full-duplex intrinsic của provider/model |
| `client_cancel_yield` | Product stack chủ động cancel response | Khả năng mitigation của product layer |

Không cộng chung hai mode. Nếu `native_yield` fail nhưng `client_cancel_yield` pass, kết luận đúng là provider chưa yield tốt tự nhiên nhưng product cancellation có thể giảm side-effect risk.

---

## 8. Tool Server và Final State

### 8.1. Không dùng final state nghèo nghĩa

Không dùng:

```json
{
  "committed_intent": "climate.set_temperature"
}
```

Vì nó không phân biệt được tool đúng nhưng args sai.

### 8.2. Final state chuẩn cho committed action

```json
{
  "fdrc": {
    "overlay_id": "fdrc_auto_003",
    "initial_intent": "set_driver_temperature_22",
    "final_intent": "set_driver_temperature_24",
    "commit_status": "committed",
    "committed_action": {
      "tool": "climate.set_temperature",
      "args": {
        "zone": "driver",
        "temperature_c": 24
      },
      "t_ms": 4700
    },
    "old_intent_committed": false,
    "commit_after_repair": true
  },
  "vehicle_state": {
    "climate": {
      "driver_temperature_c": 24
    }
  }
}
```

### 8.3. Final state chuẩn cho cancel

```json
{
  "fdrc": {
    "overlay_id": "fdrc_phone_cancel_001",
    "initial_intent": "call_mom",
    "final_intent": "cancel",
    "commit_status": "cancelled",
    "committed_action": null,
    "old_intent_committed": false
  },
  "vehicle_state": {
    "unchanged": true
  }
}
```

### 8.4. State diff

Backend nên sinh thêm `state_diff` để frontend không phải tự tính toàn bộ.

```json
{
  "state_diff": {
    "matches": false,
    "diffs": [
      {
        "path": "vehicle_state.climate.driver_temperature_c",
        "expected": 24,
        "observed": 22,
        "severity": "critical"
      }
    ]
  }
}
```

---

## 9. Evaluator Design

### 9.1. Validity evaluator

Validity phải chạy trước performance summarization.

Invalid reasons chuẩn:

```text
INVALID_AUDIO
INVALID_EVIDENCE
INVALID_TRANSCRIPT
INVALID_TOOL_RESULT
INVALID_FINAL_STATE
```

Validity pseudo-logic:

```python
def classify_fdrc_validity(episode, overlay):
    if is_reference_episode(episode):
        return VALID

    reasons = []

    if missing_required_observed_events(episode):
        reasons.append("INVALID_EVIDENCE")

    if no_user_audio_chunk_sent(episode):
        reasons.append("INVALID_AUDIO")

    if repair_transcript_does_not_match_expected(episode, overlay):
        reasons.append("INVALID_TRANSCRIPT")

    if tool_calls_exist_but_tool_results_missing(episode):
        reasons.append("INVALID_TOOL_RESULT")

    if final_state_is_not_dict(episode):
        reasons.append("INVALID_FINAL_STATE")

    return valid_if_no_reasons(reasons)
```

### 9.2. FDRC evaluator

Evaluator phải tính các nhóm rule sau:

| Rule group | Check |
|---|---|
| Tool correctness | Expected tool calls có xuất hiện không |
| Argument correctness | Args có exact/deep match không |
| Forbidden tool | Old intent tool/args có bị gọi không |
| Correction uptake | Final intent có được dùng không |
| Cancel respect | Cancel thì không được có tool side-effect |
| Yield latency | Assistant yield/stop trong threshold |
| Early commit | Tool call không được trước repair processed |
| Duplicate commit | Không commit repeated final action |
| State match | Final state đúng expected state |
| Observability | Required observed evidence đầy đủ |

### 9.3. Failure taxonomy

Chuẩn hóa primary failure để dashboard aggregate được.

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

Nguyên tắc:

```text
Invalidity failures describe measurement quality.
Performance failures describe model/product behavior.
Do not mix them in one denominator.
```

---

## 10. Metrics Contract

### 10.1. Metrics output

`metrics.json` phải có tối thiểu:

```json
{
  "total_episode_count": 8,
  "valid_episode_count": 7,
  "invalid_episode_count": 1,
  "fdrc_validity_rate": 0.875,
  "validity_failure_counts": [
    {"key": "INVALID_EVIDENCE", "count": 1}
  ],
  "raw_fdrc_pass_at_1": 0.125,
  "performance_fdrc_pass_at_1": null,
  "correction_uptake_rate": 0.5,
  "old_intent_suppression_rate": 0.75,
  "forbidden_tool_call_rate": 0.25,
  "cancel_success_rate": 1.0,
  "performance_yield_latency_p50_ms": null,
  "performance_yield_latency_p95_ms": null,
  "performance_yield_latency_pass_rate": null,
  "reportability_status": "VALIDITY_ONLY"
}
```

### 10.2. Reportability status

```text
NOT_REPORTABLE:
    fdrc_validity_rate < 0.70 or metadata/hash missing

VALIDITY_ONLY:
    0.70 <= fdrc_validity_rate < 0.90

REPORTABLE_DOMAIN:
    fdrc_validity_rate >= 0.90 for a domain-level run

REPORTABLE_FULL_MATRIX:
    fdrc_validity_rate >= 0.90 for all domains/personas in full matrix
```

### 10.3. Denominator policy

```text
raw_* metrics:
    denominator = all episodes

performance_* metrics:
    denominator = valid episodes only

validity_* metrics:
    denominator = all episodes
```

---

## 11. Runner Plan

### 11.1. Current runner interface

Giữ interface hiện có:

```powershell
.\.venv\Scripts\python.exe run_fdrc.py --reference-agent --output results\fdrc_reference_check
```

```powershell
.\.venv\Scripts\python.exe run_fdrc.py --agent openai_realtime --model gpt-realtime-mini --domains automotive --personas vi_north_normal --fdrc-yield-mode native_yield --output results\fdrc_smoke_automotive_native
```

```powershell
.\.venv\Scripts\python.exe run_fdrc.py --agent openai_realtime --model gpt-realtime-mini --domains automotive --personas vi_north_normal --fdrc-yield-mode client_cancel_yield --output results\fdrc_smoke_automotive_client_cancel
```

### 11.2. Run tiers

| Tier | Purpose | Scope | Performance report |
|---|---|---:|---|
| Tier 0 Reference | Check evaluator/dashboard contract | 30 overlays x 3 personas = 90 episodes | No |
| Tier 1 Provider Smoke | Check realtime audio, timeline, tool path, validity | 1 domain x `vi_north_normal` | Validity only |
| Tier 2 Provider Domain | Score one domain at a time | Domain overlays x selected personas | Yes, if validity sufficient |
| Tier 3 Provider Full Matrix | Official provider surrogate report | 30 overlays x 9 personas = 270 episodes | Yes |

### 11.3. Full matrix command

```powershell
.\.venv\Scripts\python.exe run_fdrc.py `
  --agent openai_realtime `
  --model gpt-realtime-mini `
  --domains automotive,navigation,media_phone `
  --personas vi_north_slow,vi_north_normal,vi_north_fast,vi_central_slow,vi_central_normal,vi_central_fast,vi_south_slow,vi_south_normal,vi_south_fast `
  --fdrc-yield-mode native_yield `
  --output results\fdrc_full_provider_native
```

---

## 12. Backend API for Frontend

Frontend có thể đọc static JSON trong MVP. Nếu cần backend API, dùng FastAPI.

### 12.1. Endpoints

```text
GET /api/runs
GET /api/runs/{run_id}
GET /api/runs/{run_id}/metrics
GET /api/runs/{run_id}/episodes
GET /api/runs/{run_id}/episodes/{episode_id}
GET /api/runs/{run_id}/failure-summary
GET /api/runs/{run_id}/domain-persona-matrix
GET /api/compare?run_a=...&run_b=...
```

### 12.2. Episode query params

```text
domain
persona
yield_mode
validity_status
final_pass
primary_failure_type
initial_intent
final_intent
risk_level
limit
offset
sort_by
```

### 12.3. API response shape

```json
{
  "items": [],
  "total": 270,
  "filters": {
    "domain": "automotive",
    "validity_status": "VALID"
  },
  "run_metadata": {},
  "metrics": {}
}
```

---

## 13. Storage Plan

### 13.1. MVP static storage

```text
results/
  fdrc_smoke_automotive_native/
    run_metadata.json
    metrics.json
    episodes.jsonl
    artifacts/
      audio/
      transcripts/
      raw_provider_events/
```

### 13.2. Scalable storage later

Khi số run tăng, dùng SQLite/Postgres cho index và vẫn giữ raw artifact trên filesystem/object storage.

```text
runs table
episodes table
events table
tool_calls table
state_diffs table
metrics table
```

Không cần database phức tạp cho MVP 270 episodes, nhưng cần metadata/hash chuẩn ngay từ đầu.

---

## 14. Data Quality Gates

### 14.1. Preflight validation

Trước khi chạy:

```text
Overlay schema valid.
Expected tool exists in registry.
Forbidden tool exists in registry.
Expected final_state is dict.
Persona exists.
Domain exists.
voice_assertions.max_yield_latency_ms exists.
```

### 14.2. Post-run validation

Sau khi chạy:

```text
Every episode has run_id, overlay_id, domain, persona.
Every provider episode has voice_events and normalized_events.
Every tool_call has t_ms.
Every tool_result has t_ms.
Every episode has fdrc_validity.
Every metrics file has raw/performance/validity split.
```

### 14.3. Encoding audit

Tất cả artifact phải là UTF-8.

```text
Markdown docs
JSON/JSONL
Dashboard static text
Overlay data
Persona yaml/json
```

Cần guardrail chống mojibake vì dashboard/demo mất độ tin cậy nếu tiếng Việt lỗi mã hóa.

---

## 15. Implementation Roadmap

### Phase 0 — Contract Cleanup

Mục tiêu: chuẩn hóa backend contract.

Tasks:

1. Chuẩn hóa docs sang `src/`, đánh dấu legacy nếu có.
2. Bổ sung `run_metadata.json` và hash fields.
3. Sửa final state semantic trong `MockToolServer` và overlays.
4. Bổ sung `state_diff` output.
5. Re-evaluate run cũ, đánh dấu `legacy_metrics` nếu thiếu validity.

Exit criteria:

```text
Reference FDRC vẫn 90/90 pass.
Mọi metrics có fdrc_validity_rate, raw_fdrc_pass_at_1, performance_fdrc_pass_at_1.
Mọi episode có run metadata và fdrc_validity.
```

### Phase 1 — Evidence Validity

Mục tiêu: provider run có đủ observed evidence.

Tasks:

1. Orchestrator log observed `assistant_speech_start`.
2. Log `user_interrupt_start`, `repair_audio_start`, `repair_transcript_done`.
3. Log `assistant_yielded` hoặc `assistant_speech_stop`.
4. Log audio chunk sent events.
5. Log tool_call/tool_result timestamp.
6. Fix transcript naming normalization.

Exit criteria:

```text
Automotive smoke validity >= 0.90.
INVALID_EVIDENCE và INVALID_AUDIO không còn dominant.
```

### Phase 2 — Failure Isolation

Mục tiêu: mỗi fail episode có root cause.

Tasks:

1. Chuẩn hóa failure taxonomy.
2. Gắn `primary_failure_type` deterministic.
3. Tách invalidity failures khỏi performance failures.
4. Sinh failure summary domain-wise/persona-wise.

Exit criteria:

```text
>= 95% failed/invalid episodes có primary_failure_type.
Dashboard có thể filter theo failure type.
```

### Phase 3 — Product Stack Evaluation

Mục tiêu: tách native yield và client cancel.

Tasks:

1. Chạy automotive native yield.
2. Chạy automotive client cancel yield.
3. So sánh run A/B.
4. Mở navigation và media_phone sau khi automotive ổn.

Exit criteria:

```text
Biết lỗi thuộc provider/model hay product cancellation stack.
Không publish metric gộp native + client_cancel.
```

### Phase 4 — Full Matrix

Mục tiêu: chạy official 270 episodes.

Tasks:

1. Chạy 30 overlays x 9 personas.
2. Báo cáo domain-wise và persona-wise.
3. Freeze report template.
4. Lưu artifact đầy đủ cho forensic replay.

Exit criteria:

```text
All domains validity >= 0.90.
Full matrix metrics reproducible by run_id + episode_set_hash.
```

---

## 16. Acceptance Criteria

Backend đạt chuẩn khi:

1. Reference run pass nhưng được gắn nhãn rõ là plumbing-only.
2. Provider run không report performance nếu validity thấp.
3. Episode nào cũng có timeline evidence đủ để frontend replay.
4. Final state biểu diễn đúng side-effect, không chỉ tên tool.
5. Native yield và client cancel yield được tách riêng.
6. Mỗi invalid/fail episode có reason/root cause rõ.
7. Full matrix 270 episodes có thể tái lập bằng hash.
8. Dashboard không phải tự suy luận các metric lõi từ raw events.

---

## 17. Non-Goals

Không làm trong backend MVP:

1. Real-time monitoring UI server.
2. Multi-provider leaderboard production-grade.
3. Persona mô phỏng tuổi/giới/nghề quá chi tiết.
4. Audio quality MOS/naturalness scoring.
5. ASR benchmark độc lập.
6. Database phức tạp khi static JSONL đủ cho 270 episodes.

---

## 18. Final Recommendation

Backend FDRC phải được xây theo hướng:

```text
validity-gated
state-semantic
evidence-first
failure-taxonomy-driven
native/client-cancel separated
```

Thứ tự ưu tiên đúng:

```text
1. Sửa semantic final state.
2. Chuẩn hóa observed event contract.
3. Bổ sung run metadata/hash.
4. Tách raw/valid/performance metrics.
5. Chạy reference 90/90.
6. Chạy provider smoke validity.
7. Tách failure root cause.
8. Mở domain expansion.
9. Chạy full matrix 270 episodes.
```

Khi backend đạt các điều kiện trên, FDRC mới trở thành một measurement instrument đủ tin cậy để báo cáo production-readiness cho Vivi-style full-duplex in-car assistant.
