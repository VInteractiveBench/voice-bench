# Luồng Hoạt Động Benchmark Và Evaluation

## Context

Repository này triển khai **Vivi-τVoice-CarBench-VN**, một benchmark tương tác giọng nói tiếng Việt trong bối cảnh ô tô. Hệ thống tách rõ hai miền trách nhiệm: tầng sinh hoặc tiếp nhận episode log và tầng evaluation tất định. Thiết kế này giúp giảm nhiễu đo lường từ hạ tầng agent, đồng thời giữ evaluator đủ độc lập để chấm log từ Vivi thật, surrogate OpenAI, hoặc `reference-agent`.

| Thành phần | File chính | Vai trò |
|---|---|---|
| Text baseline runner | `run_text_baseline.py` | Chấm retention task ở chế độ text để tạo năng lực nền. |
| Voice retention runner | `run_voice_retention.py` | Chấm cùng task retention trong điều kiện voice sạch và voice cabin. |
| Full-duplex runner | `run_fdrc.py` | Chấm khả năng bị ngắt lời, sửa hoặc hủy ý định, và chỉ commit ý định cuối. |
| Runner core | `speech_interaction/runner.py` | Chọn overlay, tạo hoặc đọc episode, validate schema, gọi evaluator, ghi kết quả. |
| Agent orchestrator | `speech_interaction/orchestrator/full_duplex_orchestrator.py` | Chạy agent thật qua adapter, gửi text/audio/timeline, nhận tool call, thực thi tool mock. |
| Retention evaluator | `speech_interaction/evaluator/retention_evaluator.py` | Chấm tool, state, policy, critical spoken slots, retention metrics. |
| FDRC evaluator | `speech_interaction/evaluator/fdrc_evaluator.py` | Chấm correction uptake, old-intent suppression, yield latency, commit timing. |
| Report generator | `generate_voice_report.py` | Gộp kết quả retention và FDRC thành báo cáo tổng hợp. |

## Problem Statement

Benchmark cần trả lời ba câu hỏi kỹ thuật, không chỉ đo transcript hoặc ASR:

1. Agent có giữ được năng lực task-grounded khi chuyển từ text sang voice hay không.
2. Agent có chịu tác động tiêu cực bởi cabin noise, accent region, speech speed, và điều kiện tương tác căng thẳng hay không.
3. Agent có xử lý full-duplex đúng policy, tức là nhường lời khi bị ngắt, tiếp nhận repair utterance, không commit ý định cũ, và chỉ commit ý định cuối hay không.

## Technical Deep-Dive

### Luồng Tổng Quan

```mermaid
flowchart TD
    A[Benchmark CLI] --> B{Runner}
    B --> B1[run_text_baseline.py]
    B --> B2[run_voice_retention.py]
    B --> B3[run_fdrc.py]

    B1 --> C[load_benchmark_env]
    B2 --> C
    B3 --> C

    C --> D[load_base_tasks]
    C --> E[load_overlays]
    D --> F[preflight_validate_assets]
    E --> F
    F --> G[select_overlays by track and domain]

    G --> H{Episode source}
    H -->|--episode-logs| I[read JSONL episode logs]
    H -->|--reference-agent| J[build deterministic oracle episodes]
    H -->|--agent| K[run OpenAI-as-Vivi surrogate]

    I --> L[evaluate_episodes]
    J --> L
    K --> L

    L --> M{Evaluator}
    M --> N[evaluate_retention_episode]
    M --> O[evaluate_fdrc_episode]

    N --> P[merge_existing_episodes]
    O --> P
    P --> Q[save_results]
    Q --> R[episodes.jsonl]
    Q --> S[metrics.json]
```

### Luồng Dữ Liệu Benchmark

```mermaid
flowchart LR
    A[data/domains/*/tasks.json] --> D[Base logical tasks]
    B[data/domains/*/policy.md] --> D
    C[data/domains/*/db.json] --> D

    D --> E[speech_interaction/base_task_manifest.json]
    E --> F[speech_interaction/speech_task_overlays.jsonl]

    G[speech_interaction/personas/*.yaml] --> H[Persona dimensions]
    I[speech_interaction/audio_conditions/*.yaml] --> J[Audio conditions]
    K[speech_interaction/full_duplex_timelines/*.json] --> L[FDRC timelines]

    F --> M[Episode construction]
    H --> M
    J --> M
    L --> M

    M --> N[Episode log contract]
    N --> O[Evaluator]
```

| Artifact | Semantic ownership | Evaluation impact |
|---|---|---|
| `tasks.json` | Logical user goal, initial state, expected tool trajectory, expected final state. | Determines task correctness, state match, and expected tool calls. |
| `policy.md` | Domain policy boundary. | Policy violations reduce `policy_pass` and `final_pass`. |
| `db.json` | Domain state fixture. | Used through task/tool execution semantics and final state comparison. |
| `base_task_manifest.json` | Normalized index over selected benchmark tasks. | Binds speech overlays to canonical logical tasks. |
| `speech_task_overlays.jsonl` | Speech utterance, critical slots, audio mode, repair intent, forbidden/expected calls. | Supplies voice assertions and overlay-specific expected outcomes. |
| `audio_conditions/*.yaml` | Clean, cabin noise, interaction stress. | Controls audio generation/mixing for realtime surrogate runs. |
| `full_duplex_timelines/*.json` | Timestamped interaction events. | Enables deterministic yield and commit-timing evaluation. |

