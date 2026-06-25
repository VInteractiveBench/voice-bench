/* Node unit tests for the pure helpers. Run: node helpers.test.cjs */
const assert = require("assert");
const VB = require("./helpers.js");

let passed = 0;
function t(name, fn) {
  try { fn(); passed++; console.log("  ok  " + name); }
  catch (e) { console.error("FAIL  " + name + "\n      " + e.message); process.exitCode = 1; }
}

// ---- formatting ----
t("fmtPct", () => {
  assert.strictEqual(VB.fmtPct(0.875), "87.5%");
  assert.strictEqual(VB.fmtPct(null), "—");
  assert.strictEqual(VB.fmtPct(1), "100.0%");
});
t("fmtMs", () => {
  assert.strictEqual(VB.fmtMs(400), "400 ms");
  assert.strictEqual(VB.fmtMs(null), "—");
});
t("fmtMetric null vs rate vs ms", () => {
  assert.strictEqual(VB.fmtMetric({ value: null, unit: "rate" }), "N/A");
  assert.strictEqual(VB.fmtMetric({ value: 0.5, unit: "rate" }), "50.0%");
  assert.strictEqual(VB.fmtMetric({ value: 400, unit: "ms" }), "400 ms");
  assert.strictEqual(VB.fmtMetric({ value: 24, unit: "count" }), "24");
});

// ---- reportability ----
t("reportability: provider => REPORTABLE", () => {
  const r = VB.deriveReportability({ data_provenance: "provider", metrics_hash_valid: true });
  assert.strictEqual(r.tone, "pass");
  assert.strictEqual(r.label, "REPORTABLE");
});
t("reportability: reference => VALIDITY ONLY", () => {
  const r = VB.deriveReportability({ data_provenance: "reference", metrics_hash_valid: true });
  assert.strictEqual(r.tone, "warn");
  assert.strictEqual(r.label, "VALIDITY ONLY");
});
t("reportability: hash invalid appends note", () => {
  const r = VB.deriveReportability({ data_provenance: "provider", metrics_hash_valid: false });
  assert.ok(/derived/.test(r.note));
});

// ---- validity summary ----
t("validitySummary counts", () => {
  const vs = VB.validitySummary([
    { fdrc_valid: true }, { fdrc_valid: true }, { fdrc_valid: false }, { fdrc_valid: null },
  ]);
  assert.strictEqual(vs.valid, 2);
  assert.strictEqual(vs.known, 3);
  assert.strictEqual(vs.total, 4);
  assert.ok(Math.abs(vs.rate - 2 / 3) < 1e-9);
});

// ---- episode status ----
t("episodeStatus precedence", () => {
  assert.strictEqual(VB.episodeStatus({ fdrc_valid: false, passed: true }), "invalid");
  assert.strictEqual(VB.episodeStatus({ fdrc_valid: true, passed: true }), "pass");
  assert.strictEqual(VB.episodeStatus({ fdrc_valid: true, passed: false }), "fail");
  assert.strictEqual(VB.episodeStatus({ passed: null }), "unscored");
});

// ---- timeline geometry (real episode shape) ----
const sampleEvents = [
  { t_ms: 0, event: "user_speech_start", text: "Đặt điều hòa 22 độ." },
  { t_ms: 2600, event: "assistant_speech_expected_start" },
  { t_ms: 3300, event: "user_interrupt_start", text: "À không, 24 độ." },
  { t_ms: 3700, event: "assistant_yielded" },
  { t_ms: 4000, event: "assistant_should_yield_by" },
  { t_ms: 4300, event: "tool_commit_allowed_after" },
  { t_ms: 4600, event: "tool_call", tool: "climate_control", args: { value: "24" } },
];

t("repairWindow spans interrupt..last", () => {
  const rw = VB.repairWindow(sampleEvents);
  assert.strictEqual(rw.start, 3300);
  assert.strictEqual(rw.end, 4600);
});
t("yieldLatency = yielded - interrupt", () => {
  assert.strictEqual(VB.yieldLatency(sampleEvents), 400);
});
t("timelineDuration rounds up", () => {
  const d = VB.timelineDuration(sampleEvents);
  assert.ok(d >= 4600 && d % 500 === 0);
});
t("scaler maps endpoints", () => {
  const x = VB.scaler(5000, 100, 1000);
  assert.strictEqual(x(0), 100);
  assert.strictEqual(x(5000), 1000);
  assert.ok(x(2500) > 500 && x(2500) < 600);
});
t("earlyCommit false when tool after gate", () => {
  assert.strictEqual(VB.earlyCommit(sampleEvents), false);
});
t("earlyCommit true when tool before gate", () => {
  const bad = [
    { t_ms: 3300, event: "user_interrupt_start" },
    { t_ms: 3500, event: "tool_call", tool: "x" },
    { t_ms: 4300, event: "tool_commit_allowed_after" },
  ];
  assert.strictEqual(VB.earlyCommit(bad), true);
});
t("classifyEvent buckets", () => {
  assert.strictEqual(VB.classifyEvent("tool_call").lane, "tool");
  assert.strictEqual(VB.classifyEvent("user_interrupt_start").cls, "interrupt");
  assert.strictEqual(VB.classifyEvent("assistant_yielded").cls, "yield");
  assert.strictEqual(VB.classifyEvent("assistant_should_yield_by").cls, "expected");
});

