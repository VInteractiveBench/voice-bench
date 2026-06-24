# FDRC Run Selector — Group & Collapse by Kind Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dashboard's FDRC run dropdown show only real model ("benchmark") runs by default, with reference/internal/sample runs grouped behind a "show diagnostic runs" toggle, and default-select a benchmark run instead of the most-recently-updated diagnostic run.

**Architecture:** The FastAPI backend already classifies every run with `data_provenance` (`provider`/`reference`/`synthetic_reference`/`internal`/`sample`/`unknown`) and `run_kind` — see `src/dashboard/service.py` `_run_kind` and `_data_provenance`. No backend change is needed. We add three pure, unit-tested helpers to `helpers.js` (`effectiveRunKind`, `defaultRunId`, `groupRunsByKind`) and rewire `runSelector()` + the default-run selection in `app.js` to use them. "Benchmark" is defined strictly as `data_provenance === "provider"` so only provider-backed runs can ever appear as the one true score.

**Tech Stack:** Vanilla JS (no framework), Node-based unit tests (`node helpers.test.cjs`), Python/FastAPI backend (unchanged), pytest + ruff for verification.

---

## Why "benchmark = provider provenance" (not name-based `run_kind`)

`run_kind` is derived from the folder name (`_run_kind` in service.py): a folder literally named `fdrc` is tagged `benchmark` even if it contains no provider episodes. `data_provenance` is derived from episode contents and is the trustworthy signal: it is `provider` only when episodes carry a real `agent`/`model` identity. The "one true score" requirement means the Benchmark group must contain **only** `data_provenance === "provider"` runs. Everything else is a diagnostic bucket.

Mapping used throughout this plan (input `data_provenance` → display kind):

| `data_provenance` | display kind |
|---|---|
| `provider` | `benchmark` |
| `reference`, `synthetic_reference` | `reference` |
| `internal` | `internal` |
| `sample` | `sample` |
| `unknown` / anything else | `internal` (never masquerades as benchmark) |

## File Structure

- **Modify** `src/dashboard/static/helpers.js` — add `RUN_KIND_ORDER`, `RUN_KIND_LABELS`, `effectiveRunKind(run)`, `defaultRunId(runs)`, `groupRunsByKind(runs)`; export them.
- **Modify** `src/dashboard/static/helpers.test.cjs` — add unit tests for the three new helpers.
- **Modify** `src/dashboard/static/app.js` — rewrite `runSelector()` to render grouped `<optgroup>`s with a diagnostic toggle; replace the `runs[0]` default in `renderOverview()` with `H.defaultRunId(...)`; add module-level `showDiagnosticRuns` state and a toggle handler.
- **Modify** `docs/dashboard_usage.md` — document the grouped selector and what each kind means.

No files are created. No run folders are deleted.

---

### Task 1: Pure helper — `effectiveRunKind`

**Files:**
- Modify: `src/dashboard/static/helpers.js`
- Test: `src/dashboard/static/helpers.test.cjs`

- [ ] **Step 1: Write the failing test**

Add to the end of `src/dashboard/static/helpers.test.cjs`, before the final `console.log` line:

```js
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/dashboard/static && node helpers.test.cjs`
Expected: FAIL with `TypeError: VB.effectiveRunKind is not a function` (or `process.exitCode = 1` and a `FAIL effectiveRunKind...` line).

- [ ] **Step 3: Write minimal implementation**

In `src/dashboard/static/helpers.js`, immediately after the `const FDRC_TRACK = "full_duplex_repair_to_commit";` line, add:

```js
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
```

Then add `effectiveRunKind`, `RUN_KIND_ORDER`, and `RUN_KIND_LABELS` to the returned object at the bottom of the factory (the `return { ... }` block), e.g. after the `leaderboardRow,` line:

```js
    leaderboardRow,
    effectiveRunKind,
    RUN_KIND_ORDER,
    RUN_KIND_LABELS,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/dashboard/static && node helpers.test.cjs`
