/* ============================================================
   Voice·Bench — Forensic Console (app)
   Vanilla JS. Reads the unchanged FastAPI /api routes.
   Two tabs: 01 Full-Duplex (FDRC), 02 Policy Gating leaderboard.
   ============================================================ */
(() => {
  "use strict";
  const H = window.VB;
  const FDRC = H.FDRC_TRACK;
  const POLICY = "voice_policy_command_gating";

  const view = document.getElementById("view");
  const tabsEl = document.getElementById("tabs");
  const sbRoute = document.getElementById("sb-route");
  const sbMeta = document.getElementById("sb-meta");

  // ---- tiny state -------------------------------------------------
  const cache = { runs: null, summary: {}, episodes: {} };
  const explorerFilters = { validity: "", passed: "", domain: "", failure: "" };
  const explorerSort = { key: "episode_id", dir: 1 };
  let showDiagnosticRuns = false;

  // ---- utils ------------------------------------------------------
  const esc = (s) =>
    String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  const el = (html) => {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  };

  async function getJSON(url) {
    const res = await fetch(url);
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(detail || ("HTTP " + res.status));
    }
    return res.json();
  }

  function nav(route) { location.hash = H.buildHash(route); }

  function setStatus(routeText, meta) {
    sbRoute.textContent = routeText;
    if (meta !== undefined) sbMeta.textContent = meta;
  }

  function persona(row) {
    const parts = [row.accent_region, row.speech_speed].filter(Boolean);
    return parts.length ? parts.join("·") : "—";
  }

  // ---- data -------------------------------------------------------
  async function loadRuns() {
    if (cache.runs) return cache.runs;
    const all = await getJSON("/api/runs");
    cache.runs = all.filter(H.isFdrcRun);
    return cache.runs;
  }
  async function loadSummary(runId) {
    if (cache.summary[runId]) return cache.summary[runId];
    const s = await getJSON(
      `/api/runs/${encodeURIComponent(runId)}/summary?track=${FDRC}`
    );
    cache.summary[runId] = s;
    return s;
  }
  function loadEpisodes(runId, filters) {
    const q = new URLSearchParams({ track: FDRC });
    if (filters.validity) q.set("validity", filters.validity);
    if (filters.passed === "true" || filters.passed === "false") q.set("passed", filters.passed);
    if (filters.domain) q.set("domain", filters.domain);
    if (filters.failure) q.set("failure", filters.failure);
    return getJSON(`/api/runs/${encodeURIComponent(runId)}/episodes?${q}`);
  }

  // ---- shared fragments ------------------------------------------
  function stateBlock({ glyph, title, body, error }) {
    return `<div class="state ${error ? "error" : ""}">
      <div class="glyph">${glyph || "∅"}</div>
      <h2>${esc(title)}</h2>
      <p>${body || ""}</p>
    </div>`;
  }

  function statusChip(status) {
    const tone = H.statusTone(status);
    const label = { pass: "PASS", fail: "FAIL", invalid: "INVALID", unscored: "—" }[status];
    return `<span class="chip ${tone}"><span class="dotpip"></span>${label}</span>`;
  }

  function runOption(r, runId) {
    return `<option value="${esc(r.run_id)}" ${r.run_id === runId ? "selected" : ""}>${esc(
      r.run_id
    )} · ${r.episode_count} ep</option>`;
  }

  function runSelector(runs, runId) {
    const groups = H.groupRunsByKind(runs);
    const benchmark = groups.find((g) => g.kind === "benchmark");
    const diagnostics = groups.filter((g) => g.kind !== "benchmark");
    const diagnosticCount = diagnostics.reduce((n, g) => n + g.runs.length, 0);

    let body;
    if (!showDiagnosticRuns) {
      const benchRuns = benchmark ? benchmark.runs : [];
      body = benchRuns.length
        ? benchRuns.map((r) => runOption(r, runId)).join("")
        : `<option value="" disabled selected>Chưa có benchmark run — bật "run chẩn đoán"</option>`;
    } else {
      body = groups
        .map(
          (g) =>
            `<optgroup label="${esc(g.label)} (${g.runs.length})">` +
            g.runs.map((r) => runOption(r, runId)).join("") +
            `</optgroup>`
        )
        .join("");
    }

    const toggle = diagnosticCount
      ? `<label class="run-toggle" style="display:flex;gap:6px;align-items:center;font-size:12px;opacity:.8;margin-top:6px">
          <input type="checkbox" id="show-all-runs" ${showDiagnosticRuns ? "checked" : ""}/>
          Hiện run chẩn đoán (${diagnosticCount})
        </label>`
      : "";

    return `<div class="field">
      <label>FDRC Run</label>
      <select id="run-select">${body}</select>
      ${toggle}
    </div>`;
  }

  // ================================================================
  // VIEW: Overview
  // ================================================================
  async function renderOverview(route) {
    setStatus("fdrc / overview", "loading runs…");
    view.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;

    let runs;
    try {
      runs = await loadRuns();
    } catch (e) {
      view.innerHTML = stateBlock({ glyph: "⚠", title: "Không tải được /api/runs", body: esc(e.message), error: true });
      return;
    }
    if (!runs.length) {
      view.innerHTML = stateBlock({
        glyph: "∅",
        title: "Chưa có FDRC run nào",
        body: "Thư mục <code>results/</code> chưa có run nào thuộc track Full-Duplex Repair-to-Commit.",
      });
      return;
    }

    // NOTE: defaultRunId relies on /api/runs being sorted by updated_at desc
    // (backend list_runs does this). "First benchmark" = newest real score.
    const runId = route.runId && runs.some((r) => r.run_id === route.runId)
      ? route.runId
      : H.defaultRunId(runs);

    // If the active run isn't a benchmark run (e.g. opened via URL), reveal
    // diagnostics so it shows up in the dropdown instead of vanishing.
    const activeRun = runs.find((r) => r.run_id === runId);
    if (activeRun && H.effectiveRunKind(activeRun) !== "benchmark") {
      showDiagnosticRuns = true;
    }

    view.innerHTML = `<div class="controls">${runSelector(runs, runId)}
      <div class="spacer"></div>
      <button class="btn" id="go-episodes">Episode Explorer →</button>
    </div>
    <div id="ov-body"><div class="skeleton"></div></div>`;

    function wireRunControls() {
      document.getElementById("run-select").addEventListener("change", (e) =>
        nav({ tab: "fdrc", view: "overview", runId: e.target.value })
      );
      const showAllEl = document.getElementById("show-all-runs");
      if (showAllEl) {
        showAllEl.addEventListener("change", (e) => {
          showDiagnosticRuns = e.target.checked;
          // Hiding diagnostics while a diagnostic run is active would leave the
          // dropdown pointing at a benchmark run while the page still shows the
          // diagnostic run's data. Navigate to the default benchmark run so the
          // dropdown and content stay in sync.
          const active = runs.find((r) => r.run_id === runId);
          if (!showDiagnosticRuns && active && H.effectiveRunKind(active) !== "benchmark") {
            nav({ tab: "fdrc", view: "overview", runId: H.defaultRunId(runs) });
            return;
          }
          const field = document.querySelector(".controls .field");
          field.outerHTML = runSelector(runs, runId);
          wireRunControls();
        });
      }
    }
    wireRunControls();
    document.getElementById("go-episodes").addEventListener("click", () =>
      nav({ tab: "fdrc", view: "episodes", runId })
    );

    setStatus(`fdrc / overview / ${runId}`, "loading summary…");
    let summary, episodesResp;
    try {
      [summary, episodesResp] = await Promise.all([
        loadSummary(runId),
        loadEpisodes(runId, {}),
      ]);
    } catch (e) {
      document.getElementById("ov-body").innerHTML = stateBlock({
        glyph: "⚠", title: "Không tải được summary", body: esc(e.message), error: true,
      });
      return;
    }

    const rep = H.deriveReportability(summary);
    const vs = H.validitySummary(episodesResp.episodes);
    const pf = summary.pass_fail || { passed: 0, failed: 0, unscored: 0 };

    const banner = `<div class="banner tone-${rep.tone}">
      <div class="banner-icon">${rep.tone === "pass" ? "◆" : rep.tone === "warn" ? "▲" : "■"}</div>
      <div class="banner-body">
        <h3>${esc(rep.label)}</h3>
        <p>${esc(rep.note)}</p>
      </div>
      <div class="banner-meta">
        <span>provenance<b>${esc(summary.data_provenance || "—")}</b></span>
        <span>run kind<b>${esc(summary.run_kind || "—")}</b></span>
        <span>source<b>${esc(summary.metric_source || "—")}</b></span>
      </div>
    </div>`;

    const statline = `<div class="statline">
      <div class="stat"><span class="k">Episodes</span><span class="v">${summary.episode_count ?? "—"}</span></div>
      <div class="stat"><span class="k">Validity</span><span class="v">${
        vs.rate === null ? "—" : H.fmtPct(vs.rate)
      } <small>${vs.valid}/${vs.known || vs.total}</small></span></div>
      <div class="stat"><span class="k">Pass</span><span class="v" style="color:var(--pass)">${pf.passed}</span></div>
      <div class="stat"><span class="k">Fail</span><span class="v" style="color:var(--fail)">${pf.failed}</span></div>
      <div class="stat"><span class="k">Unscored</span><span class="v muted">${pf.unscored}</span></div>
    </div>`;

    document.getElementById("ov-body").innerHTML =
      banner + statline + renderMetricGroups(summary) + renderPolicyExtras(summary);
    const ovBody = document.getElementById("ov-body");
    function onMetricActivate(target) {
      const card = target.closest(".metric-clickable");
      if (!card) return;
      openMetricModal(runId, card.getAttribute("data-key"));
    }
    ovBody.addEventListener("click", (e) => onMetricActivate(e.target));
    ovBody.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onMetricActivate(e.target); }
    });
    setStatus(`fdrc / overview / ${runId}`, `${summary.episode_count ?? 0} episodes`);
  }

  function metricStatusClass(status) {
    if (status === "ok" || status === "pass") return "s-pass";
    if (status === "warn" || status === "nullable" || status === "null") return "";
    if (status === "violation" || status === "fail") return "s-fail";
    return "";
  }

  function renderMetricGroups(summary) {
    const catalog = summary.metric_catalog || [];
    const byKey = {};
    for (const m of catalog) byKey[m.key] = m;
    let groups = summary.metric_groups || [];
    // Prefer the FDRC-relevant groups; fall back to all if shape differs.
    const wanted = ["fdrc", "latency", "contract", "tool_state", "policy", "overview"];
    if (groups.length) {
      groups = groups.slice().sort((a, b) => {
        const ia = wanted.findIndex((w) => String(a.id).includes(w));
        const ib = wanted.findIndex((w) => String(b.id).includes(w));
        return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
      });
    }
    if (!groups.length) {
      return catalogGrid(catalog);
    }
    return groups
      .map((g) => {
        const cards = (g.metric_keys || [])
          .map((k) => byKey[k])
          .filter(Boolean)
          .map(metricCard)
          .join("");
        if (!cards) return "";
        return `<div class="group-label">${esc(g.label || g.id)}</div>
          <div class="metric-grid">${cards}</div>`;
      })
      .join("");
  }

  function catalogGrid(catalog) {
    return `<div class="metric-grid">${catalog.map(metricCard).join("")}</div>`;
  }

  // Policy-gating-only views: the decision confusion matrix and the
  // state-conditioned pair comparison. Render nothing for other tracks.
  function renderPolicyExtras(summary) {
    const matrix = summary.decision_confusion_matrix || [];
    const pairs = summary.state_pairs || [];
    if (!matrix.length && !pairs.length) return "";
    const decisions = ["execute", "clarify", "refuse", "defer"];
    const head = decisions.map((d) => `<th>${esc(d)}</th>`).join("");
    const rows = decisions.map((exp) => {
      const cells = decisions.map((act) => {
        const n = H.confusionCell(matrix, exp, act);
        const diag = exp === act && n > 0 ? ' class="s-pass"' : (n > 0 ? ' class="s-fail"' : "");
        return `<td${diag}>${n}</td>`;
      }).join("");
      return `<tr><th>${esc(exp)}</th>${cells}</tr>`;
    }).join("");
    const matrixHtml = matrix.length
      ? `<div class="group-label">Decision confusion matrix (kỳ vọng × agent)</div>
         <div class="table-wrap"><table class="episodes">
         <thead><tr><th>Expected ↓ / Agent →</th>${head}</tr></thead>
         <tbody>${rows}</tbody></table></div>`
      : "";
    const pairRows = pairs.map((p) => {
      const m = p.members || [];
      const cell = (x) => x
        ? `${esc(x.expected)} → <span class="${x.correct ? "s-pass" : "s-fail"}">${esc(x.agent)}</span>`
        : "—";
      return `<tr>
        <td>${esc(p.user_utterance || p.state_pair_id)}</td>
        <td>${cell(m[0])}</td>
        <td>${cell(m[1])}</td>
        <td>${p.pair_pass ? "✓" : "✗"}</td>
      </tr>`;
    }).join("");
    const pairHtml = pairs.length
      ? `<div class="group-label">State-conditioned pairs</div>
         <div class="table-wrap"><table class="episodes">
         <thead><tr><th>Câu lệnh</th><th>State A</th><th>State B</th><th>Pair pass</th></tr></thead>
         <tbody>${pairRows}</tbody></table></div>`
      : "";
    return matrixHtml + pairHtml;
  }

  // Color a metric card: contract violations / missing → status-based; otherwise
  // direction-aware (good-high vs bad-high) so a high violation rate shows red,
  // not green. Counts/latency/unknown rates stay neutral.
  function metricColorClass(m) {
    if (m.status === "invalid" || m.status === "violation" || m.status === "fail") return "s-fail";
    if (m.value === null || m.value === undefined) return metricStatusClass(m.status);
    return H.metricTone(m.key, m.value, m.unit);
  }

  function metricCard(m) {
    const isNull = m.value === null || m.value === undefined;
    let valHtml;
    if (isNull) {
      valHtml = `<div class="metric-value null">N/A</div><div class="metric-reason">${esc(H.nullReasonText(m.null_reason))}</div>`;
    } else if (m.key === "metric_contract.benchmark_status") {
      valHtml = `<div class="metric-value metric-status-text">${esc(H.contractStatusText(m.value))}</div>`;
    } else {
      valHtml = `<div class="metric-value">${esc(H.fmtMetric(m))}</div>`;
    }
    const denom = m.denominator ? `n=${esc(m.denominator)}` : "";
    return `<div class="metric ${metricColorClass(m)} metric-clickable" data-key="${esc(m.key)}" role="button" tabindex="0">
      <div class="metric-label">${esc(m.label || m.key)}</div>
      ${valHtml}
      <div class="metric-foot"><span>${esc(m.group || "")}</span><span>${denom}</span></div>
    </div>`;
  }

  async function fetchExplain(runId, key) {
    return getJSON(
      `/api/runs/${encodeURIComponent(runId)}/metrics/${encodeURIComponent(key)}/explain?track=${FDRC}`
    );
  }

  function closeMetricModal() {
    const m = document.getElementById("metric-modal");
    if (m) m.remove();
    document.removeEventListener("keydown", onModalKeydown);
  }

  function onModalKeydown(e) {
    if (e.key === "Escape") closeMetricModal();
  }

  function explainEpisodeRow(runId, ep) {
    const persona = [ep.accent_region, ep.speech_speed].filter(Boolean).join("·") || "—";
    const status = ep.passed === true ? "pass" : ep.passed === false ? "fail" : "—";
    return `<tr>
      <td><a href="${H.buildHash({ tab: "fdrc", view: "episode", runId, episodeId: ep.episode_id })}">${esc(ep.episode_id)}</a></td>
      <td>${esc(ep.domain || "—")}</td>
      <td>${esc(persona)}</td>
      <td>${esc(status)}</td>
    </tr>`;
  }

  function renderMetricModal(runId, data) {
    let bodyHtml;
    if (!data.supported) {
      bodyHtml = `<p class="modal-note">${esc(data.note_vi || "Không có phân tích theo episode.")}</p>`;
    } else {
      const ratio = H.formatRatio(data.numerator, data.denominator);
      const fmtVal = (v) =>
        data.unit === "count" ? H.fmtInt(v)
        : data.unit === "ms" ? H.fmtMs(v)
        : H.fmtPct(v);
      const headline = fmtVal(data.value);              // displayed value (matches the card)
      const recomputed = fmtVal(data.recomputed_value); // recomputed from episodes = num/denom
      const eps = (data.numerator_episodes || []);
      const epTable = eps.length
        ? `<table class="modal-table"><thead><tr><th>episode</th><th>domain</th><th>persona</th><th>kết quả</th></tr></thead>
            <tbody>${eps.map((ep) => explainEpisodeRow(runId, ep)).join("")}</tbody></table>`
        : `<p class="modal-note">Tử số rỗng — không episode nào thỏa điều kiện.</p>`;
      const explorerLink = data.explorer_filter
        ? `<a class="btn btn-ghost" id="modal-explorer" href="${H.buildHash({ tab: "fdrc", view: "episodes", runId })}">Mở Episode Explorer →</a>`
        : "";
      const divergeWarn = data.value_matches_recomputed === false
        ? `<div class="modal-diverge">⚠ Giá trị hiển thị (${esc(headline)}, từ ${esc(data.metric_source)}) KHÁC giá trị tính lại từ episode (${esc(recomputed)} = ${esc(ratio)}). Cần kiểm tra metrics.json.</div>`
        : "";
      bodyHtml = `
        <div class="modal-formula"><code>${esc(data.formula_vi)}</code></div>
        <div class="modal-calc">
          <span class="modal-calc-num">${esc(headline)}</span>
          <span class="modal-calc-eq">=</span>
          <span class="modal-calc-ratio">${esc(ratio)}</span>
          <span class="modal-calc-lbl">(${esc(data.numerator_label_vi)} ÷ ${esc(data.row_set_label_vi)})</span>
        </div>
        ${divergeWarn}
        <div class="modal-src">nguồn: ${esc(data.metric_source)} · hash ${data.metrics_hash_valid ? "khớp" : "KHÔNG khớp"} · scope: ${esc(data.scope)} · tính lại: ${esc(recomputed)}</div>
        <h4>Episode tử số (${eps.length})</h4>
        ${epTable}
        ${explorerLink}`;
    }
    return `<div class="modal-backdrop" id="metric-modal">
      <div class="modal" role="dialog" aria-modal="true" aria-label="${esc(data.label || data.key)}">
        <div class="modal-head">
          <div><div class="modal-title">${esc(data.label || data.key)}</div>
          <div class="modal-key">${esc(data.key)}</div></div>
          <button class="modal-x" id="modal-close" aria-label="Đóng">✕</button>
        </div>
        ${data.description ? `<p class="modal-desc">${esc(data.description)}</p>` : ""}
        ${bodyHtml}
      </div>
    </div>`;
  }

  async function openMetricModal(runId, key) {
    closeMetricModal();
    const shell = el(`<div class="modal-backdrop" id="metric-modal"><div class="modal"><div class="skeleton"></div></div></div>`);
    document.body.appendChild(shell);
    document.addEventListener("keydown", onModalKeydown);
    let data;
    try {
      data = await fetchExplain(runId, key);
    } catch (e) {
      shell.querySelector(".modal").innerHTML =
        `<div class="modal-head"><div class="modal-title">Lỗi</div><button class="modal-x" id="modal-close">✕</button></div><p class="modal-note">${esc(e.message)}</p>`;
      const closeBtn = shell.querySelector("#modal-close");
      if (closeBtn) closeBtn.addEventListener("click", closeMetricModal);
      shell.addEventListener("click", (ev) => { if (ev.target === shell) closeMetricModal(); });
      return;
    }
    shell.outerHTML = renderMetricModal(runId, data);
    const modal = document.getElementById("metric-modal");
    modal.addEventListener("click", (ev) => {
      if (ev.target === modal) closeMetricModal();
    });
    document.getElementById("modal-close").addEventListener("click", closeMetricModal);
    const explorer = document.getElementById("modal-explorer");
    if (explorer) {
      explorer.addEventListener("click", () => {
        const f = (data && data.explorer_filter) || {};
        explorerFilters.validity = f.validity || "";
        explorerFilters.passed = f.passed || "";
        explorerFilters.failure = f.failure || "";
        explorerFilters.domain = f.domain || "";
        closeMetricModal();
      });
    }
  }

  // ================================================================
  // VIEW: Episode Explorer
  // ================================================================
  async function renderEpisodes(route) {
    const runId = route.runId;
    setStatus(`fdrc / episodes / ${runId}`, "loading…");
    view.innerHTML = `
      <button class="crumb" id="back-ov">← Overview</button>
      <div class="section-head"><h2>Episode Explorer</h2><span class="count" id="ep-count">—</span></div>
      <div class="controls" id="ep-filters"></div>
      <div id="ep-table"><div class="skeleton"></div></div>`;

    document.getElementById("back-ov").addEventListener("click", () =>
      nav({ tab: "fdrc", view: "overview", runId })
    );

    let summary;
    try { summary = await loadSummary(runId); } catch (_) { summary = {}; }
    renderEpFilters(summary);
    await refreshEpisodeTable(runId);
  }

  function renderEpFilters(summary) {
    const domains = (summary.pass_by_domain || []).map((d) => d.key).filter(Boolean);
    const failures = (summary.failure_counts || []).map((f) => f.key).filter(Boolean);
    const sel = (id, label, value, opts) => `<div class="field">
      <label>${label}</label>
      <select id="${id}">${opts
        .map((o) => `<option value="${esc(o.v)}" ${o.v === value ? "selected" : ""}>${esc(o.t)}</option>`)
        .join("")}</select></div>`;

    document.getElementById("ep-filters").innerHTML =
      sel("f-validity", "Validity", explorerFilters.validity, [
        { v: "", t: "all" }, { v: "valid", t: "valid" }, { v: "invalid", t: "invalid" },
      ]) +
      sel("f-passed", "Result", explorerFilters.passed, [
        { v: "", t: "all" }, { v: "true", t: "pass" }, { v: "false", t: "fail" },
      ]) +
      sel("f-domain", "Domain", explorerFilters.domain,
        [{ v: "", t: "all" }].concat(domains.map((d) => ({ v: d, t: d })))) +
      sel("f-failure", "Failure", explorerFilters.failure,
        [{ v: "", t: "all" }].concat(failures.map((f) => ({ v: f, t: f }))));

    const runId = currentRoute().runId;
    const bind = (id, key) =>
      document.getElementById(id).addEventListener("change", (e) => {
        explorerFilters[key] = e.target.value;
        refreshEpisodeTable(runId);
      });
    bind("f-validity", "validity");
    bind("f-passed", "passed");
    bind("f-domain", "domain");
    bind("f-failure", "failure");
  }

  const SORTABLE = [
    { key: "episode_id", label: "Episode", cls: "" },
    { key: "domain", label: "Domain", cls: "" },
    { key: "persona", label: "Persona", cls: "" },
    { key: "fdrc_valid", label: "Validity", cls: "" },
    { key: "passed", label: "Result", cls: "" },
    { key: "yield_latency_ms", label: "Yield ms", cls: "cell-num" },
    { key: "primary_failure_type", label: "Primary failure", cls: "" },
  ];

  async function refreshEpisodeTable(runId) {
    const host = document.getElementById("ep-table");
    host.innerHTML = `<div class="skeleton"></div>`;
    let resp;
    try {
      resp = await loadEpisodes(runId, explorerFilters);
    } catch (e) {
      host.innerHTML = stateBlock({ glyph: "⚠", title: "Không tải được episodes", body: esc(e.message), error: true });
      return;
    }
    const rows = resp.episodes.slice();
    const cnt = document.getElementById("ep-count");
    if (cnt) cnt.textContent = `${resp.count} / ${resp.total}`;
    setStatus(`fdrc / episodes / ${runId}`, `${resp.count} of ${resp.total}`);

    if (!rows.length) {
      host.innerHTML = stateBlock({ glyph: "∅", title: "Không có episode khớp filter", body: "Thử nới lỏng bộ lọc." });
      return;
    }

    sortRows(rows);

    const head = SORTABLE.map((c) => {
      const active = explorerSort.key === c.key;
      const arrow = active ? `<span class="arrow">${explorerSort.dir > 0 ? "▲" : "▼"}</span>` : "";
      return `<th data-sort="${c.key}" class="${c.cls}">${c.label} ${arrow}</th>`;
    }).join("");

    const body = rows
      .map((r) => {
        const st = H.episodeStatus(r);
        const vChip = r.fdrc_valid === false
          ? `<span class="chip warn">INVALID</span>`
          : r.fdrc_valid === true
          ? `<span class="chip pass">VALID</span>`
          : `<span class="chip gray">—</span>`;
        const fail = r.primary_failure_type
          ? `<span class="chip fail">${esc(r.primary_failure_type)}</span>`
          : `<span class="cell-muted">—</span>`;
        return `<tr data-ep="${esc(r.episode_id)}">
          <td class="cell-id" title="${esc(r.episode_id)}">${esc(r.episode_id)}</td>
          <td>${esc(r.domain || "—")}</td>
          <td class="cell-muted">${esc(persona(r))}</td>
          <td>${vChip}</td>
          <td>${statusChip(st)}</td>
          <td class="cell-num">${r.yield_latency_ms == null ? "—" : H.fmtMs(r.yield_latency_ms)}</td>
          <td>${fail}</td>
        </tr>`;
      })
      .join("");

    host.innerHTML = `<div class="table-wrap"><table class="episodes">
      <thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;

    host.querySelectorAll("thead th").forEach((th) =>
      th.addEventListener("click", () => {
        const key = th.getAttribute("data-sort");
        if (explorerSort.key === key) explorerSort.dir *= -1;
        else { explorerSort.key = key; explorerSort.dir = 1; }
        refreshEpisodeTable(runId);
      })
    );
    host.querySelectorAll("tbody tr").forEach((tr) =>
      tr.addEventListener("click", () =>
        nav({ tab: "fdrc", view: "episode", runId, episodeId: tr.getAttribute("data-ep") })
      )
    );
  }

  function sortRows(rows) {
    const k = explorerSort.key;
    const dir = explorerSort.dir;
    rows.sort((a, b) => {
      let va = k === "persona" ? persona(a) : a[k];
      let vb = k === "persona" ? persona(b) : b[k];
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
      return String(va).localeCompare(String(vb)) * dir;
    });
  }

  // ================================================================
  // VIEW: Episode Detail
  // ================================================================
  async function renderEpisodeDetail(route) {
    const { runId, episodeId } = route;
    setStatus(`fdrc / episode / ${episodeId}`, "loading…");
    view.innerHTML = `<button class="crumb" id="back-eps">← Episodes</button>
      <div class="skeleton"></div><div class="skeleton"></div>`;
    document.getElementById("back-eps").addEventListener("click", () =>
      nav({ tab: "fdrc", view: "episodes", runId })
    );

    let d;
    try {
      d = await getJSON(
        `/api/runs/${encodeURIComponent(runId)}/episodes/${encodeURIComponent(episodeId)}`
      );
    } catch (e) {
      view.innerHTML =
        `<button class="crumb" id="back-eps2">← Episodes</button>` +
        stateBlock({ glyph: "⚠", title: "Không tải được episode", body: esc(e.message), error: true });
      document.getElementById("back-eps2").addEventListener("click", () =>
        nav({ tab: "fdrc", view: "episodes", runId }));
      return;
    }

    const s = d.summary || {};
    const repair = d.repair || {};
    const validity = d.fdrc_validity || {};
    const scores = d.scores || {};
    const contract = d.contract || {};
    const status = H.episodeStatus(s);
    const yl = s.yield_latency_ms;

    const header = `<div class="ep-header">
      <div class="ep-id">${esc(s.episode_id || episodeId)}</div>
      <div class="ep-tags">
        ${statusChip(status)}
        ${validity.valid === false ? `<span class="chip warn">INVALID</span>` : `<span class="chip pass">VALID</span>`}
        ${s.primary_failure_type ? `<span class="chip fail">${esc(s.primary_failure_type)}</span>` : ""}
        <span class="chip">${esc(s.domain || "—")}</span>
        <span class="chip gray">${esc(persona(s))}</span>
        <span class="chip">${esc(s.audio_condition_id || "")}</span>
      </div>
      <div class="ep-intent">
        <span>initial</span><b>${esc(intentText(contract.initial_intent) || "—")}</b>
        <span class="arrow">→ repair</span><b>${esc(contract.repair_utterance || repair.correction_text || "—")}</b>
      </div>
    </div>`;

    const contractPanel = `<div class="panel"><h3>Overlay Contract</h3>
      <dl class="kv">
        <dt>task</dt><dd>${esc(contract.task_description || "—")}</dd>
        <dt>initial utter</dt><dd>${esc(contract.initial_spoken_utterance || "—")}</dd>
        <dt>repair utter</dt><dd>${esc(contract.repair_utterance || "—")}</dd>
        <dt>final intent</dt><dd>${esc(contract.final_intent || repair.final_intent || "—")}</dd>
        <dt>expected tool</dt><dd>${esc(summarizeCalls(contract.expected_tool_calls))}</dd>
        <dt>forbidden tool</dt><dd>${esc(summarizeCalls(contract.forbidden_tool_calls))}</dd>
      </dl></div>`;

    const verdictPanel = `<div class="panel"><h3>Verdict</h3>
      ${assertRow(validity.valid !== false, `validity: ${esc(validity.status || (validity.valid ? "VALID" : "INVALID"))}`, validity.valid === undefined)}
      ${assertRow(scores.task_pass === 1, "task pass", scores.task_pass == null)}
      ${assertRow(scores.policy_pass === 1, "policy pass", scores.policy_pass == null)}
      ${assertRow(scores.voice_pass === 1, "voice pass", scores.voice_pass == null)}
      ${assertRow(scores.final_pass === 1, "final pass", scores.final_pass == null)}
      <div class="assert ${yl == null ? "na" : yl <= 1000 ? "ok" : "bad"}">
        <span class="mark">${yl == null ? "·" : "◷"}</span>
        <span class="txt">yield latency: ${yl == null ? "—" : H.fmtMs(yl)}</span>
      </div>
    </div>`;

    const timeline = renderTimeline(d.timeline || [], { yieldLatency: yl });

    const repairPanel = `<div class="panel"><h3>Repair / Commit Safety</h3>
      ${assertRow(repair.assistant_speaking_before_interrupt !== false, "assistant speaking before interrupt", repair.assistant_speaking_before_interrupt == null)}
      ${assertRow(repair.correction_uptaken === true, "correction uptaken", repair.correction_uptaken == null)}
      ${assertRow(repair.old_intent_committed === false, "old intent NOT committed", repair.old_intent_committed == null)}
      ${assertRow(repair.forbidden_tool_called === false, "forbidden tool NOT called", repair.forbidden_tool_called == null)}
      ${assertRow(repair.duplicate_final_commit === false, "no duplicate final commit", repair.duplicate_final_commit == null)}
      ${assertRow(!H.earlyCommit(d.timeline || []), "no early commit (before gate)", false)}
    </div>`;

    const diffPanel = renderToolStateDiff(d);

    const failurePanel = (d.failure_types && d.failure_types.length)
      ? `<div class="panel"><h3>Failure Types</h3><div class="row">${d.failure_types
          .map((f) => `<span class="chip fail">${esc(f)}</span>`).join("")}</div></div>`
      : "";

    const raw = `<details class="raw"><summary>Raw episode JSON</summary>
      <pre class="code">${esc(JSON.stringify(d.raw || {}, null, 2))}</pre></details>`;

    view.innerHTML =
      `<button class="crumb" id="back-eps3">← Episodes</button>` +
      header +
      `<div class="two-col">${verdictPanel}${repairPanel}</div>` +
      timeline +
      `<div class="two-col">${contractPanel}${diffPanel}</div>` +
      failurePanel +
      raw;

    document.getElementById("back-eps3").addEventListener("click", () =>
      nav({ tab: "fdrc", view: "episodes", runId }));
    setStatus(`fdrc / episode / ${episodeId}`, status.toUpperCase());
  }

  function assertRow(ok, text, na) {
    const cls = na ? "na" : ok ? "ok" : "bad";
    const mark = na ? "·" : ok ? "✓" : "✗";
    return `<div class="assert ${cls}"><span class="mark">${mark}</span><span class="txt">${esc(text)}</span></div>`;
  }

  function intentText(intent) {
    if (!intent) return "";
    if (typeof intent === "string") return intent;
    if (intent.tool) return `${intent.tool}(${argsText(intent.args)})`;
    return JSON.stringify(intent);
  }
  function argsText(args) {
    if (!args || typeof args !== "object") return "";
    return Object.entries(args).map(([k, v]) => `${k}=${v}`).join(", ");
  }
  function summarizeCalls(calls) {
    if (!calls || !calls.length) return "—";
    return calls.map((c) => `${c.tool || c.name}(${argsText(c.args)})`).join("  ");
  }

  function renderToolStateDiff(d) {
    const repair = d.repair || {};
    const observed = (d.tool_calls || []).map((c) => ({ tool: c.tool, args: c.args }));
    const expected = (d.contract && d.contract.expected_tool_calls) || [];
    const stateDiff = d.state_diff || {};
    const warnings = [];
    if (repair.old_intent_committed) warnings.push("OLD_INTENT_COMMITTED");
    if (repair.forbidden_tool_called) warnings.push("FORBIDDEN_TOOL_CALL");
    if (repair.correction_uptaken === false) warnings.push("CORRECTION_NOT_UPTAKEN");
    if (stateDiff.matches === false) warnings.push("FINAL_STATE_MISMATCH");

    const warnHtml = warnings.length
      ? `<div class="row" style="margin-bottom:12px">${warnings
          .map((w) => `<span class="chip fail">${esc(w)}</span>`).join("")}</div>`
      : `<div class="row" style="margin-bottom:12px"><span class="chip pass">no side-effect flags</span></div>`;

    const obsBad = warnings.length > 0;
    const stateBody = (stateDiff.diffs && stateDiff.diffs.length)
      ? JSON.stringify(stateDiff.diffs, null, 2)
      : JSON.stringify(d.summary && d.summary.final_intent ? { final_intent: d.summary.final_intent } : (d.raw && d.raw.final_state) || {}, null, 2);

    return `<div class="panel"><h3>Tool / State Diff</h3>
      ${warnHtml}
      <div class="diff">
        <div class="col"><h4>Expected tool</h4>
          <pre class="code expected">${esc(expected.length ? JSON.stringify(expected, null, 2) : "—")}</pre></div>
        <div class="col"><h4>Observed tool</h4>
          <pre class="code ${obsBad ? "bad" : "observed"}">${esc(observed.length ? JSON.stringify(observed, null, 2) : "(none)")}</pre></div>
      </div>
      <div class="col" style="margin-top:12px"><h4>State diff</h4>
        <pre class="code ${stateDiff.matches === false ? "bad" : "observed"}">${esc(stateBody)}</pre></div>
    </div>`;
  }

  // ---- SVG timeline ----------------------------------------------
  function renderTimeline(events, opts) {
    const evs = (events || []).filter((e) => typeof e.t_ms === "number");
    if (!evs.length) {
      return `<div class="timeline-card">` +
        stateBlock({ glyph: "⌁", title: "Không có timeline event", body: "Episode này thiếu voice_events có t_ms." }) +
        `</div>`;
    }

    const W = 1040, padL = 96, padR = 24, top = 30, laneH = 50;
    const lanes = [
      { key: "user", label: "User" },
      { key: "assistant", label: "Assistant" },
      { key: "events", label: "Events" },
      { key: "tool", label: "Tool / State" },
    ];
    const laneIndex = {}; lanes.forEach((l, i) => (laneIndex[l.key] = i));
    const innerH = lanes.length * laneH;
    const H_ = top + innerH + 26;
    const duration = H.timelineDuration(evs);
    const x = H.scaler(duration, padL, W - padR);
    const laneY = (k) => top + laneIndex[k] * laneH;

    let svg = `<svg class="tl-svg" viewBox="0 0 ${W} ${H_}" width="100%" preserveAspectRatio="xMinYMin meet" style="min-width:760px">`;

    // lane backgrounds + labels
    lanes.forEach((l, i) => {
      svg += `<rect class="tl-lane-bg ${i % 2 ? "alt" : ""}" x="${padL}" y="${laneY(l.key)}" width="${W - padL - padR}" height="${laneH}"/>`;
      svg += `<text class="tl-lane-label" x="${padL - 10}" y="${laneY(l.key) + laneH / 2 + 3}" text-anchor="end">${esc(l.label)}</text>`;
    });

    // axis grid + ticks
    const step = duration > 8000 ? 2000 : duration > 4000 ? 1000 : 500;
    for (let t = 0; t <= duration; t += step) {
      const gx = x(t);
      svg += `<line class="tl-grid" x1="${gx}" y1="${top}" x2="${gx}" y2="${top + innerH}"/>`;
      svg += `<text class="tl-axis-tick" x="${gx}" y="${top - 8}" text-anchor="middle">${t}ms</text>`;
    }

    // repair window
    const rw = H.repairWindow(evs);
    if (rw) {
      svg += `<rect class="tl-repair" x="${x(rw.start)}" y="${top}" width="${Math.max(2, x(rw.end) - x(rw.start))}" height="${innerH}"/>`;
      svg += `<text class="tl-axis-tick" x="${x(rw.start) + 4}" y="${top + 11}" fill="var(--warn)">repair window</text>`;
    }

    // yield bracket
    const interrupt = H.findEvent(evs, (e) => /interrupt/.test(e.event || ""));
    const yielded = H.findEvent(evs, (e) => /yield/.test(e.event || "") && !/should_yield/.test(e.event || ""));
    if (interrupt && yielded) {
      const yy = laneY("events") + laneH - 8;
      svg += `<line class="tl-threshold" x1="${x(interrupt.t_ms)}" y1="${yy}" x2="${x(yielded.t_ms)}" y2="${yy}"/>`;
      svg += `<text class="tl-axis-tick" x="${(x(interrupt.t_ms) + x(yielded.t_ms)) / 2}" y="${yy - 4}" text-anchor="middle" fill="var(--pass)">yield ${H.fmtMs(opts && opts.yieldLatency != null ? opts.yieldLatency : yielded.t_ms - interrupt.t_ms)}</text>`;
    }

    const early = H.earlyCommit(evs);

    // markers
    evs.forEach((e) => {
      const c = H.classifyEvent(e.event);
      const ly = laneY(c.lane);
      const cx = x(e.t_ms);
      const isEarlyTool = c.cls === "tool" && early && (() => {
        const gate = H.findEvent(evs, (g) => /allowed_after|repair_transcript_done/.test(g.event || ""));
        return gate && e.t_ms < gate.t_ms;
      })();
      const cls = `tl-marker ${c.cls} ${e.source === "expected" ? "expected" : "observed"} ${isEarlyTool ? "early" : ""}`;
      const dotColor = {
        yield: "var(--pass)", interrupt: "var(--warn)", tool: isEarlyTool ? "var(--fail)" : "var(--mutate)",
        expected: "var(--gray)", observed: "var(--observed)",
      }[c.cls] || "var(--observed)";
      const tip = `${e.event || ""} @ ${e.t_ms}ms${e.source ? " · " + e.source : ""}`;
      svg += `<g class="${cls}"><title>${esc(tip)}</title>`;
      svg += `<line x1="${cx}" y1="${ly + 12}" x2="${cx}" y2="${ly + laneH - 12}"/>`;
      svg += `<circle class="tl-dot" cx="${cx}" cy="${ly + laneH / 2}" r="4" fill="${dotColor}"/>`;
      // event short label
      svg += `<text class="tl-label" x="${cx + 6}" y="${ly + 14}">${esc(shortEvent(e.event))}</text>`;
      // utterance / tool text
      const note = e.text || (e.tool ? `${e.tool}(${argsText(e.args)})` : "");
      if (note) {
        svg += `<text class="tl-utt" x="${cx + 6}" y="${ly + laneH - 8}">${esc(truncate(note, 34))}</text>`;
      }
      svg += `</g>`;
    });

    svg += `</svg>`;

    const legend = `<div class="legend">
      <span><i style="border-color:var(--observed)"></i>observed</span>
      <span><i style="border-color:var(--gray);border-top-style:dashed"></i>expected</span>
      <span><i style="border-color:var(--warn)"></i>interrupt</span>
      <span><i style="border-color:var(--pass)"></i>yield</span>
      <span><i style="border-color:var(--mutate)"></i>tool</span>
      <span><i style="border-color:var(--fail)"></i>early commit</span>
    </div>`;

    return `<div class="timeline-card">
      <div class="section-head"><h2>Full-Duplex Timeline</h2><span class="count">${evs.length} events</span></div>
      ${legend}${svg}</div>`;
  }

  function shortEvent(name) {
    return String(name || "")
      .replace(/^assistant_/, "a_").replace(/^user_/, "u_")
      .replace(/_start$/, "").replace(/_ms$/, "");
  }
  function truncate(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; }

  // ================================================================
  // VIEW: Leaderboard
  // ================================================================
  async function renderReserved() {
    setStatus("policy-gating", "loading…");
    let rows;
    try {
      rows = await getJSON(`/api/leaderboard?track=${POLICY}`);
    } catch (e) {
      view.innerHTML = stateBlock({ glyph: "⚠", title: "Không tải được leaderboard", body: esc(e.message), error: true });
      return;
    }
    if (!rows.length) {
      view.innerHTML = stateBlock({ glyph: "∅", title: "Chưa có run Policy Gating nào", body: "Chạy run_policy_gating với --agent rồi quay lại." });
      return;
    }
    const head = ["Model", "Provider", "Episodes", "Status", "Compliance", "Forbidden", "Clarify P", "Clarify R", "State Acc", "Honesty", "Final State"];
    const body = rows.map((raw) => {
      const r = H.policyLeaderboardRow(raw);
      return `<tr class="${r.reportable ? "" : "muted"}">
        <td><b>${esc(r.model)}</b><div class="sub">${esc(r.run_id)}</div></td>
        <td>${esc(r.provider)}</td>
        <td class="cell-num">${esc(r.episodes)}</td>
        <td>${esc(r.status)}</td>
        <td class="cell-num">${esc(r.complianceCell)}</td>
        <td class="cell-num">${esc(r.forbiddenCell)}</td>
        <td class="cell-num">${esc(r.clarPrecisionCell)}</td>
        <td class="cell-num">${esc(r.clarRecallCell)}</td>
        <td class="cell-num">${esc(r.stateAccCell)}</td>
        <td class="cell-num">${esc(r.honestyCell)}</td>
        <td class="cell-num">${esc(r.finalStateCell)}</td>
      </tr>`;
    }).join("");
    view.innerHTML = `<section class="panel"><h2>Policy-Grounded Voice Command Gating Leaderboard</h2>
      <table class="lb"><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>
      <tbody>${body}</tbody></table></section>`;
    setStatus("policy-gating", `${rows.length} runs`);
  }

  // ---- router -----------------------------------------------------
  let _route = { tab: "fdrc", view: "overview" };
  function currentRoute() { return _route; }

  function setActiveTab(tab) {
    tabsEl.querySelectorAll(".tab").forEach((b) =>
      b.setAttribute("aria-current", b.dataset.tab === tab ? "true" : "false")
    );
  }

  function route() {
    const r = H.parseRoute(location.hash);
    _route = r;
    setActiveTab(r.tab);
    if (r.tab === "lab") return renderReserved();
    if (r.view === "episode") return renderEpisodeDetail(r);
    if (r.view === "episodes") return renderEpisodes(r);
    return renderOverview(r);
  }

  tabsEl.querySelectorAll(".tab").forEach((b) =>
    b.addEventListener("click", () => nav({ tab: b.dataset.tab }))
  );

  window.addEventListener("hashchange", route);
  route();
})();
