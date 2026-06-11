# Vivi Voice CarBench VN

## Context

`Vivi Voice CarBench VN` la benchmark tuong tac giong noi tieng Viet trong boi canh o to, dung de danh gia tro ly Vivi tren cac tac vu co side effect nhu dieu hoa, ghe, cua so, den, dieu huong, media va goi dien. Du an mo rong tu nen tang `tau2`/`VInteractiveBench`, nhung benchmark surface chinh cua du an hien nam trong `speech_interaction/`.

Benchmark nay khong chi do ASR, khong chi do chatbot, va khong chi do tool-calling bang text. Mot episode chi duoc tinh pass khi tool trajectory, tool arguments, final state, policy behavior, critical slots, communication va voice evidence deu dung theo contract.

## Problem Statement

Tro ly trong xe co hai nhom loi ma text benchmark thong thuong khong phat hien du:

| Nhom rui ro | Vi sao can benchmark rieng |
|---|---|
| Mat nang luc khi chuyen text sang voice | Cung mot task co the pass bang text nhung fail khi qua audio, accent, speech speed hoac cabin noise. |
| Commit sai khi hoi thoai bi chen ngang | Assistant co the da nghe lenh sua/huy nhung van goi tool theo y dinh cu, commit qua som, hoac khong yield khi user ngat loi. |

Vi vay du an tap trung vao hai benchmark:

1. `Text-to-Voice Capability Retention`: do ty le giu nang luc tu text baseline sang voice.
2. `Full-Duplex Repair-to-Commit`: do kha nang yield, tiep nhan sua/huy, chan old intent va chi commit final intent.

Tai lieu chi tiet:

- [Benchmark 1: Full-Duplex Repair-to-Commit](docs/benchmark_1_full_duplex_repair_to_commit.md)
- [Benchmark 2: Text-to-Voice Capability Retention](docs/benchmark_2_text_to_voice_retention.md)
- [Dashboard usage](docs/dashboard_usage.md)
- [Benchmark overview](docs/benchmark/tong-quan-benchmark.md)

## MVP Scope

| Dimension | Scope hien tai |
|---|---|
| Domains | `automotive`, `navigation`, `media_phone` |
| Base tasks | 30 tasks, chia 10/10/10 theo domain |
| Speech overlays | 60 overlays: 30 retention va 30 FDRC |
| Official Vivi tools | 25 tools trong registry |
| MVP in-scope tools | 19 tools, loai 6 information/search tools |
| Personas | 9 personas: north/central/south x slow/normal/fast |
| Audio conditions | `clean`, `cabin_noise`, `interaction_stress` |
| Full-duplex scheduler | deterministic tick `200 ms` |
| Primary runner surface | `speech_interaction/`, `run_text_baseline.py`, `run_voice_retention.py`, `run_fdrc.py` |

Sau official tools nam ngoai MVP la `weather`, `news_search`, `web_search`, `vinfast_kb`, `vehicle_troubleshoot`, `software_release`. Goi cac tool nay duoc phan loai la `OUT_OF_SCOPE_TOOL_CALL`; goi tool bia ngoai whitelist duoc phan loai la `TOOL_NOT_IN_WHITELIST`.

## Repository Map

| Path | Vai tro |
|---|---|
| `speech_interaction/` | Benchmark surface chinh: assets, schemas, adapters, evaluator, audio pipeline, dashboard. |
| `speech_interaction/base_task_manifest.json` | Manifest 30 logical tasks, tham chieu domain task source. |
| `speech_interaction/speech_task_overlays.jsonl` | 60 speech overlays: utterance, persona/audio condition, critical slots, FDRC timeline. |
| `speech_interaction/evaluator/` | Deterministic evaluators cho retention, FDRC, tool schema, tool scope, critical slots, voice events. |
| `speech_interaction/orchestrator/` | Runtime orchestration: provider adapter, audio streaming, tool server, event normalization. |
| `speech_interaction/audio/` | TTS, audio cache, PCM conversion, noise mixing. |
| `speech_interaction/tools/` | Canonical Vivi tool registry, schema va mock tool server. |
| `speech_interaction/dashboard/` | Local dashboard de xem runs, metrics, failures va episode details. |
| `scripts/` | Asset generation, cabin noise segmentation, provider smoke scripts. |
| `docs/` | Product/benchmark documentation va dashboard guide. |
| `src/tau2/` | Upstream tau2 infrastructure, domain/evaluator/orchestrator legacy. |
| `src/tau2_voice/` | Legacy voice/realtime experiments, including Gemini/Qwen/OpenAI paths; khong phai benchmark surface chinh. |
| `results/` | Output cua cac lan chay: `episodes.jsonl`, `metrics.json`, report artifacts. |