Expected: PASS — all `effectiveRunKind ...` lines print `ok`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add src/dashboard/static/helpers.js src/dashboard/static/helpers.test.cjs
git commit -m "feat(dashboard): add effectiveRunKind helper for run grouping"
```

---

### Task 2: Pure helper — `defaultRunId`

**Files:**
- Modify: `src/dashboard/static/helpers.js`
- Test: `src/dashboard/static/helpers.test.cjs`

- [ ] **Step 1: Write the failing test**

Add to the end of `src/dashboard/static/helpers.test.cjs`, before the final `console.log` line:

```js
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/dashboard/static && node helpers.test.cjs`
Expected: FAIL with `TypeError: VB.defaultRunId is not a function`.

- [ ] **Step 3: Write minimal implementation**

In `src/dashboard/static/helpers.js`, directly below the `effectiveRunKind` function added in Task 1, add:

```js
  // Pick which run to select by default. /api/runs is already sorted by
  // updated_at desc, so "first benchmark" = newest real score.
  function defaultRunId(runs) {
    const list = runs || [];
    const bench = list.find((r) => effectiveRunKind(r) === "benchmark");
    if (bench) return bench.run_id;
    return list.length ? list[0].run_id : null;
  }
```

Then add `defaultRunId,` to the returned object at the bottom of the factory, after the `effectiveRunKind,` line added in Task 1.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/dashboard/static && node helpers.test.cjs`
Expected: PASS — `defaultRunId ...` lines print `ok`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add src/dashboard/static/helpers.js src/dashboard/static/helpers.test.cjs
git commit -m "feat(dashboard): add defaultRunId helper preferring benchmark runs"
```

---

### Task 3: Pure helper — `groupRunsByKind`

**Files:**
- Modify: `src/dashboard/static/helpers.js`
- Test: `src/dashboard/static/helpers.test.cjs`

- [ ] **Step 1: Write the failing test**

Add to the end of `src/dashboard/static/helpers.test.cjs`, before the final `console.log` line:

```js
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/dashboard/static && node helpers.test.cjs`
Expected: FAIL with `TypeError: VB.groupRunsByKind is not a function`.

- [ ] **Step 3: Write minimal implementation**

In `src/dashboard/static/helpers.js`, directly below the `defaultRunId` function added in Task 2, add:

```js
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
```

Then add `groupRunsByKind,` to the returned object at the bottom of the factory, after the `defaultRunId,` line added in Task 2.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/dashboard/static && node helpers.test.cjs`
Expected: PASS — all `groupRunsByKind ...` lines print `ok`, final line prints total assertions passed, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add src/dashboard/static/helpers.js src/dashboard/static/helpers.test.cjs
git commit -m "feat(dashboard): add groupRunsByKind helper"
```

---

### Task 4: Wire grouped selector + default selection into `app.js`

**Files:**
- Modify: `src/dashboard/static/app.js` (rewrite `runSelector` at lines 94-107; update default run selection at lines 132-147; add module state near line 17-19)

This task has no Node unit test (it touches DOM/state, which `helpers.test.cjs` deliberately does not cover — see the helpers.js header). It is verified manually by loading the dashboard (Task 6). Keep all testable logic in the helpers from Tasks 1-3.

- [ ] **Step 1: Add module-level diagnostic-toggle state**

In `src/dashboard/static/app.js`, find (around line 18-19):

```js
  const explorerFilters = { validity: "", passed: "", domain: "", failure: "" };
  const explorerSort = { key: "episode_id", dir: 1 };
```

Add a line directly below them:

```js
  let showDiagnosticRuns = false;
```

- [ ] **Step 2: Rewrite `runSelector` to render grouped optgroups + toggle**

Replace the entire existing `runSelector` function (lines 94-107):

```js
  function runSelector(runs, runId) {
    const opts = runs
      .map(
        (r) =>
          `<option value="${esc(r.run_id)}" ${r.run_id === runId ? "selected" : ""}>${esc(
            r.run_id
          )} · ${r.episode_count} ep · ${esc(r.run_kind || "?")}</option>`
      )
      .join("");
    return `<div class="field">
      <label>FDRC Run</label>
      <select id="run-select">${opts}</select>
    </div>`;
  }
