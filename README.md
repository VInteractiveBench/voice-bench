# Vivi Voice CarBench VN

## Bối Cảnh

`Vivi Voice CarBench VN` là benchmark tương tác giọng nói tiếng Việt trong bối cảnh ô tô, dùng để đánh giá trợ lý Vivi trên các tác vụ có side effect như điều hòa, ghế, cửa sổ, đèn, điều hướng, media và gọi điện. Dự án mở rộng từ nền tảng `tau2`/`VInteractiveBench`, nhưng bề mặt benchmark chính hiện nằm trong `speech_interaction/`.

Benchmark này không chỉ đo ASR, không chỉ đo chatbot, và không chỉ đo tool-calling bằng text. Một episode chỉ được tính pass khi tool trajectory, tool arguments, final state, policy behavior, critical slots, communication và voice evidence đều đúng theo contract.

## Vấn Đề Cần Đo

Trợ lý trong xe có hai nhóm lỗi mà text benchmark thông thường khó phát hiện đầy đủ:

| Nhóm rủi ro | Vì sao cần benchmark riêng |
|---|---|
| Mất năng lực khi chuyển từ text sang voice | Cùng một task có thể pass bằng text nhưng fail khi đi qua audio, accent, speech speed hoặc cabin noise. |
| Commit sai khi hội thoại bị chen ngang | Assistant có thể đã nghe lệnh sửa/hủy nhưng vẫn gọi tool theo ý định cũ, commit quá sớm, hoặc không yield khi user ngắt lời. |

Dự án tập trung vào hai benchmark:

| Benchmark | Câu hỏi đo lường |
|---|---|
| Policy-Grounded Voice Command Gating | Khi user ra lệnh bằng giọng nói, Vivi có chọn đúng execute/clarify/refuse/defer theo policy và trạng thái xe không? |
| Full-Duplex Repair-to-Commit | Khi user chen ngang để sửa hoặc hủy, Vivi có dừng lại, bỏ ý định cũ, và chỉ commit ý định cuối cùng đúng thời điểm không? |

<img width="3349" height="1984" alt="mermaid-diagram-2026-06-26-120112" src="https://github.com/user-attachments/assets/cf8a4b22-6f4a-4e44-84f9-e881e2d5e6f9" />

Tài liệu chi tiết:

- [Benchmark 1: Full-Duplex Repair-to-Commit](docs/benchmark_1_full_duplex_repair_to_commit.md)
- [Benchmark 2: Policy-Grounded Voice Command Gating](docs/benchmark_2_policy_grounded_voice_command_gating.md)
- [Dashboard usage](docs/dashboard_usage.md)
- [Benchmark overview](docs/benchmark/tong-quan-benchmark.md)

## Phạm Vi MVP

| Dimension | Phạm vi hiện tại |
|---|---|
| Domains | `automotive`, `navigation`, `media_phone` |
| Base tasks | FDRC base tasks + ~16 policy-gating base tasks |
| Speech overlays | 30 FDRC + ~24 policy-gating overlays |
| Official Vivi tools | 25 tools trong registry |
| MVP in-scope tools | 19 tools, loại 6 information/search tools |
| Personas | 9 personas: north/central/south x slow/normal/fast |
| Audio conditions | `clean`, `cabin_noise`, `interaction_stress` |
| Full-duplex scheduler | deterministic tick `200 ms` |
| Primary runner surface | `src/`, `run_policy_gating.py`, `run_fdrc.py` |

Sáu official tools nằm ngoài MVP là `weather`, `news_search`, `web_search`, `vinfast_kb`, `vehicle_troubleshoot`, `software_release`. Gọi các tool này được phân loại là `OUT_OF_SCOPE_TOOL_CALL`; gọi tool bịa ngoài whitelist được phân loại là `TOOL_NOT_IN_WHITELIST`.

## Sơ Đồ Repository