### Luồng Text-to-Voice Capability Retention

```mermaid
flowchart TD
    A[run_text_baseline.py or run_voice_retention.py] --> B[Select text_to_voice_retention overlays]
    B --> C{Mode set}
    C -->|Text baseline| D[text_baseline + vi_north_normal]
    C -->|Voice retention| E[clean_voice + realistic_cabin_voice]
    E --> F[Personas: north, central, south; normal by default]

    D --> G{Episode source}
    F --> G
    G -->|Existing log| H[load_or_build_episodes reads JSONL]
    G -->|Reference oracle| I[reference_episode]
    G -->|Surrogate agent| J[run_agent_episodes]

    H --> K[evaluate_episodes]
    I --> K
    J --> K

    K --> L[evaluate_retention_episode]
    L --> M[evaluate_common]
    M --> M1[Tool exact match]
    M --> M2[Argument exact match]
    M --> M3[Final state subset match]
    M --> M4[Policy and tool-schema validation]
    M --> M5[Tool execution success]

    L --> N[evaluate_critical_slots]
    N --> O[summarize_retention]
    O --> P[text_pass_at_1]
    O --> Q[clean_voice_retention]
    O --> R[voice_capability_retention]
    O --> S[voice_degradation_gap]
    O --> T[critical_slot_accuracy]
    O --> U[accent_gap and speed_gap]
```

Retention không chỉ so sánh transcript. Episode chỉ pass khi tool selection, argument, final state, policy behavior, execution result, assistant communication, và critical spoken slots cùng đạt. Vì vậy, `voice_capability_retention = cabin_voice_pass_at_1 / text_pass_at_1` đo mức bảo toàn năng lực task-grounded trong điều kiện cabin thực tế, thay vì đo độ giống văn bản bề mặt.

### Luồng Full-Duplex Repair-to-Commit

```mermaid
sequenceDiagram
    participant CLI as run_fdrc.py
    participant Runner as speech_interaction.runner
    participant Scheduler as tick_scheduler
    participant Agent as Vivi/OpenAI Realtime Adapter
    participant Tools as MockToolServer
    participant Eval as evaluate_fdrc_episode

    CLI->>Runner: load tasks and full_duplex_repair_to_commit overlays
    Runner->>Scheduler: schedule_timeline(tick_ms=200)
    Runner->>Agent: start_session(system_prompt, tool_schemas)
    Runner->>Agent: send initial utterance/audio
    Agent-->>Runner: assistant speech/transcript/tool events
    Runner->>Agent: send repair utterance during overlap
    Agent-->>Runner: assistant_yielded or assistant_speech_stop evidence
    Agent-->>Runner: tool_call with t_ms
    Runner->>Tools: execute tool call against task and overlay state
    Tools-->>Runner: tool_result and final_state update
    Runner->>Eval: episode log with voice_events, tool_calls, final_state
    Eval-->>Runner: scores, repair fields, failure_types
    Runner->>CLI: episodes.jsonl and metrics.json
```

```mermaid
flowchart TD
    A[evaluate_fdrc_episode] --> B[Clone task and override expected_final_state from overlay]
    B --> C[evaluate_common with overlay expected_tool_calls]
    C --> D[Detect forbidden_tool_calls]
    C --> E[Check expected final calls were made]
    C --> F[evaluate_yield against max_yield_latency_ms]
    C --> G[Check assistant speaking before interrupt]
    C --> H[Check early commit before tool_commit_allowed_after]
    C --> I[Check duplicate final commit]
    C --> J[Check assistant_continued_old_confirmation]

    D --> K[Failure taxonomy]
    E --> K
    F --> K
    G --> K
    H --> K
    I --> K
    J --> K

    K --> L[repair object]
    K --> M[latency.yield_latency_ms]
    K --> N[scores.voice_pass]
    K --> O[scores.final_pass]
    O --> P[summarize_fdrc]
```

| FDRC criterion | Signal source | Failure type when violated |
|---|---|---|
| Agent nhường lời khi bị ngắt | `voice_events`, `assistant_yielded`, `yield_latency_ms` | `YIELD_LATENCY_TOO_HIGH` |
| Ý định sửa được tiếp nhận | Expected final tool calls in overlay versus actual `tool_calls` | `CORRECTION_NOT_UPTAKEN` |
| Ý định cũ không bị commit | `forbidden_tool_calls` versus actual `tool_calls` | `FORBIDDEN_TOOL_CALL`, `OLD_INTENT_COMMITTED` |
| Lệnh hủy được tôn trọng | Overlay `final_intent == cancel` and no actual commit | `CANCEL_NOT_RESPECTED` |
| Không commit quá sớm | `tool_commit_allowed_after` versus tool `t_ms` | `POLICY_VIOLATION` |
| Không xác nhận ý định cũ sau repair | `assistant_continued_old_confirmation` event | `POLICY_VIOLATION` |