// ---- routing ----
t("parseRoute overview/episodes/episode", () => {
  assert.deepStrictEqual(VB.parseRoute("#fdrc"), { tab: "fdrc", view: "overview" });
  assert.deepStrictEqual(VB.parseRoute("#lab"), { tab: "lab" });
  assert.deepStrictEqual(VB.parseRoute("#fdrc/runs/abc"), { tab: "fdrc", view: "overview", runId: "abc" });
  assert.deepStrictEqual(VB.parseRoute("#fdrc/runs/abc/episodes"), { tab: "fdrc", view: "episodes", runId: "abc" });
  assert.deepStrictEqual(
    VB.parseRoute("#fdrc/runs/abc/episodes/ep%3A1"),
    { tab: "fdrc", view: "episode", runId: "abc", episodeId: "ep:1" }
  );
});
t("buildHash round-trips", () => {
  const r = { tab: "fdrc", view: "episode", runId: "r 1", episodeId: "ep:1" };
  const back = VB.parseRoute(VB.buildHash(r));
  assert.strictEqual(back.runId, "r 1");
  assert.strictEqual(back.episodeId, "ep:1");
});

// ---- policy-gating leaderboard row ----

// ---- run kind grouping ----
t("effectiveRunKind maps provider => benchmark", () => {
  assert.strictEqual(VB.effectiveRunKind({ data_provenance: "provider" }), "benchmark");
});
t("effectiveRunKind maps reference + synthetic_reference => reference", () => {
  assert.strictEqual(VB.effectiveRunKind({ data_provenance: "reference" }), "reference");
  assert.strictEqual(VB.effectiveRunKind({ data_provenance: "synthetic_reference" }), "reference");
});
t("effectiveRunKind maps internal and sample to themselves", () => {
  assert.strictEqual(VB.effectiveRunKind({ data_provenance: "internal" }), "internal");
  assert.strictEqual(VB.effectiveRunKind({ data_provenance: "sample" }), "sample");
});
t("effectiveRunKind never lets unknown masquerade as benchmark", () => {
  assert.strictEqual(VB.effectiveRunKind({ data_provenance: "unknown" }), "internal");
  assert.strictEqual(VB.effectiveRunKind({}), "internal");
  assert.strictEqual(VB.effectiveRunKind(null), "internal");
});

t("defaultRunId prefers the first provider/benchmark run", () => {
  const runs = [
    { run_id: "impl_check", data_provenance: "internal" },
    { run_id: "real_run", data_provenance: "provider" },
    { run_id: "ref_run", data_provenance: "reference" },
  ];
  assert.strictEqual(VB.defaultRunId(runs), "real_run");
});
t("defaultRunId falls back to first run when no benchmark exists", () => {
  const runs = [
    { run_id: "ref_run", data_provenance: "reference" },
    { run_id: "impl_check", data_provenance: "internal" },
  ];
  assert.strictEqual(VB.defaultRunId(runs), "ref_run");
});
t("defaultRunId returns null for empty/missing input", () => {
  assert.strictEqual(VB.defaultRunId([]), null);
  assert.strictEqual(VB.defaultRunId(null), null);
});

t("groupRunsByKind returns non-empty groups in fixed order", () => {
  const runs = [
    { run_id: "s1", data_provenance: "sample" },
    { run_id: "b1", data_provenance: "provider" },
    { run_id: "r1", data_provenance: "reference" },
    { run_id: "b2", data_provenance: "provider" },
  ];
  const groups = VB.groupRunsByKind(runs);
  assert.deepStrictEqual(groups.map((g) => g.kind), ["benchmark", "reference", "sample"]);
  assert.strictEqual(groups[0].runs.length, 2);
  assert.strictEqual(groups[0].label, VB.RUN_KIND_LABELS.benchmark);
  assert.strictEqual(groups[0].runs[0].run_id, "b1");
});
t("groupRunsByKind preserves input order within a group", () => {
  const runs = [
    { run_id: "b2", data_provenance: "provider" },
    { run_id: "b1", data_provenance: "provider" },
  ];
  const groups = VB.groupRunsByKind(runs);
  assert.deepStrictEqual(groups[0].runs.map((r) => r.run_id), ["b2", "b1"]);
});
t("groupRunsByKind handles empty input", () => {
  assert.deepStrictEqual(VB.groupRunsByKind([]), []);
  assert.deepStrictEqual(VB.groupRunsByKind(null), []);
});

// ---- formatRatio ----
t("formatRatio shows numerator / denominator", () => {
  assert.strictEqual(VB.formatRatio(1, 8), "1 / 8");
  assert.strictEqual(VB.formatRatio(0, 0), "0 / 0");
});
t("formatRatio coerces nullish to 0", () => {
  assert.strictEqual(VB.formatRatio(null, undefined), "0 / 0");
});

