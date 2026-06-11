const TRACK_RETENTION = "text_to_voice_retention";
const TRACK_FDRC = "full_duplex_repair_to_commit";

const benchmarkText = {
  [TRACK_RETENTION]:
    "Mục đích: đo mức Vivi giữ được năng lực từ text baseline sang voice, đặc biệt critical slots, tool calls, arguments và final state.",
  [TRACK_FDRC]:
    "Mục đích: đo khả năng nhường lời khi user chen ngang, tiếp nhận lệnh sửa/hủy, chặn ý định cũ và chỉ commit ý định cuối cùng.",
};

const metricInfo = {
  pass_at_1: ["Pass tổng", "Tỷ lệ episode pass toàn bộ tiêu chí chấm điểm."],
  text_pass_at_1: ["Pass text baseline", "Tỷ lệ pass của các episode text baseline."],
  clean_voice_pass_at_1: ["Pass voice sạch", "Tỷ lệ pass khi input là giọng nói sạch."],
  cabin_voice_pass_at_1: ["Pass voice cabin", "Tỷ lệ pass khi input là giọng nói có nhiễu cabin."],
  voice_capability_retention: ["Giữ năng lực voice", "Cabin voice pass chia cho text baseline pass."],
  critical_slot_accuracy: ["Đúng critical slot", "Tỷ lệ slot quan trọng được giữ đúng."],
  tool_exact_match: ["Khớp tool", "Tỷ lệ episode gọi đúng chuỗi tool expected."],
  argument_exact_match: ["Khớp argument", "Tỷ lệ episode truyền đúng argument tool expected."],
  state_match: ["Khớp trạng thái", "Tỷ lệ episode có final state khớp expected."],
  fdrc_pass_at_1: ["Pass FDRC", "Tỷ lệ episode FDRC pass toàn bộ tiêu chí."],
  yield_latency_p50_ms: ["P50 nhường lời", "Trung vị độ trễ nhường lời sau khi user chen ngang."],
  yield_latency_p95_ms: ["P95 nhường lời", "Phân vị 95 của độ trễ nhường lời."],
  yield_latency_pass_rate: ["Pass latency", "Tỷ lệ episode có yield latency trong ngưỡng cho phép."],
  policy_violation_rate: ["Vi phạm policy", "Tỷ lệ episode vi phạm policy benchmark."],
  tool_validation_error_rate: ["Lỗi validation tool", "Tỷ lệ episode có lỗi schema, argument hoặc contract tool."],
  old_intent_suppression_rate: ["Chặn ý định cũ", "Tỷ lệ episode không commit ý định cũ sau khi user sửa/hủy."],
  forbidden_tool_call_rate: ["Gọi tool bị cấm", "Tỷ lệ episode có forbidden tool call."],
};

const kpiByTrack = {
  [TRACK_RETENTION]: {
    primary: [
      "pass_at_1",
      "voice_capability_retention",
      "critical_slot_accuracy",
      "cabin_voice_pass_at_1",
      "tool_exact_match",
    ],
    secondary: [
      "text_pass_at_1",
      "clean_voice_pass_at_1",
      "argument_exact_match",
      "state_match",
      "tool_validation_error_rate",
    ],
  },
  [TRACK_FDRC]: {
    primary: [
      "fdrc_pass_at_1",
      "yield_latency_p50_ms",
      "yield_latency_p95_ms",
      "policy_violation_rate",
      "state_match",
    ],
    secondary: [
      "yield_latency_pass_rate",
      "tool_validation_error_rate",
      "old_intent_suppression_rate",
      "forbidden_tool_call_rate",
      "pass_at_1",
    ],
  },
};