## Benchmark 1: Full-Duplex Repair-to-Commit

### Scenario

FDRC tao tinh huong user noi mot lenh ban dau, assistant bat dau phan hoi, sau do user chen ngang de sua hoac huy. Benchmark kiem tra Vivi co dung lai dung luc, bo y dinh cu va chi commit y dinh cuoi cung hay khong.

Vi du scenario:

```text
User initial: "Dan duong den nha hang A."
Assistant: bat dau confirm hoac xu ly.
User interrupt: "A khong, den nha hang B."
Expected: khong commit route A, chi commit route B sau moc duoc phep.
```

Cancel scenario:

```text
User initial: "Goi cho Minh."
Assistant: bat dau confirm.
User interrupt: "Thoi huy di."
Expected: khong co tool call tao cuoc goi.
```

### Runtime Flow

| Step | Component | Detail |
|---|---|---|
| 1 | `run_fdrc.py` | Load `.env`, tasks, overlays, personas, model va `tick_ms=200`. |
| 2 | `preflight_validate_assets()` | Validate task/overlay contract, required FDRC timeline events, expected/forbidden tool consistency. |
| 3 | `OpenAIRealtimeViviAdapter` | Mo realtime/audio session va khai bao official Vivi tool schema. |
| 4 | `AudioCache` | Build or load audio cho `initial_spoken_utterance` va `repair_utterance`. |
| 5 | `NoiseMixer` | Mix `interaction_stress`: cabin segments, engine sound, continuous noise, bursts. |
| 6 | `_stream_audio()` | Stream PCM16 24 kHz theo 100 ms chunks. |
| 7 | `_drain_adapter_events()` | Thu assistant speech/transcript/tool calls, execute tool tren `MockToolServer`. |
| 8 | `_voice_events_from_normalized()` | Tao `assistant_yielded` tu speech stop sau `user_interrupt_start`. |
| 9 | `schedule_timeline()` | Gan tick `t_ms // 200` cho voice events. |
| 10 | `evaluate_fdrc_episode()` | Cham lifecycle, tool/state, policy va latency. |

### FDRC Required Evidence

| Field/Event | Y nghia |
|---|---|
| `assistant_speech_start` | Assistant thuc su dang noi truoc khi user interrupt. |
| `user_interrupt_start` | Moc user bat dau chen ngang. |
| `assistant_yielded` | Moc assistant dung/yield sau interrupt. |
| `assistant_should_yield_by` | Deadline yield theo overlay. |
| `tool_commit_allowed_after` | Moc som nhat duoc phep commit side effect. |
| Tool call `t_ms` | Timestamp dung de phat hien early commit. |
| `expected_tool_calls` | Final intent phai duoc commit. |
| `forbidden_tool_calls` | Old intent tuyet doi khong duoc commit. |
| `final_intent` | Final user intent sau repair, co the la `cancel`. |

### FDRC Metrics

| Metric | Y nghia |
|---|---|
| `fdrc_pass_at_1` | Episode pass toan bo task, policy, voice va lifecycle checks. |
| `correction_uptake_rate` | Ty le final intent duoc tiep nhan dung. |
| `old_intent_suppression_rate` | Ty le old intent khong bi commit. |
| `forbidden_tool_call_rate` | Ty le goi tool bi cam thuoc old intent. |
| `cancel_success_rate` | Ty le cancel khong tao side effect. |
| `yield_latency_p50_ms` | Median latency tu interrupt den yield. |
| `yield_latency_p95_ms` | Tail latency cua yield. |
| `yield_latency_pass_rate` | Ty le yield duoi threshold, mac dinh 700 ms neu overlay khong override. |

## Benchmark 2: Text-to-Voice Capability Retention

### Scenario

Retention benchmark chay cung mot logical task qua nhieu input modes:

1. `text_baseline`: text input, chi phi thap, do nang luc task/tool goc.
2. `clean_voice`: audio tieng Viet sach.
3. `realistic_cabin_voice`: audio tieng Viet co cabin/engine/noise.

Benchmark hoi: neu Vivi lam dung task bang text, khi user noi cung task do bang giong noi thi Vivi con giu duoc bao nhieu nang luc?

Vi du:

```text
Text: "Dat dieu hoa ghe lai 22 do."
Clean voice: cung cau noi duoc synthesize thanh audio sach.
Cabin voice: cung cau noi, mix cabin_noise.
Expected: tool `climate_control` dung args `temperature=22`, `position=driver`, final state dung.
```

### Runtime Flow

| Step | Component | Detail |
|---|---|---|
| 1 | `run_text_baseline.py` | Chay text baseline bang episode logs, reference-agent, hoac `openai_text`. |
| 2 | `run_voice_retention.py` | Chay clean/cabin voice bang episode logs, reference-agent, hoac `openai_realtime`. |
| 3 | `AudioCache` | Cache TTS/noise variants de rerun re dung audio. |
| 4 | `MockToolServer` | Execute validated tool calls va tao final state deterministic. |
| 5 | `evaluate_retention_episode()` | Cham exact tool trajectory, args, state, critical slots, communication. |
| 6 | `summarize_retention()` | Tinh pass rates va retention ratios. |

### Retention Evaluation Surface

| Layer | Cham cai gi |
|---|---|
| Tool trajectory | Model co goi dung chuoi tool expected khong. |
| Tool arguments | Args co dung schema va dung slot expected khong. |
| Final state | Mock state sau tool calls co khop expected final state khong. |
| Critical slots | Slot quan trong co duoc giu lai qua audio khong. |
| Communication | Assistant co noi thong tin bat buoc neu task yeu cau khong. |
| Voice condition | So sanh `clean_voice` va `realistic_cabin_voice`. |
| Persona | Co the do accent gap va speed gap khi chay day du 9 personas. |

### Retention Metrics

| Metric | Y nghia |
|---|---|
| `text_pass_at_1` | Pass rate cua text baseline. |
| `clean_voice_pass_at_1` | Pass rate cua clean voice. |
| `cabin_voice_pass_at_1` | Pass rate cua realistic cabin voice. |
| `clean_voice_retention` | `clean_voice_pass_at_1 / text_pass_at_1`. |
| `voice_capability_retention` | `cabin_voice_pass_at_1 / text_pass_at_1`. |
| `voice_degradation_gap` | `text_pass_at_1 - cabin_voice_pass_at_1`. |
| `critical_slot_accuracy` | Ty le critical slots duoc giu dung. |
| `accent_gap` | Chenh lech giua accent regions khi chay nhieu accent. |
| `speed_gap` | Chenh lech giua speech speeds khi chay nhieu speed. |

## Data Contract

Episode log la JSONL. Moi row can co cac field co ban:

| Field | Y nghia |
|---|---|
| `episode_id` | Dinh danh episode de resume/de-dup. |
| `base_task_id` | Task logical trong `base_task_manifest.json`. |
| `speech_overlay_id` | Overlay trong `speech_task_overlays.jsonl`. |
| `benchmark_track` | `text_to_voice_retention` hoac `full_duplex_repair_to_commit`. |
| `domain` | `automotive`, `navigation`, `media_phone`. |
| `mode` | `text_baseline`, `clean_voice`, `realistic_cabin_voice`, hoac `full_duplex_repair_to_commit`. |
| `initial_state` / `final_state` | State truoc va sau episode. |
| `user_transcript` / `assistant_transcript` | Transcript de forensic/debug. |
| `tool_calls` / `tool_results` | Tool calls va execution results. |
| `captured_slots` | Critical slots da bat duoc. |
| `voice_events` | Timeline evidence; bat buoc quan trong voi FDRC. |
| `latency` | Response latency, yield latency neu co. |

Schema validation nam trong `speech_interaction/schema.py`. Runner se chuyen malformed episodes thanh validation failures co cau truc, thay vi crash bang `KeyError`.

## Setup

Khuyen nghi dung Conda `base`, theo yeu cau hien tai cua project.

```powershell
conda run -n base python -c "import sys; print(sys.executable)"
```