// ---- metricTone (direction-aware coloring) ----
t("metricTone: good-high metric green when high, red when low", () => {
  assert.strictEqual(VB.metricTone("fdrc_pass_at_1", 0.95, "rate"), "s-pass");
  assert.strictEqual(VB.metricTone("fdrc_pass_at_1", 0.8, "rate"), "s-warn");
  assert.strictEqual(VB.metricTone("fdrc_pass_at_1", 0.0, "rate"), "s-fail");
  assert.strictEqual(VB.metricTone("state_match", 0.0, "rate"), "s-fail");
  assert.strictEqual(VB.metricTone("fdrc_validity_rate", 0.625, "rate"), "s-fail");
});
t("metricTone: bad-high metric green when low, red when high", () => {
  assert.strictEqual(VB.metricTone("policy_violation_rate", 0.0, "rate"), "s-pass");
  assert.strictEqual(VB.metricTone("policy_violation_rate", 0.15, "rate"), "s-warn");
  assert.strictEqual(VB.metricTone("policy_violation_rate", 0.375, "rate"), "s-fail");
  assert.strictEqual(VB.metricTone("tool_validation_error_rate", 0.375, "rate"), "s-fail");
  assert.strictEqual(VB.metricTone("forbidden_tool_call_rate", 0.125, "rate"), "s-warn");
});
t("metricTone: non-rate units and unknown/null are neutral", () => {
  assert.strictEqual(VB.metricTone("yield_latency_p50_ms", 2548, "ms"), "");
  assert.strictEqual(VB.metricTone("valid_episode_count", 1, "count"), "");
  assert.strictEqual(VB.metricTone("some_unknown_rate", 0.0, "rate"), "");
  assert.strictEqual(VB.metricTone("fdrc_pass_at_1", null, "rate"), "");
});
t("metricTone: dotted keys resolve by base", () => {
  assert.strictEqual(VB.metricTone("performance_yield_latency_pass_rate", 1.0, "rate"), "s-pass");
});

// ---- nullReasonText / contractStatusText (audit-friendly labels) ----
t("nullReasonText maps known codes to Vietnamese", () => {
  assert.strictEqual(VB.nullReasonText("not_reportable_validity"), "Chưa đủ validity (<90%) để báo cáo");
  assert.strictEqual(VB.nullReasonText("no_cancel_cases"), "Không có ca cancel để đo");
  assert.strictEqual(VB.nullReasonText("no_data"), "Không có dữ liệu");
});
t("nullReasonText falls back to a default for null/unknown", () => {
  assert.strictEqual(VB.nullReasonText(null), "Không có dữ liệu");
  assert.strictEqual(VB.nullReasonText("weird_code"), "weird_code");
});
t("contractStatusText maps statuses to Vietnamese", () => {
  assert.strictEqual(VB.contractStatusText("failed_evaluated"), "Đã chấm — có episode chưa đạt");
  assert.strictEqual(VB.contractStatusText("completed"), "Hoàn tất — tất cả pass");
  assert.strictEqual(VB.contractStatusText("partial"), "Chưa đủ — thiếu episode / đang chạy");
  assert.strictEqual(VB.contractStatusText("invalid"), "Không hợp lệ — thiếu metric bắt buộc");
  assert.strictEqual(VB.contractStatusText("xyz"), "xyz");
});

t("confusionCell returns count for expected/agent pair", () => {
  const matrix = [{ expected: "refuse", agent: "execute", count: 3 }];
  assert.strictEqual(VB.confusionCell(matrix, "refuse", "execute"), 3);
  assert.strictEqual(VB.confusionCell(matrix, "refuse", "refuse"), 0);
});

t("policyLeaderboardRow formats provider run as reportable", () => {
  const r = VB.policyLeaderboardRow({
    run_id: "run_pg", provider: "openai", model: "gpt-x",
    data_provenance: "provider", episode_count: 24, benchmark_status: "completed",
    policy_compliance_rate: 0.9, forbidden_tool_call_rate: 0.0,
    clarification_precision: 1.0, clarification_recall: 0.8,
    state_conditioned_decision_accuracy: 1.0, response_honesty_rate: 0.95,
    final_state_correctness: 1.0,
  });
  assert.strictEqual(r.model, "gpt-x");
  assert.strictEqual(r.reportable, true);
  assert.strictEqual(r.complianceCell, "90.0%");
  assert.strictEqual(r.forbiddenCell, "0.0%");
  assert.strictEqual(r.status, "completed");
});

t("policyLeaderboardRow mutes non-provider runs", () => {
  const r = VB.policyLeaderboardRow({ run_id: "ref", data_provenance: "reference" });
  assert.strictEqual(r.reportable, false);
  assert.strictEqual(r.complianceCell, "—");
});

console.log(`\n${passed} assertions passed.`);