const failureDescriptions = {
  FINAL_STATE_MISMATCH: "Final state không khớp expected state.",
  CORRECTION_NOT_UPTAKEN: "Không tiếp nhận đúng lệnh sửa của user.",
  YIELD_LATENCY_TOO_HIGH: "Nhường lời quá chậm sau khi user chen ngang.",
  TOOL_SELECTION_ERROR: "Chọn sai tool hoặc thiếu tool cần gọi.",
  VALIDATION_ERROR: "Episode/tool call vi phạm schema hoặc contract.",
  POLICY_VIOLATION: "Vi phạm policy như commit sớm, commit trùng hoặc xác nhận ý định cũ.",
  TOOL_ARGUMENT_ERROR: "Đúng tool nhưng sai argument.",
  FORBIDDEN_TOOL_CALL: "Gọi tool thuộc ý định cũ hoặc tool bị cấm.",
  OLD_INTENT_COMMITTED: "Đã commit ý định cũ sau khi user sửa/hủy.",
  CRITICAL_SLOT_ERROR: "Critical slot bị sai hoặc mất.",
  FABRICATED_SUCCESS: "Báo thành công nhưng tool/state không chứng minh thành công.",
};

const state = {
  runs: [],
  presets: [],
  config: null,
  selectedRun: null,
  summary: null,
  episodes: [],
  allEpisodes: [],
  activeJobId: null,
  selectedDetail: null,
  activeTab: "summary",
  quickFilter: null,
};

function $(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmt(value) {
  if (value === null || value === undefined) return "N/A";
  if (typeof value === "number") {
    if (Math.abs(value) <= 1) return `${(value * 100).toFixed(1)}%`;
    return Number.isInteger(value) ? `${value}` : value.toFixed(1);
  }
  return String(value);
}

function trackLabel(track) {
  if (track === TRACK_RETENTION) return "Text-to-Voice Retention";
  if (track === TRACK_FDRC) return "Full-Duplex Repair-to-Commit";
  return track || "Không rõ";
}

async function fetchJson(url, options = undefined) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function setStatus(text) {
  $("statusPill").textContent = text;
}

function selectedTrack() {
  return $("benchmarkSelect").value;
}

function primaryRunsForTrack(track) {
  return state.runs.filter((run) => run.primary && run.benchmark_track === track);
}

function fallbackRunsForTrack(track) {
  return state.runs.filter((run) => (run.tracks || []).includes(track));
}

function setOptions(select, values, allLabel = "Tất cả", keepValue = true) {
  const previous = keepValue ? select.value : "";
  select.innerHTML = `<option value="">${allLabel}</option>`;
  for (const value of values || []) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  }
  if ([...select.options].some((option) => option.value === previous)) {
    select.value = previous;
  }
}

function optionLabel(kind, value) {
  const config = state.config || {};
  if (kind === "domain") {
    const item = (config.domains || []).find((row) => row.domain === value);
    return item ? `${item.label} (${value})` : value;
  }
  if (kind === "speed") {
    const item = (config.speech_speeds || []).find((row) => row.speech_speed === value);
    return item ? `${item.label} (${value})` : value;
  }
  if (kind === "audio") {
    if (value === "none") return "Không có audio condition (none)";
    const item = (config.audio_conditions || []).find((row) => row.condition_id === value);
    return item ? `${item.condition_id} — ${item.description}` : value;
  }
  if (kind === "accent") {
    const persona = (config.personas || []).find((row) => row.accent_region === value);
    return persona ? `${persona.accent_region_label} (${value})` : value;
  }
  return value;
}

function setLabeledOptions(select, values, kind, allLabel = "Tất cả", keepValue = true) {
  const previous = keepValue ? select.value : "";
  select.innerHTML = `<option value="">${allLabel}</option>`;
  for (const value of values || []) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = optionLabel(kind, value);
    select.appendChild(option);
  }
  if ([...select.options].some((option) => option.value === previous)) {
    select.value = previous;
  }
}

function renderRuns() {
  const track = selectedTrack();
  const primary = primaryRunsForTrack(track);
  const candidates = primary.length ? primary : fallbackRunsForTrack(track);
  const select = $("runSelect");
  select.innerHTML = "";
  for (const run of candidates) {
    const option = document.createElement("option");
    option.value = run.run_id;
    const suffix = run.data_provenance === "provider" ? "" : ` · ${run.provenance_label}`;
    option.textContent = `${run.run_id} (${run.episode_count})${suffix}`;
    select.appendChild(option);
  }
  if (!candidates.some((run) => run.run_id === state.selectedRun)) {
    state.selectedRun = candidates[0]?.run_id || null;
  }
  select.value = state.selectedRun || "";
  $("benchmarkPurpose").textContent = benchmarkText[track];
}