| Path | Vai trò |
|---|---|
| `speech_interaction/` | Benchmark surface chính: assets, schemas, adapters, evaluator, audio pipeline, dashboard. |
| `speech_interaction/base_task_manifest.json` | Manifest 30 logical tasks, tham chiếu domain task source. |
| `speech_interaction/speech_task_overlays.jsonl` | 60 speech overlays: utterance, persona/audio condition, critical slots, FDRC timeline. |
| `speech_interaction/evaluator/` | Deterministic evaluators cho policy gating, FDRC, tool schema, tool scope, critical slots, voice events. |
| `speech_interaction/orchestrator/` | Runtime orchestration: provider adapter, audio streaming, tool server, event normalization. |
| `speech_interaction/audio/` | TTS, audio cache, PCM conversion, noise mixing. |
| `speech_interaction/tools/` | Canonical Vivi tool registry, schema và mock tool server. |
| `speech_interaction/dashboard/` | Local dashboard để xem runs, metrics, failures và episode details. |
| `scripts/` | Asset generation, cabin noise segmentation, provider smoke scripts. |
| `docs/` | Product/benchmark documentation và dashboard guide. |
| `src/tau2/` | Upstream tau2 infrastructure, domain/evaluator/orchestrator legacy. |
| `src/tau2_voice/` | Legacy voice/realtime experiments; không phải benchmark surface chính. |
| `results/` | Output của các lần chạy: `episodes.jsonl`, `metrics.json`, report artifacts. |

## Benchmark 1: Full-Duplex Repair-to-Commit

FDRC tạo tình huống user nói một lệnh ban đầu, assistant bắt đầu phản hồi, sau đó user chen ngang để sửa hoặc hủy. Benchmark kiểm tra Vivi có dừng đúng lúc, bỏ ý định cũ và chỉ commit ý định cuối cùng hay không.

Ví dụ repair scenario:

```text
User initial: "Dẫn đường đến nhà hàng A."
Assistant: bắt đầu confirm hoặc xử lý.
User interrupt: "À không, đến nhà hàng B."
Expected: không commit route A, chỉ commit route B sau mốc được phép.
```

Ví dụ cancel scenario:

```text
User initial: "Gọi cho Minh."
Assistant: bắt đầu confirm.
User interrupt: "Thôi hủy đi."
Expected: không có tool call tạo cuộc gọi.
```

### FDRC Evidence Bắt Buộc

| Field/Event | Ý nghĩa |
|---|---|
| `assistant_speech_start` | Assistant thực sự đang nói trước khi user interrupt. |
| `user_interrupt_start` | Mốc user bắt đầu chen ngang. |
| `assistant_yielded` | Mốc assistant dừng/yield sau interrupt. |
| `assistant_should_yield_by` | Deadline yield theo overlay. |
| `tool_commit_allowed_after` | Mốc sớm nhất được phép commit side effect. |
| Tool call `t_ms` | Timestamp dùng để phát hiện early commit. |
| `expected_tool_calls` | Final intent phải được commit. |
| `forbidden_tool_calls` | Old intent tuyệt đối không được commit. |
| `final_intent` | Final user intent sau repair, có thể là `cancel`. |

### FDRC Metrics

| Metric | Ý nghĩa |
|---|---|
| `fdrc_pass_at_1` | Episode pass toàn bộ task, policy, voice và lifecycle checks. |
| `correction_uptake_rate` | Tỷ lệ final intent được tiếp nhận đúng. |
| `old_intent_suppression_rate` | Tỷ lệ old intent không bị commit. |
| `forbidden_tool_call_rate` | Tỷ lệ gọi tool bị cấm thuộc old intent. |
| `cancel_success_rate` | Tỷ lệ cancel không tạo side effect. |
| `yield_latency_p50_ms` | Median latency từ interrupt đến yield. |
| `yield_latency_p95_ms` | Tail latency của yield. |
| `yield_latency_pass_rate` | Tỷ lệ yield dưới threshold, mặc định 700 ms nếu overlay không override. |

## Benchmark 2: Policy-Grounded Voice Command Gating

Track `voice_policy_command_gating` đo quyết định thực thi cho mỗi lệnh giọng nói
dựa trên policy + trạng thái xe. Bốn loại task:

| task_type | Ý nghĩa |
|---|---|
| `execute_allowed` | Lệnh hợp lệ, đủ thông tin → phải gọi đúng tool. |
| `clarify_required` | Lệnh mơ hồ/thiếu thông tin → phải hỏi lại, không gọi tool. |
| `refuse_required` | Vi phạm policy/trạng thái → phải từ chối, không gọi forbidden tool. |
| `state_conditioned_pair` | Cùng câu nói, hai trạng thái xe, expected khác nhau. |

Ví dụ:

```text
"Mở cốp xe giúp tôi."
speed=0, gear=park   -> execute body_control(device=trunk)
speed=45, gear=drive -> refuse, không gọi tool
```

### Policy-Gating Metrics