```

with:

```js
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
```

- [ ] **Step 3: Default to a benchmark run and auto-reveal diagnostics when needed**

In `renderOverview` (around lines 132-147), replace:

```js
    const runId = route.runId && runs.some((r) => r.run_id === route.runId)
      ? route.runId
      : runs[0].run_id;

    view.innerHTML = `<div class="controls">${runSelector(runs, runId)}
      <div class="spacer"></div>
      <button class="btn" id="go-episodes">Episode Explorer →</button>
    </div>
    <div id="ov-body"><div class="skeleton"></div></div>`;

    document.getElementById("run-select").addEventListener("change", (e) =>
      nav({ tab: "fdrc", view: "overview", runId: e.target.value })
    );
    document.getElementById("go-episodes").addEventListener("click", () =>
      nav({ tab: "fdrc", view: "episodes", runId })
    );
```

with:

```js
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

    document.getElementById("run-select").addEventListener("change", (e) =>
      nav({ tab: "fdrc", view: "overview", runId: e.target.value })
    );
    const showAllEl = document.getElementById("show-all-runs");
    if (showAllEl) {
      showAllEl.addEventListener("change", (e) => {
        showDiagnosticRuns = e.target.checked;
        document.querySelector(".controls .field").outerHTML = runSelector(runs, runId);
        document.getElementById("run-select").addEventListener("change", (ev) =>
          nav({ tab: "fdrc", view: "overview", runId: ev.target.value })
        );
        const reAdded = document.getElementById("show-all-runs");
        if (reAdded) reAdded.addEventListener("change", arguments.callee);
      });
    }
    document.getElementById("go-episodes").addEventListener("click", () =>
      nav({ tab: "fdrc", view: "episodes", runId })
    );
```

> Note: `arguments.callee` is used to re-bind the same toggle handler after the selector re-renders. If your lint config forbids it (strict mode disallows `arguments.callee`), extract the handler into a named function `function onToggle(e) { ... reAdded.addEventListener("change", onToggle); }` and reference `onToggle` instead. Prefer the named-function form to stay strict-mode clean.

- [ ] **Step 4: Replace `arguments.callee` with a named handler (strict-mode clean)**

`app.js` runs under `"use strict"` (line 7), where `arguments.callee` throws. Use this final form for the toggle wiring instead of the version in Step 3 — replace the `const showAllEl = ...` block with:

```js
    function wireRunControls() {
      document.getElementById("run-select").addEventListener("change", (e) =>
        nav({ tab: "fdrc", view: "overview", runId: e.target.value })
      );
      const showAllEl = document.getElementById("show-all-runs");
      if (showAllEl) {
        showAllEl.addEventListener("change", (e) => {
          showDiagnosticRuns = e.target.checked;
          const field = document.querySelector(".controls .field");
          field.outerHTML = runSelector(runs, runId);
          wireRunControls();
        });
      }
    }
    wireRunControls();
```

And delete the now-duplicated standalone `document.getElementById("run-select").addEventListener(...)` line that precedes it (the `run-select` change listener is now inside `wireRunControls`). Keep the `go-episodes` listener as-is, after `wireRunControls();`.

- [ ] **Step 5: Run the JS unit tests (regression check)**

Run: `cd src/dashboard/static && node helpers.test.cjs`
Expected: PASS — all assertions pass, exit code 0 (confirms helpers still load and app.js edits didn't touch them).

- [ ] **Step 6: Commit**

```bash
git add src/dashboard/static/app.js
git commit -m "feat(dashboard): group FDRC run selector by kind, default to benchmark"
```

---

### Task 5: Document the grouped selector

**Files:**
- Modify: `docs/dashboard_usage.md`

- [ ] **Step 1: Add a "Run Selector" section**

In `docs/dashboard_usage.md`, after the `## Data Integrity` section (ends near line 87), insert:

```markdown
## Chọn Run (Run Selector)

Dropdown `FDRC Run` mặc định chỉ hiển thị các run **Benchmark** — tức run có `data_provenance = provider` (kết quả model thật, có thể báo cáo). Đây là "một điểm số thật" duy nhất.

Các run còn lại được gom thành nhóm chẩn đoán và ẩn mặc định. Bật checkbox `Hiện run chẩn đoán` để xem chúng, hiển thị theo `<optgroup>`:

| Nhóm | `data_provenance` | Ý nghĩa |
|---|---|---|
| Kết quả thật (model provider) | `provider` | Kết quả model thật, báo cáo được. |
| Đối chiếu — kiểm bộ chấm | `reference`, `synthetic_reference` | Agent mẫu lý tưởng để kiểm bộ chấm; thường ~100%, không phải hiệu năng thật. |
| Nội bộ — chạy thử khi dev | `internal` | Run thử khi phát triển (`_impl_check_*`, `_plan_check_*`); bỏ đi được. |
| Dữ liệu mẫu | `sample` | Dữ liệu demo/mẫu. |

Run mặc định được chọn là benchmark run mới nhất. Nếu mở dashboard bằng URL trỏ tới một run chẩn đoán, checkbox tự bật để run đó vẫn xuất hiện.
```

- [ ] **Step 2: Commit**

```bash
git add docs/dashboard_usage.md
git commit -m "docs: explain grouped FDRC run selector"
```

---

### Task 6: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run JS unit tests**

Run: `cd src/dashboard/static && node helpers.test.cjs`
Expected: final line `N assertions passed.`, exit code 0.

- [ ] **Step 2: Run Python dashboard tests + lint (no backend change, must still pass)**

Run:
```powershell
conda run -n base python -m pytest -q tests\test_dashboard.py
conda run -n base python -m ruff check src\dashboard
```
Expected: pytest all pass; ruff reports no errors.

- [ ] **Step 3: Manual smoke of the dashboard**

Run:
```powershell
conda run -n base python -m src.dashboard --host 127.0.0.1 --port 8765
```
Open `http://127.0.0.1:8765`, go to the FDRC tab, and confirm:
- The `FDRC Run` dropdown shows only benchmark runs (e.g. `fdrc`, `automotive_openai_fdrc_gpt_realtime_mini`) — no `_impl_check_*`/`_plan_check_*`/`*_reference`/`*_sample` by default.
- A `Hiện run chẩn đoán (N)` checkbox is present; checking it reveals the diagnostic runs grouped under Reference / Internal / Sample optgroups.
- The initially selected run is a benchmark run (not `_impl_check_fdrc`).
- Selecting a run still loads its overview/summary.

- [ ] **Step 4: Commit any doc/screenshot updates if needed**

(No commit if Steps 1-3 pass with no changes.)

---

## Self-Review

**Spec coverage:**
- "Clean dashboard, one true score" → Task 4 default-selects a benchmark (provider) run; Task 1 defines benchmark = provider only. ✅
- "Group & collapse by kind, default Benchmark only" → Task 3 groups by kind; Task 4 renders benchmark-only by default with a toggle to reveal grouped diagnostics. ✅
- "Delete nothing" → No task removes run folders; backend untouched. ✅

**Placeholder scan:** All code steps contain complete code. Toggle wiring resolved to a strict-mode-safe named function in Task 4 Step 4 (the `arguments.callee` variant in Step 3 is explicitly superseded). No TBD/TODO. ✅

**Type consistency:** Helper names consistent across tasks and exports — `effectiveRunKind`, `defaultRunId`, `groupRunsByKind`, `RUN_KIND_ORDER`, `RUN_KIND_LABELS`. `app.js` calls them as `H.effectiveRunKind` / `H.defaultRunId` / `H.groupRunsByKind`, matching the `window.VB` export object. Group objects use `{ kind, label, runs }` consistently in both the helper and `runSelector`. ✅