function renderPresets() {
  const select = $("presetSelect");
  const presets = state.presets.filter((preset) => preset.benchmark_track === selectedTrack());
  select.innerHTML = "";
  for (const preset of presets) {
    const option = document.createElement("option");
    option.value = preset.id;
    option.textContent = preset.label;
    select.appendChild(option);
  }
  alignPresetToBenchmark();
  updateRunScope();
}

function alignPresetToBenchmark() {
  const preferred = selectedTrack() === TRACK_RETENTION ? "retention_reference" : "fdrc_reference";
  if ([...$("presetSelect").options].some((option) => option.value === preferred)) {
    $("presetSelect").value = preferred;
  }
}

function updateRunScope() {
  const domain = $("domainFilter")?.value || "";
  const domains = domain
    ? [domain]
    : state.summary?.metadata?.domains?.length
      ? state.summary.metadata.domains
      : ["automotive", "navigation", "media_phone"];
  if ($("runDomains")) $("runDomains").value = domains.join(",");
  const track = selectedTrack();
  const domainText = domains.map((item) => optionLabel("domain", item)).join(", ");
  $("runScopeText").textContent =
    `Sẽ chạy ${trackLabel(track)} trên ${domainText}. Reference-agent không gọi provider; OpenAI preset sẽ dùng credential hiện có.`;
  renderRunEstimate();
}