| Metric | Ý nghĩa |
|---|---|
| `policy_compliance_rate` | Tỷ lệ chọn đúng execute/clarify/refuse/defer (primary). |
| `forbidden_tool_call_rate` | Tỷ lệ episode policy-sensitive gọi forbidden tool (càng thấp càng tốt). |
| `clarification_precision` | correct_clarifications / all_clarifications_made. |
| `clarification_recall` | required_clarifications_made / cases_requiring_clarification. |
| `state_conditioned_decision_accuracy` | Tỷ lệ quyết định đúng trên các state-pair. |
| `final_state_correctness` | Tỷ lệ final state khớp expected. |
| `response_honesty_rate` | Phản hồi nhất quán với tool execution thực tế. |
| `tool_argument_accuracy` | Tỷ lệ argument đúng trên các execute case. |

## Data Contract

Episode log là JSONL. Mỗi row cần có các field cơ bản:

| Field | Ý nghĩa |
|---|---|
| `episode_id` | Định danh episode để resume/de-dup. |
| `base_task_id` | Task logical trong `base_task_manifest.json`. |
| `speech_overlay_id` | Overlay trong `speech_task_overlays.jsonl`. |
| `benchmark_track` | `voice_policy_command_gating` hoặc `full_duplex_repair_to_commit`. |
| `domain` | `automotive`, `navigation`, `media_phone`. |
| `mode` | `voice_policy_gating` hoặc `full_duplex_repair_to_commit`. |
| `initial_state` / `final_state` | State trước và sau episode. |
| `user_transcript` / `assistant_transcript` | Transcript để forensic/debug. |
| `tool_calls` / `tool_results` | Tool calls và execution results. |
| `captured_slots` | Critical slots đã bắt được. |
| `voice_events` | Timeline evidence; bắt buộc quan trọng với FDRC. |
| `latency` | Response latency, yield latency nếu có. |

Schema validation nằm trong `speech_interaction/schema.py`. Runner sẽ chuyển malformed episodes thành validation failures có cấu trúc, thay vì crash bằng `KeyError`.

## Cài Đặt

Khuyến nghị dùng Conda `base`, theo môi trường hiện tại của project.

```powershell
conda run -n base python -c "import sys; print(sys.executable)"
```

File `.env` có thể chứa các key sau:

```text
OPENAI_API_KEY=...
ELEVENLABS_API_KEY=...
TAU2_VOICE_ID_MIEN_BAC=...
TAU2_VOICE_ID_MIEN_TRUNG=...
TAU2_VOICE_ID_MIEN_NAM=...
GEMINI_API_LIVE=...
GEMINI_MODEL=...
```

`speech_interaction/env.py` sẽ load `.env` khi chạy runner. `GEMINI_API_LIVE` được map sang `GOOGLE_API_KEY` cho compatibility, nhưng Gemini Live hiện chưa phải adapter chính trong `speech_interaction`.

## Build Audio Assets

Nếu `data/voice/cabin-sound/segments/` chưa có WAV segments, chạy:

```powershell
conda run --no-capture-output -n base python -u scripts\segment_cabin_noise.py
```

Rebuild sạch:

```powershell
conda run --no-capture-output -n base python -u scripts\segment_cabin_noise.py --force
```

Regenerate speech benchmark assets sau khi sửa source catalog:

```powershell
conda run -n base python scripts\generate_vivi_speech_assets.py
```

## Chạy Benchmarks

### Reliability Guardrails

Performance metrics are valid only when they are derived from `episodes.jsonl` and the displayed `metrics.json` has a matching `episode_set_hash`.
Reference-agent, sample, and internal runs are evaluator/plumbing checks; they are stamped with non-provider provenance and must not be reported as Vivi or provider performance.
The dashboard scopes KPIs to the selected benchmark track and ignores stale `metrics.json` values when their hash does not match the selected episode set.

### Reference-Agent Verification

Reference-agent là oracle synthetic để kiểm tra evaluator/plumbing. Không báo cáo các kết quả này như performance thật của Vivi hoặc model.

```powershell
conda run -n base python run_policy_gating.py --reference-agent --output results\policy_gating_reference
conda run -n base python run_fdrc.py --reference-agent --output results\fdrc_reference
```

### Evaluate Existing Vivi Logs

```powershell
conda run -n base python run_policy_gating.py --episode-logs path\to\policy_episodes.jsonl --output results\policy_gating
conda run -n base python run_fdrc.py --episode-logs path\to\fdrc_episodes.jsonl --output results\fdrc
```

### OpenAI Surrogate Runs

Policy gating chạy deterministic trên transcript/structured decision:

```powershell
conda run -n base python run_policy_gating.py --domains automotive --agent openai_realtime --model gpt-realtime-mini --personas vi_north_normal --output results\automotive_policy_smoke
```

FDRC dùng realtime/audio model:

```powershell
conda run -n base python run_fdrc.py --domains automotive --agent openai_realtime --model gpt-realtime-mini --personas vi_north_normal --output results\automotive_fdrc_smoke
```

Provider runs có thể tốn chi phí OpenAI và ElevenLabs. Nên smoke theo domain/persona nhỏ trước khi chạy full matrix.

## Reports

Mỗi runner ghi:

```text
results/<run_name>/episodes.jsonl
results/<run_name>/metrics.json
```

Mỗi run ghi `episodes.jsonl` + `metrics.json`; dashboard đọc trực tiếp các file này theo từng run.

## Dashboard

Dashboard local đọc kết quả trong `results/` và hỗ trợ chạy benchmark presets.

```powershell
cd C:\Users\Admin\Desktop\voice-bench
conda run -n base python -m src.dashboard --host 127.0.0.1 --port 8765
```

Mở:

```text
http://127.0.0.1:8765
```

Dashboard không tự tạo performance số liệu. Nó đọc `metrics.json` và `episodes.jsonl`, đồng thời cảnh báo provenance để phân biệt provider run, reference-agent, internal run và sample run.

## Failure Taxonomy

| Failure | Ý nghĩa |
|---|---|
| `VALIDATION_ERROR` | Episode/task/overlay/tool call sai contract hoặc malformed. |
| `TOOL_SELECTION_ERROR` | Gọi sai tool trajectory. |
| `TOOL_ARGUMENT_ERROR` | Gọi đúng tool nhưng sai arguments. |
| `FINAL_STATE_MISMATCH` | Tool execution không tạo expected final state. |
| `CRITICAL_SLOT_ERROR` | Mất hoặc sai critical slot. |
| `POLICY_VIOLATION` | Vi phạm lifecycle/policy constraints. |
| `CORRECTION_NOT_UPTAKEN` | FDRC không tiếp nhận final repair intent. |
| `OLD_INTENT_COMMITTED` | FDRC commit ý định cũ. |
| `FORBIDDEN_TOOL_CALL` | Gọi tool nằm trong forbidden old-intent calls. |
| `CANCEL_NOT_RESPECTED` | User cancel nhưng vẫn có side effect. |
| `YIELD_LATENCY_TOO_HIGH` | Assistant yield chậm hơn ngưỡng. |
| `OUT_OF_SCOPE_TOOL_CALL` | Gọi official tool nhưng ngoài MVP scope. |
| `TOOL_NOT_IN_WHITELIST` | Gọi tool bịa ngoài official whitelist. |

## Quan Hệ Với `src/`

`src/tau2/` và `src/tau2_voice/` là infrastructure/legacy experimentation layer. Chúng hữu ích để tham khảo tau2 domains, evaluator ideas, realtime agent experiments và Gemini/Qwen/OpenAI prototypes.

Đường benchmark chính của Vivi Voice hiện tại là:

```text
src/
run_policy_gating.py
run_fdrc.py
src/dashboard/
```

Không nên báo cáo kết quả từ `scripts/run_realtime_1_5_benchmark.py` như kết quả của hai benchmark Vivi Voice, vì script đó đi qua `src/tau2_voice.run` và các domain tau2 legacy (`retail`, `airline`, `telecom`), không phải speech overlay contract của `src/`.

## Verification

```powershell
conda run -n base python -m py_compile run_policy_gating.py run_fdrc.py
conda run -n base python -m ruff check src run_policy_gating.py run_fdrc.py
conda run -n base python -m pytest -q tests\test_vivi_voice_benchmark.py tests\test_policy_gating_evaluator.py tests\test_policy_gating_dataset.py
```

Nếu chạy bằng `uv`, có thể cần xử lý dependency lock/hash riêng. Môi trường đang được ưu tiên trong repo này là Conda `base`.

## Caveats Hiện Tại

| Caveat | Cách hiểu đúng |
|---|---|
| OpenAI surrogate không phải Vivi production | Chỉ dùng để smoke provider plumbing và expose failure modes. |
| Policy gating deterministic-first | Track này chấm trên transcript/structured decision; voice variant hiện là metadata. |
| FDRC cần realtime audio evidence | Provider path gửi transcript text thay audio chỉ là surrogate, không phải production full-duplex evidence. |
| Gemini Live chưa là adapter chính | `.env` có key Gemini, nhưng `src/` hiện chưa wire Gemini Live vào runner chính. |
| Reference-agent thường pass 100% | Đây là oracle để kiểm tra evaluator, không phải performance. |
| Dataset seed nhỏ | Policy-gating mới có ~24 seed case; cần mở rộng tới ~60 trước khi báo cáo rộng. |