File `.env` co the chua cac key sau:

```text
OPENAI_API_KEY=...
ELEVENLABS_API_KEY=...
TAU2_VOICE_ID_MIEN_BAC=...
TAU2_VOICE_ID_MIEN_TRUNG=...
TAU2_VOICE_ID_MIEN_NAM=...
GEMINI_API_LIVE=...
GEMINI_MODEL=...
```

`speech_interaction/env.py` se load `.env` khi chay runner. `GEMINI_API_LIVE` duoc map sang `GOOGLE_API_KEY` cho compatibility, nhung Gemini Live hien chua phai adapter chinh trong `speech_interaction`.

## Build Audio Assets

Cabin/stress audio can noise segments. Neu `data/voice/cabin-sound/segments/` chua co WAV segments, chay:

```powershell
conda run --no-capture-output -n base python -u scripts\segment_cabin_noise.py
```

Rebuild sach:

```powershell
conda run --no-capture-output -n base python -u scripts\segment_cabin_noise.py --force
```

Vua hien log vua luu file:

```powershell
conda run --no-capture-output -n base python -u scripts\segment_cabin_noise.py 2>&1 | Tee-Object -FilePath segment_cabin_noise.log
```

Regenerate speech benchmark assets sau khi sua source catalog:

```powershell
conda run -n base python scripts\generate_vivi_speech_assets.py
```

## Run Benchmarks

### Reference-Agent Verification

Reference-agent la oracle synthetic de kiem tra evaluator/plumbing. Khong bao cao cac ket qua nay nhu performance that cua Vivi hoac model.

```powershell
conda run -n base python run_text_baseline.py --reference-agent --output results\text_reference
conda run -n base python run_voice_retention.py --reference-agent --output results\voice_reference
conda run -n base python run_fdrc.py --reference-agent --output results\fdrc_reference
```

### Evaluate Existing Vivi Logs

```powershell
conda run -n base python run_text_baseline.py --episode-logs path\to\text_episodes.jsonl --output results\text_baseline
conda run -n base python run_voice_retention.py --episode-logs path\to\voice_episodes.jsonl --output results\voice_retention
conda run -n base python run_fdrc.py --episode-logs path\to\fdrc_episodes.jsonl --output results\fdrc
```

### OpenAI Surrogate Runs

Text baseline dung model chi phi thap:

```powershell
conda run -n base python run_text_baseline.py --agent openai_text --model gpt-4o-mini --output results\openai_text_gpt4o_mini
```

Voice retention dung realtime/audio model:

```powershell
conda run -n base python run_voice_retention.py --domains automotive --agent openai_realtime --model gpt-realtime-mini --personas vi_north_normal --audio-conditions "clean,cabin_noise" --output results\automotive_voice_smoke
```

FDRC dung realtime/audio model:

```powershell
conda run -n base python run_fdrc.py --domains automotive --agent openai_realtime --model gpt-realtime-mini --personas vi_north_normal --output results\automotive_fdrc_smoke
```

Provider runs co the ton chi phi OpenAI va ElevenLabs. Nen smoke theo domain/persona nho truoc khi chay full matrix.

## Reports

Moi runner ghi:

```text
results/<run_name>/episodes.jsonl
results/<run_name>/metrics.json
```

Tao report hop nhat:

```powershell
conda run -n base python generate_voice_report.py `
  --text-results results\openai_text_gpt4o_mini\episodes.jsonl `
  --voice-results results\automotive_voice_smoke\episodes.jsonl `
  --fdrc-results results\automotive_fdrc_smoke\episodes.jsonl `
  --output results\voice_report
```

Output:

| File | Noi dung |
|---|---|
| `vivi_voice_report.md` | Bang metrics retention/FDRC va failure summary. |
| `vivi_voice_failures.csv` | Danh sach failed episodes de debug. |

## Dashboard

Dashboard local doc ket qua trong `results/` va ho tro chay benchmark presets.

```powershell
conda run -n base python -m speech_interaction.dashboard --host 127.0.0.1 --port 8765
```

Mo:

```text
http://127.0.0.1:8765
```

Dashboard khong tu tao performance so lieu. No doc `metrics.json` va `episodes.jsonl`, dong thoi canh bao provenance de phan biet provider run, reference-agent, internal run va sample run.