### Luồng Chạy Agent Surrogate

```mermaid
flowchart TD
    A[run_agent_episodes] --> B[run_agent_episode]
    B --> C[build_adapter]
    C --> C1[OpenAITextViviAdapter]
    C --> C2[OpenAIRealtimeViviAdapter]

    B --> D[get_openai_tool_schemas]
    B --> E[get_domain_tools]
    B --> F[build_system_prompt]
    B --> G[MockToolServer]

    C1 --> H{Input mode}
    C2 --> H
    H -->|text_baseline| I[send_text spoken_utterance]
    H -->|clean/cabin voice| J[AudioCache get_or_build TTS and noise-mixed audio]
    H -->|full-duplex realtime| K[send initial audio, wait interrupt_ms, send repair audio]

    I --> L[receive_events]
    J --> L
    K --> L

    L --> M{Event type}
    M -->|assistant transcript| N[assistant_transcript append]
    M -->|tool_call| O[MockToolServer.execute]
    O --> P[send_tool_result]
    M -->|speech/audio events| Q[normalized_events append]
    M -->|session_error| R[failure_types append]

    N --> S[Episode JSON object]
    P --> S
    Q --> S
    R --> S
```

Surrogate agent không được xem là ground truth. Nó chỉ là adapter để tạo episode log theo cùng contract với Vivi thật. Điểm đáng chú ý về reliability là mọi tool call đều đi qua `MockToolServer`, sau đó evaluator vẫn re-validate tool scope, schema, final state, critical slots, và voice behavior; nhờ vậy lỗi agent không bị che bởi tool execution layer.

### Luồng Evaluation Chung

```mermaid
flowchart TD
    A[evaluate_episodes] --> B[Map overlay by speech_overlay_id]
    A --> C[Map task by base_task_id]
    B --> D{Overlay and task exist?}
    C --> D
    D -->|No| E[invalid_episode_result]
    D -->|Yes| F[validate_episode_log]
    F --> G{Schema errors?}
    G -->|Yes| E
    G -->|No| H[Track-specific evaluator]

    H --> I[evaluate_common]
    I --> J[validate_tool_scope]
    I --> K[validate_tool_schema]
    I --> L[tool_call_matches]
    I --> M[deep_subset expected_final_state]
    I --> N[execution_success from tool_results]
    I --> O[communication_present]
    I --> P[Failure taxonomy and scores]

    P --> Q[Track-specific assertions]
    Q --> R[final evaluated episode]
```

| Score field | Computation principle | Product interpretation |
|---|---|---|
| `task_pass` | Exact expected tool trajectory, argument subset match, final state match, and successful tool results. | Agent completed the requested in-car action correctly. |
| `policy_pass` | No policy violations and no tool-schema validation errors. | Agent stayed inside official Vivi behavior and tool interface constraints. |
| `voice_pass` | Track-specific voice behavior; always 1 in common evaluator, then overridden by retention/FDRC logic when needed. | Agent preserved speech-critical semantics or full-duplex interaction correctness. |
| `final_pass` | All task, policy, voice, and failure taxonomy checks pass. | Episode is reportable as successful benchmark behavior. |

### Luồng Report Tổng Hợp

```mermaid
flowchart LR
    A[results/text_baseline/episodes.jsonl] --> D[generate_voice_report.py]
    B[results/voice_retention/episodes.jsonl] --> D
    C[results/fdrc/episodes.jsonl] --> D

    D --> E[summarize_retention]
    D --> F[summarize_fdrc]
    E --> G[generate_report]
    F --> G
    G --> H[speech_interaction/reports/vivi_voice_report.md]
    G --> I[speech_interaction/reports/vivi_voice_failures.csv]
```

## Strategic Recommendations

| Concern | Current design | Recommendation |
|---|---|---|
| Scalability | Runner loops are deterministic and simple, but agent episodes are executed sequentially. | Parallelize at `(overlay, mode, persona)` granularity only after introducing explicit rate-limit controls, output de-duplication, and deterministic retry metadata. |
| Reliability | Evaluation is decoupled from generation and validates schema before scoring. | Preserve JSONL episode contract as the stable boundary; any future Vivi adapter should only replace `ViviAgentAdapter`, not evaluator semantics. |
| Latency | FDRC uses fixed 200 ms ticks and logs `t_ms` on tool calls and voice events. | Keep tick granularity fixed for comparability; report wall-clock latency separately from benchmark timing if realtime API jitter becomes material. |
| Cost-to-serve | `reference-agent` validates plumbing without paid model calls; OpenAI surrogate requires API calls and TTS/audio cache. | Use `reference-agent` in CI, reserve `--agent openai_realtime` for smoke/regression runs, and evaluate production Vivi logs offline whenever available. |
| Evaluation validity | `final_pass` is strict and failure taxonomy is explicit. | Avoid reporting ASR-style metrics as primary KPIs; keep task correctness, tool safety, and repair-to-commit behavior as the benchmark’s authoritative product metrics. |

