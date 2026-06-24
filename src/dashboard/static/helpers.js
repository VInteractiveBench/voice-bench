/* ============================================================
   Voice·Bench — pure helpers
   No DOM, no fetch. Deterministic, unit-testable.
   Exposed on window.VB (browser) and module.exports (node).
   ============================================================ */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.VB = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const FDRC_TRACK = "full_duplex_repair_to_commit";

  const RUN_KIND_ORDER = ["benchmark", "reference", "internal", "sample"];
  const RUN_KIND_LABELS = {
    benchmark: "Kết quả thật (model provider)",
    reference: "Đối chiếu — kiểm bộ chấm",
    internal: "Nội bộ — chạy thử khi dev",
    sample: "Dữ liệu mẫu",
  };

  // Map a run's data_provenance into a display kind. "benchmark" is reserved
  // strictly for provider-backed runs so only real scores can be the default.
  function effectiveRunKind(run) {
    const prov = (run && run.data_provenance) || "";
    if (prov === "provider") return "benchmark";
    if (prov === "reference" || prov === "synthetic_reference") return "reference";
    if (prov === "internal") return "internal";
    if (prov === "sample") return "sample";
    return "internal"; // unknown never masquerades as benchmark
  }

  // Pick which run to select by default. /api/runs is already sorted by
  // updated_at desc, so "first benchmark" = newest real score.
  function defaultRunId(runs) {
    const list = runs || [];
    const bench = list.find((r) => effectiveRunKind(r) === "benchmark");
    if (bench) return bench.run_id;
    return list.length ? list[0].run_id : null;
  }

  // Bucket runs into ordered, non-empty display groups by kind.
  // Returns [{ kind, label, runs:[...] }] in RUN_KIND_ORDER.
  function groupRunsByKind(runs) {
    const buckets = {};
    for (const r of runs || []) {
      const k = effectiveRunKind(r);
      (buckets[k] = buckets[k] || []).push(r);
    }
    return RUN_KIND_ORDER
      .filter((k) => buckets[k] && buckets[k].length)
      .map((k) => ({ kind: k, label: RUN_KIND_LABELS[k], runs: buckets[k] }));
  }

  // ---- formatting -------------------------------------------------
  function fmtPct(v, digits) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return (v * 100).toFixed(digits === undefined ? 1 : digits) + "%";
  }

  function fmtMs(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return Math.round(v) + " ms";
  }

  function fmtInt(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return String(Math.round(v));
  }

  // "numerator / denominator", nullish-safe. For audit explain modal.
  function formatRatio(numerator, denominator) {
    const n = Number.isFinite(numerator) ? numerator : 0;
    const d = Number.isFinite(denominator) ? denominator : 0;
    return n + " / " + d;
  }

  // Format a catalog metric {value, unit} into display text. Null-safe.
  function fmtMetric(metric) {
    if (!metric) return "—";
    const v = metric.value;
    if (v === null || v === undefined) return "N/A";
    switch (metric.unit) {
      case "rate": return fmtPct(v);
      case "ms": return fmtMs(v);
      case "count": return fmtInt(v);
      default:
        return typeof v === "number" ? String(v) : String(v);
    }
  }

  // ---- reportability ---------------------------------------------
  // Derive a trust banner from fields the API actually returns:
  // data_provenance, provenance_warning, run_kind, metrics_hash_valid,
  // metric_contract.benchmark_status.
  function deriveReportability(summary) {
    if (!summary) {
      return { tone: "fail", label: "NO DATA", note: "Không tải được run." };
    }
    const prov = summary.data_provenance || "unknown";
    const warning = summary.provenance_warning || null;
    const contract = summary.metric_contract || {};
    const status = contract.benchmark_status || null;
    const hashValid = summary.metrics_hash_valid !== false;

    let tone, label, note;

    if (prov === "provider") {
      tone = "pass";
      label = "REPORTABLE";
      note = "Provider run — performance có thể báo cáo.";
    } else {
      tone = "warn";
      label = "VALIDITY ONLY";
      note =
        warning ||
        "Reference/sample/internal run — chỉ dùng debug, KHÔNG báo cáo như performance thật.";
    }

    if (status && /fail|invalid|not_report/i.test(String(status))) {
      tone = "fail";
      label = "NOT REPORTABLE";
      note = warning || "Contract chưa hợp lệ — không báo cáo performance.";
    }

    const extras = [];
    if (!hashValid) {
      extras.push("metrics derived từ episodes.jsonl (hash không khớp)");
    }
    if (summary.metric_source && summary.metric_source !== "metrics.json") {
      // already conveyed by hashValid in most cases; keep concise
    }
    if (extras.length) note = note + " · " + extras.join(" · ");

    return { tone, label, note, provenance: prov, status };
  }

  // ---- validity summary over an episode list ----------------------
  function validitySummary(episodes) {
    const rows = episodes || [];
    let valid = 0;
    let known = 0;
    for (const e of rows) {
      const v = e.fdrc_valid;
      if (v === true) { valid++; known++; }
      else if (v === false) { known++; }
    }
    return {
      valid,
      total: rows.length,
      known,
      rate: known ? valid / known : null,
    };
  }

  // ---- episode status classification ------------------------------
  // Returns one of: invalid | pass | fail | unscored
  function episodeStatus(row) {
    if (!row) return "unscored";
    if (row.fdrc_valid === false) return "invalid";
    if (row.passed === true) return "pass";
    if (row.passed === false) return "fail";
    return "unscored";
  }

  function statusTone(status) {
    return (
      { pass: "pass", fail: "fail", invalid: "warn", unscored: "gray" }[status] ||
      "gray"
    );
  }

  // ---- timeline geometry ------------------------------------------
  // Bucket a raw voice/timeline event into a marker class + lane key.
  function classifyEvent(name) {
    const n = String(name || "");
    if (n === "tool_call") return { lane: "tool", cls: "tool" };
    if (/interrupt/.test(n)) return { lane: "events", cls: "interrupt" };
    if (/yield/.test(n) && !/should_yield/.test(n)) return { lane: "events", cls: "yield" };
    if (/should_yield|allowed_after|expected/.test(n)) return { lane: "events", cls: "expected" };
    if (/user_speech|user_/.test(n)) return { lane: "user", cls: "observed" };
    if (/assistant/.test(n)) return { lane: "assistant", cls: "observed" };
    return { lane: "events", cls: "observed" };
  }

  function eventTime(ev) {
    const t = ev && ev.t_ms;
    return typeof t === "number" ? t : null;
  }

  function findEvent(events, predicate) {
    for (const e of events || []) if (predicate(e)) return e;
    return null;
  }

  // Compute repair window [start, end] in ms, or null if no interrupt.
  function repairWindow(events) {
    const evs = events || [];
    const interrupt = findEvent(evs, (e) => /interrupt/.test(e.event || ""));
    if (!interrupt || eventTime(interrupt) === null) return null;
    const start = eventTime(interrupt);
    let end = start;
    for (const e of evs) {
      const t = eventTime(e);
      if (t === null) continue;
      const name = e.event || "";
      if (/yield|allowed_after|repair|tool_call/.test(name) && t >= start && t > end) {
        end = t;
      }
    }
    if (end === start) end = start + 600; // minimum visible width
    return { start, end };
  }

  // Yield latency = assistant_yielded.t - user_interrupt_start.t
  function yieldLatency(events) {
    const evs = events || [];
    const interrupt = findEvent(evs, (e) => /interrupt/.test(e.event || ""));
    const yielded = findEvent(
      evs,
      (e) => /yield/.test(e.event || "") && !/should_yield/.test(e.event || "")
    );
    if (!interrupt || !yielded) return null;
    const a = eventTime(interrupt);
    const b = eventTime(yielded);
    if (a === null || b === null) return null;
    return b - a;
  }

  // Total duration (ms) for the axis; rounded up to a clean tick.
  function timelineDuration(events) {
    let max = 0;
    for (const e of events || []) {
      const t = eventTime(e);
      if (t !== null && t > max) max = t;
    }
    if (max <= 0) max = 1000;
    const pad = max * 0.08;
    const span = max + pad;
    const step = span > 8000 ? 2000 : span > 4000 ? 1000 : 500;
    return Math.ceil(span / step) * step;
  }

  // Linear scale builder: ms -> px
  function scaler(durationMs, x0, x1) {
    const d = durationMs <= 0 ? 1 : durationMs;
    return function (ms) {
      const clamped = Math.max(0, Math.min(ms, d));
      return x0 + (clamped / d) * (x1 - x0);
    };
  }

  // Detect early commit: a tool_call before the latest commit-gate event.
  function earlyCommit(events) {
    const evs = events || [];
    const gate = findEvent(
      evs,
      (e) => /allowed_after|repair_transcript_done|repair_audio/.test(e.event || "")
    );
    if (!gate) return false;
    const gateT = eventTime(gate);
    if (gateT === null) return false;
    for (const e of evs) {
      if ((e.event || "") === "tool_call") {
        const t = eventTime(e);
        if (t !== null && t < gateT) return true;
      }
    }
    return false;
  }

  // ---- hash routing ----------------------------------------------
  // Parse "#fdrc/runs/:id/episodes/:eid" into a structured route.
  function parseRoute(hash) {
    const raw = String(hash || "").replace(/^#\/?/, "");
    const parts = raw.split("/").filter(Boolean);
    if (parts.length === 0) return { tab: "fdrc", view: "overview" };
    const tab = parts[0];
    if (tab === "lab") return { tab: "lab" };
    // fdrc routes
    if (parts[1] === "runs" && parts[2]) {
      const runId = decodeURIComponent(parts[2]);
      if (parts[3] === "episodes" && parts[4]) {
        return { tab: "fdrc", view: "episode", runId, episodeId: decodeURIComponent(parts[4]) };
      }
      if (parts[3] === "episodes") {
        return { tab: "fdrc", view: "episodes", runId };
      }
      return { tab: "fdrc", view: "overview", runId };
    }
    return { tab: "fdrc", view: "overview" };
  }

  function buildHash(route) {
    if (!route || route.tab === "lab") return "#lab";
    const r = ["#fdrc"];
    if (route.runId) {
      r.push("runs", encodeURIComponent(route.runId));
      if (route.view === "episodes") r.push("episodes");
      if (route.view === "episode" && route.episodeId) {
        r.push("episodes", encodeURIComponent(route.episodeId));
      }
    }
    return r.join("/");
  }

  function isFdrcRun(run) {
    return run && run.benchmark_track === FDRC_TRACK;
  }

  // ---- leaderboard row --------------------------------------------
  // Turn a raw /api/leaderboard row into display-ready cells.
  // Pass@1 only shows the performance number when the run is reportable.
  function leaderboardRow(row) {
    const reportable = String(row.reportability_status || "").startsWith("REPORTABLE");
    return {
      run_id: row.run_id,
      provider: row.provider || "—",
      model: row.model || "—",
      yield_mode: row.yield_mode || "—",
      episodes: fmtInt(row.episode_count),
      reportable,
      reportability_status: row.reportability_status || "—",
      validityCell: fmtPct(row.fdrc_validity_rate),
      passCell: reportable ? fmtPct(row.performance_fdrc_pass_at_1) : "—",
      rawPassCell: fmtPct(row.raw_fdrc_pass_at_1),
      yieldP50: fmtMs(row.performance_yield_latency_p50_ms),
      yieldP95: fmtMs(row.performance_yield_latency_p95_ms),
      forbiddenCell: fmtPct(row.forbidden_tool_call_rate),
      cancelCell: fmtPct(row.cancel_success_rate),
      uptakeCell: fmtPct(row.correction_uptake_rate),
    };
  }

  return {
    FDRC_TRACK,
    RUN_KIND_ORDER,
    RUN_KIND_LABELS,
    effectiveRunKind,
    defaultRunId,
    groupRunsByKind,
    fmtPct,
    fmtMs,
    fmtInt,
    formatRatio,
    fmtMetric,
    deriveReportability,
    validitySummary,
    episodeStatus,
    statusTone,
    classifyEvent,
    eventTime,
    findEvent,
    repairWindow,
    yieldLatency,
    timelineDuration,
    scaler,
    earlyCommit,
    parseRoute,
    buildHash,
    isFdrcRun,
    leaderboardRow,
  };
});