## Failure Taxonomy

| Failure | Y nghia |
|---|---|
| `VALIDATION_ERROR` | Episode/task/overlay/tool call sai contract hoac malformed. |
| `TOOL_SELECTION_ERROR` | Goi sai tool trajectory. |
| `TOOL_ARGUMENT_ERROR` | Goi dung tool nhung sai arguments. |
| `FINAL_STATE_MISMATCH` | Tool execution khong tao expected final state. |
| `CRITICAL_SLOT_ERROR` | Mat hoac sai critical slot. |
| `POLICY_VIOLATION` | Vi pham lifecycle/policy constraints. |
| `CORRECTION_NOT_UPTAKEN` | FDRC khong tiep nhan final repair intent. |
| `OLD_INTENT_COMMITTED` | FDRC commit y dinh cu. |
| `FORBIDDEN_TOOL_CALL` | Goi tool nam trong forbidden old-intent calls. |
| `CANCEL_NOT_RESPECTED` | User cancel nhung van co side effect. |
| `YIELD_LATENCY_TOO_HIGH` | Assistant yield cham hon nguong. |
| `OUT_OF_SCOPE_TOOL_CALL` | Goi official tool nhung ngoai MVP scope. |
| `TOOL_NOT_IN_WHITELIST` | Goi tool bia ngoai official whitelist. |

## Relationship With `src/`

`src/tau2/` va `src/tau2_voice/` la infrastructure/legacy experimentation layer. Chung huu ich de tham khao tau2 domains, evaluator ideas, realtime agent experiments va Gemini/Qwen/OpenAI prototypes.

Duong benchmark chinh cua Vivi Voice hien tai la:

```text
speech_interaction/
run_text_baseline.py
run_voice_retention.py
run_fdrc.py
generate_voice_report.py
speech_interaction/dashboard/
```

Khong nen bao cao ket qua tu `scripts/run_realtime_1_5_benchmark.py` nhu ket qua cua hai benchmark Vivi Voice, vi script do di qua `src/tau2_voice.run` va cac domain tau2 legacy (`retail`, `airline`, `telecom`), khong phai speech overlay contract cua `speech_interaction`.

## Verification

```powershell
conda run -n base python -m py_compile run_text_baseline.py run_voice_retention.py run_fdrc.py generate_voice_report.py
conda run -n base python -m ruff check speech_interaction run_text_baseline.py run_voice_retention.py run_fdrc.py generate_voice_report.py
conda run -n base python -m pytest -q tests\test_vivi_voice_benchmark.py
```

Neu chay bang `uv`, co the can xu ly dependency lock/hash rieng. Moi truong dang duoc uu tien trong repo nay la Conda `base`.

## Current Caveats

| Caveat | Cach hieu dung |
|---|---|
| OpenAI surrogate khong phai Vivi production | Chi dung de smoke provider plumbing va expose failure modes. |
| `gpt-4o-mini` chi dung cho text baseline | Khong dung de bao cao voice benchmark. |
| Voice/FDRC can realtime audio evidence | Provider path gui transcript text thay audio chi la surrogate, khong phai production full-duplex evidence. |
| Gemini Live chua la adapter chinh | `.env` co key Gemini, nhung `speech_interaction` hien chua wire Gemini Live vao runner chinh. |
| Reference-agent thuong pass 100% | Day la oracle de kiem tra evaluator, khong phai performance. |
| Full matrix ton chi phi | 30 retention overlays x 2 voice modes x 9 personas = 540 voice episodes neu chay day du; FDRC 30 overlays x 9 personas = 270 episodes. Nen smoke nho truoc. |

## Short Interpretation

Text-to-Voice Capability Retention tra loi:

```text
Cung mot task Vivi lam duoc bang text, khi chuyen sang giong noi tieng Viet trong xe thi con giu duoc bao nhieu nang luc?
```

Full-Duplex Repair-to-Commit tra loi:

```text
Khi user chen ngang de sua hoac huy, Vivi co dung lai, bo y dinh cu, va chi commit y dinh cuoi cung dung thoi diem khong?
```

Hai benchmark nay bo sung cho nhau. Retention do voice robustness cua nang luc task. FDRC do safety/lifecycle cua hoi thoai song cong truoc khi side effect duoc commit.