function selectedRunDomains() {
  return ($("runDomains")?.value || "automotive,navigation,media_phone")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function selectedRunPersonas() {
  return ($("runPersonas")?.value || "vi_north_normal,vi_central_normal,vi_south_normal")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function estimateEpisodeCount() {
  const track = selectedTrack();
  const counts = state.config?.overlay_counts?.[track] || {};
  const overlayCount = selectedRunDomains().reduce((total, domain) => total + (counts[domain] || 0), 0);
  const personaCount = selectedRunPersonas().length || 1;
  const modeMultiplier = track === TRACK_RETENTION ? 2 : 1;
  return {
    overlayCount,
    personaCount,
    modeMultiplier,
    total: overlayCount * personaCount * modeMultiplier,
  };
}

function renderRunEstimate() {
  if (!$("runEstimate")) return;
  const estimate = estimateEpisodeCount();
  const provider = $("presetSelect")?.value?.includes("openai");
  const audioModes = selectedTrack() === TRACK_RETENTION ? "clean + cabin_noise" : "interaction_stress";
  $("runEstimate").innerHTML = `
    <strong>Ước lượng:</strong> ${estimate.total} episode
    (${estimate.overlayCount} overlay × ${estimate.personaCount} persona × ${estimate.modeMultiplier} mode).
    <br><strong>Audio condition:</strong> ${audioModes}.
    <br><strong>Nguồn chạy:</strong> ${provider ? "Provider/model thật, có thể phát sinh chi phí." : "Reference-agent, không gọi provider."}`;
}

function renderSummary() {
  const summary = state.summary;
  if (!summary) return;
  $("runTitle").textContent = summary.run_id;
  $("runMeta").textContent =
    `Track: ${summary.benchmark_label} · Status: ${summary.status} · Episodes: ${summary.episode_count} · Source: ${summary.provenance_label} · Updated: ${summary.updated_at || "N/A"}`;
  $("statusPill").textContent = summary.status;
  $("benchmarkPurpose").textContent = benchmarkText[selectedTrack()];
  renderProvenance(summary);
  const metadata = summary.metadata || {};
  setLabeledOptions($("domainFilter"), metadata.domains, "domain");
  setOptions($("modeFilter"), metadata.modes);
  setOptions($("failureFilter"), (summary.failure_counts || []).map((row) => row.key));
  setLabeledOptions($("accentFilter"), metadata.accent_regions, "accent");
  setLabeledOptions($("speedFilter"), metadata.speech_speeds, "speed");
  setLabeledOptions($("audioFilter"), metadata.audio_conditions, "audio");
  renderKpis();
  renderBreakdown();
  renderFailureBars("failureChart", summary.failure_counts || []);
  renderLatency(summary.latency_summary || []);
  renderFocusPanel();
  updateRunScope();
}

function renderProvenance(summary) {
  const banner = $("provenanceBanner");
  if (!summary.provenance_warning) {
    banner.classList.add("hidden");
    banner.textContent = "";
    return;
  }
  banner.classList.remove("hidden");
  banner.innerHTML = `<strong>${escapeHtml(summary.provenance_label)}.</strong> ${escapeHtml(summary.provenance_warning)}`;
}

function renderKpis() {
  const config = kpiByTrack[selectedTrack()] || kpiByTrack[TRACK_RETENTION];
  $("primaryKpiGrid").innerHTML = renderKpiCards(config.primary);
  $("secondaryKpiGrid").innerHTML = renderKpiCards(config.secondary);
}

function renderKpiCards(keys) {
  return keys
    .map((key) => {
      const [label, help] = metricInfo[key] || [key, "Chưa có mô tả metric."];
      return `
        <div class="kpi" tabindex="0">
          <div class="label">${escapeHtml(label)}</div>
          <div class="value">${escapeHtml(fmt(state.summary?.metrics?.[key]))}</div>
          <div class="metric-help">${escapeHtml(help)}</div>
        </div>`;
    })
    .join("");
}

function breakdownRows() {
  const key = $("breakdownSelect").value;
  const map = {
    domain: "pass_by_domain",
    mode: "pass_by_mode",
    accent_region: "pass_by_accent_region",
    speech_speed: "pass_by_speech_speed",
    audio_condition: "pass_by_audio_condition",
  };
  return state.summary?.[map[key]] || [];
}

function renderBreakdown() {
  renderRateBars("breakdownChart", breakdownRows());
}

function renderRateBars(id, rows) {
  const element = $(id);
  if (!rows.length) {
    element.innerHTML = '<div class="muted">Không có dữ liệu đã chấm điểm.</div>';
    return;
  }
  element.innerHTML = rows
    .map((row) => {
      const percent = row.rate === null || row.rate === undefined ? 0 : row.rate * 100;
      return `
        <div class="bar-row">
          <div class="bar-label">${escapeHtml(row.key)}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${percent}%"></div></div>
          <div class="bar-value">${escapeHtml(fmt(row.rate))}</div>
        </div>`;
    })
    .join("");
}

function renderFailureBars(id, rows) {
  const element = $(id);
  if (!rows.length) {
    element.innerHTML = '<div class="muted">Run này không ghi nhận lỗi.</div>';
    return;
  }
  const totalEpisodes = state.summary?.episode_count || 0;
  const failedEpisodes = state.summary?.pass_fail?.failed || 0;
  element.innerHTML = `
    <div class="failure-note">
      Đây là số episode có từng loại lỗi, không phải điểm số. Một episode fail có thể xuất hiện ở nhiều loại lỗi nếu nó
      vừa sai tool, vừa sai state hoặc vi phạm policy.
    </div>
    <div class="failure-list">
      ${rows
        .map((row) => {
          const runPercent = totalEpisodes ? row.count / totalEpisodes : null;
          const failPercent = failedEpisodes ? row.count / failedEpisodes : null;
          const barPercent = runPercent === null ? 0 : runPercent * 100;
      const desc = failureDescriptions[row.key] || "Chưa có mô tả lỗi.";
      return `
          <div class="failure-row" title="${escapeHtml(desc)}">
            <div class="failure-copy">
              <strong>${escapeHtml(row.key)}</strong>
              <span>${escapeHtml(desc)}</span>
            </div>
            <div class="failure-meter" aria-label="${escapeHtml(row.count)} episode">
              <div class="bar-track"><div class="bar-fill failure" style="width:${barPercent}%"></div></div>
              <div class="failure-value">
                <strong>${row.count} episode</strong>
                <span>${escapeHtml(fmt(runPercent))} của run${failPercent === null ? "" : ` · ${escapeHtml(fmt(failPercent))} trên episode fail`}</span>
              </div>
            </div>
          </div>`;
        })
        .join("")}
    </div>`;
}

function renderLatency(rows) {
  const element = $("latencyChart");
  if (!rows.length) {
    element.innerHTML = '<div class="muted">Không có latency hợp lệ trong run này.</div>';
    return;
  }
  element.innerHTML = `
    <table class="latency-table">
      <thead><tr><th>Metric</th><th>Số mẫu</th><th>Nhỏ nhất</th><th>P50</th><th>P95</th><th>Lớn nhất</th></tr></thead>
      <tbody>
        ${rows
          .map(
            (row) => `
              <tr>
                <td>${escapeHtml(row.metric)}</td>
                <td>${row.count}</td>
                <td>${escapeHtml(fmt(row.min_ms))} ms</td>
                <td>${escapeHtml(fmt(row.p50_ms))} ms</td>
                <td>${escapeHtml(fmt(row.p95_ms))} ms</td>
                <td>${escapeHtml(fmt(row.max_ms))} ms</td>
              </tr>`,
          )
          .join("")}
      </tbody>
    </table>`;
}

function renderFocusPanel() {
  const panel = $("focusPanel");
  if (selectedTrack() === TRACK_FDRC) {
    $("focusPanelTitle").textContent = "Độ trễ và rủi ro ngắt lời";
    const slow = state.summary?.top_yield_latency_episodes || [];
    panel.innerHTML = slow.length
      ? `<div class="mini-list">${slow
          .map(
            (row) => `
              <button class="mini-item" data-episode-id="${escapeHtml(row.episode_id)}">
                <span>${escapeHtml(row.episode_id)}</span>
                <strong>${escapeHtml(fmt(row.value))} ms</strong>
              </button>`,
          )
          .join("")}</div>`
      : '<div class="muted">Không có yield latency để xếp hạng.</div>';
  } else {
    $("focusPanelTitle").textContent = "Slot và suy giảm voice";
    panel.innerHTML = `
      <div class="focus-grid">
        <div><span>Pass text baseline</span><strong>${fmt(state.summary?.metrics?.text_pass_at_1)}</strong></div>
        <div><span>Pass voice sạch</span><strong>${fmt(state.summary?.metrics?.clean_voice_pass_at_1)}</strong></div>
        <div><span>Pass voice cabin</span><strong>${fmt(state.summary?.metrics?.cabin_voice_pass_at_1)}</strong></div>
        <div><span>Khoảng suy giảm voice</span><strong>${fmt(state.summary?.metrics?.voice_degradation_gap)}</strong></div>
      </div>`;
  }
  for (const item of panel.querySelectorAll("[data-episode-id]")) {
    item.addEventListener("click", () => loadEpisode(item.dataset.episodeId));
  }
}

function filtersQuery() {
  const params = new URLSearchParams();
  const filters = [
    ["track", selectedTrack()],
    ["domain", $("domainFilter").value],
    ["mode", $("modeFilter").value],
    ["failure", $("failureFilter").value],
  ];
  for (const [key, value] of filters) {
    if (value) params.set(key, value);
  }
  if ($("passFilter").value) params.set("passed", $("passFilter").value);
  return params.toString();
}

function applyClientFilters(rows) {
  return rows.filter((episode) => {
    if ($("accentFilter").value && episode.accent_region !== $("accentFilter").value) return false;
    if ($("speedFilter").value && episode.speech_speed !== $("speedFilter").value) return false;
    if ($("audioFilter").value && episode.audio_condition_id !== $("audioFilter").value) return false;
    if (state.quickFilter === "failed" && episode.passed !== false) return false;
    if (state.quickFilter === "policy" && !episode.failure_types.includes("POLICY_VIOLATION")) return false;
    if (state.quickFilter === "slot" && episode.critical_slot_passed !== false) return false;
    if (state.quickFilter === "latency" && (episode.yield_latency_ms ?? 0) < 700) return false;
    if (
      state.quickFilter === "tool" &&
      episode.tool_exact_match !== 0 &&
      !episode.failure_types.includes("TOOL_SELECTION_ERROR")
    ) return false;
    return true;
  });
}

function renderEpisodes(payload) {
  state.allEpisodes = payload.episodes || [];
  state.episodes = applyClientFilters(state.allEpisodes);
  $("episodeCount").textContent = `${state.episodes.length} / ${payload.total}`;
  renderEpisodeHead();
  $("episodeRows").innerHTML = state.episodes.map(renderEpisodeRow).join("");
  for (const row of $("episodeRows").querySelectorAll("tr")) {
    row.addEventListener("click", () => loadEpisode(row.dataset.episodeId));
  }
}

function renderEpisodeHead() {
  const retention = selectedTrack() === TRACK_RETENTION;
  $("episodeHead").innerHTML = retention
    ? `<tr><th>Episode</th><th>Kết quả</th><th>Domain</th><th>Chế độ</th><th>Vùng giọng</th><th>Tốc độ</th><th>Critical slot</th><th>Tool</th><th>Argument</th><th>State</th><th>Lỗi chính</th></tr>`
    : `<tr><th>Episode</th><th>Kết quả</th><th>Domain</th><th>Vùng giọng</th><th>Tốc độ</th><th>Yield latency</th><th>Chặn ý định cũ</th><th>Tiếp nhận sửa</th><th>Tool</th><th>Lỗi chính</th></tr>`;
}

function renderEpisodeRow(episode) {
  const passClass = episode.passed === true ? "ok" : episode.passed === false ? "fail" : "warn";
  const passLabel = episode.passed === true ? "Pass" : episode.passed === false ? "Fail" : "Chưa chấm";
  const passPill = `<span class="pill ${passClass}">${passLabel}</span>`;
  const toolText = (episode.tool_names || []).join(", ") || "";
  if (selectedTrack() === TRACK_RETENTION) {
    return `
      <tr data-episode-id="${escapeHtml(episode.episode_id)}">
        <td>${escapeHtml(episode.episode_id)}</td>
        <td>${passPill}</td>
        <td>${escapeHtml(episode.domain)}</td>
        <td>${escapeHtml(episode.mode)}</td>
        <td>${escapeHtml(episode.accent_region)}</td>
        <td>${escapeHtml(episode.speech_speed)}</td>
        <td>${escapeHtml(slotText(episode))}</td>
        <td>${escapeHtml(fmtBool(episode.tool_exact_match))}</td>
        <td>${escapeHtml(fmtBool(episode.argument_exact_match))}</td>
        <td>${escapeHtml(fmtBool(episode.state_match))}</td>
        <td>${escapeHtml(episode.primary_failure_type || "")}</td>
      </tr>`;
  }
  return `
    <tr data-episode-id="${escapeHtml(episode.episode_id)}">
      <td>${escapeHtml(episode.episode_id)}</td>
      <td>${passPill}</td>
      <td>${escapeHtml(episode.domain)}</td>
      <td>${escapeHtml(episode.accent_region)}</td>
      <td>${escapeHtml(episode.speech_speed)}</td>
      <td>${escapeHtml(fmt(episode.yield_latency_ms))}</td>
      <td>${escapeHtml(episode.old_intent_committed === false ? "Có" : episode.old_intent_committed === true ? "Không" : "N/A")}</td>
      <td>${escapeHtml(fmtBool(episode.correction_uptaken))}</td>
      <td>${escapeHtml(toolText)}</td>
      <td>${escapeHtml(episode.primary_failure_type || "")}</td>
    </tr>`;
}

function slotText(episode) {
  if (episode.critical_slot_total === undefined || episode.critical_slot_total === null) return "N/A";
  return `${episode.critical_slot_correct ?? 0}/${episode.critical_slot_total}`;
}

function fmtBool(value) {
  if (value === true || value === 1) return "Có";
  if (value === false || value === 0) return "Không";
  return "N/A";
}

function renderJson(value) {
  return `<pre>${escapeHtml(JSON.stringify(value ?? null, null, 2))}</pre>`;
}

function renderTranscript(transcript) {
  const user = transcript?.user || [];
  const assistant = transcript?.assistant || [];
  return `
    <div class="transcript">
      <div class="turn"><strong>User</strong>${escapeHtml(user.join(" "))}</div>
      <div class="turn"><strong>Assistant</strong>${escapeHtml(assistant.join(" "))}</div>
    </div>`;
}

function renderTimeline(events) {
  if (!events?.length) return '<div class="muted">Không có timeline event.</div>';
  return `
    <div class="timeline">
      ${events
        .map(
          (event) => `
            <div class="timeline-event ${event.priority ? "priority" : ""}">
              <div>${escapeHtml(event.t_ms)} ms</div>
              <div>
                <strong>${escapeHtml(event.event || event.type)}</strong>
                ${event.tool ? ` · ${escapeHtml(event.tool)}` : ""}
                ${event.text ? `<div>${escapeHtml(event.text)}</div>` : ""}
              </div>
            </div>`,
        )
        .join("")}
    </div>`;
}

function failureConclusion(detail) {
  const failure = detail.summary?.primary_failure_type;
  if (!failure) return detail.summary?.passed ? "Episode pass toàn bộ tiêu chí." : "Episode fail nhưng không có primary failure rõ ràng.";
  return failureDescriptions[failure] || `Fail do ${failure}.`;
}

function renderDetail() {
  const detail = state.selectedDetail;
  if (!detail) return;
  const body = $("detailBody");
  const tab = state.activeTab;
  if (tab === "summary") {
    body.innerHTML = `
      <div class="summary-grid">
        <div><span>Kết luận</span><strong>${escapeHtml(failureConclusion(detail))}</strong></div>
        <div><span>Kết quả</span><strong>${detail.summary.passed ? "Pass" : "Fail"}</strong></div>
        <div><span>Lỗi chính</span><strong>${escapeHtml(detail.summary.primary_failure_type || "Không có")}</strong></div>
        <div><span>Domain</span><strong>${escapeHtml(detail.summary.domain)}</strong></div>
        <div><span>Chế độ</span><strong>${escapeHtml(detail.summary.mode)}</strong></div>
        <div><span>Vùng giọng / tốc độ</span><strong>${escapeHtml(detail.summary.accent_region)} / ${escapeHtml(detail.summary.speech_speed)}</strong></div>
        <div><span>Độ trễ phản hồi</span><strong>${fmt(detail.summary.response_latency_ms)}</strong></div>
        <div><span>Độ trễ nhường lời</span><strong>${fmt(detail.summary.yield_latency_ms)}</strong></div>
      </div>`;
  } else if (tab === "conversation") {
    body.innerHTML = renderTranscript(detail.transcript);
  } else if (tab === "timeline") {
    body.innerHTML = renderTimeline(detail.timeline);
  } else if (tab === "tool_state") {
    body.innerHTML = `<div class="detail-grid">
      <div class="subpanel"><h4>Lệnh gọi công cụ</h4>${renderJson(detail.tool_calls)}</div>
      <div class="subpanel"><h4>Kết quả công cụ</h4>${renderJson(detail.tool_results)}</div>
      <div class="subpanel"><h4>Trạng thái ban đầu</h4>${renderJson(detail.initial_state)}</div>
      <div class="subpanel"><h4>Trạng thái cuối</h4>${renderJson(detail.final_state)}</div>
    </div>`;
  } else if (tab === "evidence") {
    const evidence = selectedTrack() === TRACK_RETENTION ? detail.retention : detail.repair;
    body.innerHTML = renderJson(evidence);
  } else {
    body.innerHTML = renderJson(detail.raw);
  }
}

async function loadRuns() {
  setStatus("Đang tải");
  state.runs = await fetchJson("/api/runs");
  state.presets = await fetchJson("/api/run-presets");
  state.config = await fetchJson("/api/dashboard-config");
  renderPresets();
  renderRuns();
  if (state.selectedRun) {
    await loadRun(state.selectedRun);
  } else {
    setStatus("Không có run");
    $("runTitle").textContent = "Không có run phù hợp";
  }
}

async function loadRun(runId) {
  if (!runId) return;
  state.selectedRun = runId;
  state.summary = await fetchJson(`/api/runs/${encodeURIComponent(runId)}/summary`);
  state.quickFilter = null;
  renderSummary();
  await loadEpisodes();
}

async function loadEpisodes() {
  if (!state.selectedRun) return;
  const query = filtersQuery();
  const payload = await fetchJson(
    `/api/runs/${encodeURIComponent(state.selectedRun)}/episodes${query ? `?${query}` : ""}`,
  );
  renderEpisodes(payload);
}

async function loadEpisode(episodeId) {
  const detail = await fetchJson(
    `/api/runs/${encodeURIComponent(state.selectedRun)}/episodes/${encodeURIComponent(episodeId)}`,
  );
  state.selectedDetail = detail;
  state.activeTab = "summary";
  $("detailTitle").textContent = detail.summary?.episode_id || "Chi tiết episode";
  $("detailTabs").classList.remove("hidden");
  for (const button of $("detailTabs").querySelectorAll("button")) {
    button.classList.toggle("active", button.dataset.tab === state.activeTab);
  }
  $("detailBody").classList.remove("muted");
  renderDetail();
}

async function startBenchmark() {
  $("runButton").disabled = true;
  $("jobStatus").textContent = "Đang khởi động benchmark...";
  try {
    const payload = {
      preset_id: $("presetSelect").value,
      domains: $("runDomains").value.trim() || "automotive,navigation,media_phone",
      personas: $("runPersonas").value.trim() || "vi_north_normal,vi_central_normal,vi_south_normal",
      model: $("runModel").value.trim() || null,
    };
    const job = await fetchJson("/api/benchmark-runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.activeJobId = job.job_id;
    pollJob();
  } catch (error) {
    $("jobStatus").textContent = `Không chạy được: ${error.message}`;
    $("runButton").disabled = false;
  }
}

async function pollJob() {
  if (!state.activeJobId) return;
  const job = await fetchJson(`/api/benchmark-runs/${state.activeJobId}`);
  $("jobStatus").textContent = `${job.label}: ${job.status}. Output: ${job.run_id}`;
  if (job.status === "running") {
    setTimeout(pollJob, 2000);
    return;
  }
  $("runButton").disabled = false;
  if (job.status === "failed") {
    $("jobStatus").textContent += `\n${job.stderr || job.stdout || "Không có log lỗi."}`;
  }
  await loadRuns();
  state.selectedRun = job.run_id;
  renderRuns();
  await loadRun(job.run_id);
}

function openRunModal() {
  renderPresets();
  $("runModal").classList.remove("hidden");
}

function closeRunModal() {
  $("runModal").classList.add("hidden");
}

function bindEvents() {
  $("refreshButton").addEventListener("click", loadRuns);
  $("openRunModalButton").addEventListener("click", openRunModal);
  $("closeRunModalButton").addEventListener("click", closeRunModal);
  $("benchmarkSelect").addEventListener("change", async () => {
    renderPresets();
    renderRuns();
    if (state.selectedRun) await loadRun(state.selectedRun);
  });
  $("runSelect").addEventListener("change", (event) => loadRun(event.target.value));
  for (const id of ["domainFilter", "modeFilter", "failureFilter", "passFilter"]) {
    $(id).addEventListener("change", loadEpisodes);
  }
  for (const id of ["accentFilter", "speedFilter", "audioFilter"]) {
    $(id).addEventListener("change", () => renderEpisodes({ episodes: state.allEpisodes, total: state.allEpisodes.length }));
  }
  $("domainFilter").addEventListener("change", updateRunScope);
  $("breakdownSelect").addEventListener("change", renderBreakdown);
  $("presetSelect").addEventListener("change", renderRunEstimate);
  $("runDomains").addEventListener("input", renderRunEstimate);
  $("runPersonas").addEventListener("input", renderRunEstimate);
  $("runButton").addEventListener("click", startBenchmark);
  for (const button of document.querySelectorAll(".quick-filters button")) {
    button.addEventListener("click", () => {
      state.quickFilter = button.dataset.filter === "clear" ? null : button.dataset.filter;
      renderEpisodes({ episodes: state.allEpisodes, total: state.allEpisodes.length });
    });
  }
  for (const button of $("detailTabs").querySelectorAll("button")) {
    button.addEventListener("click", () => {
      state.activeTab = button.dataset.tab;
      for (const item of $("detailTabs").querySelectorAll("button")) {
        item.classList.toggle("active", item.dataset.tab === state.activeTab);
      }
      renderDetail();
    });
  }
}

bindEvents();
loadRuns().catch((error) => {
  setStatus("Lỗi");
  $("detailBody").textContent = error.message;
});
