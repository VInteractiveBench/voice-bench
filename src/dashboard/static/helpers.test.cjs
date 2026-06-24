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

// ---- leaderboard row ----
t("leaderboardRow formats reportable run", () => {
  const r = VB.leaderboardRow({
    run_id: "run_gemini", provider: "google", model: "gemini-x",
    yield_mode: "native_yield", episode_count: 90,
    reportability_status: "REPORTABLE_DOMAIN",
    fdrc_validity_rate: 1, performance_fdrc_pass_at_1: 0.5,
    raw_fdrc_pass_at_1: 0.5,
  });
  assert.strictEqual(r.model, "gemini-x");
  assert.strictEqual(r.passCell, "50.0%");
  assert.strictEqual(r.validityCell, "100.0%");
  assert.strictEqual(r.reportable, true);
});

t("leaderboardRow shows dash when not reportable", () => {
  const r = VB.leaderboardRow({
    run_id: "run_x", provider: "openai", model: "gpt",
    reportability_status: "VALIDITY_ONLY",
    fdrc_validity_rate: 0.8, performance_fdrc_pass_at_1: null,
    raw_fdrc_pass_at_1: 0.1,
  });
  assert.strictEqual(r.passCell, "—");
  assert.strictEqual(r.reportable, false);
});

console.log(`\n${passed} assertions passed.`);
