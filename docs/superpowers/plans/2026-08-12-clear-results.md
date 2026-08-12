# Clear Ranked Results Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CLEAR button to the ranked results panel that empties the in-session results table and live metrics.

**Architecture:** Frontend-only change. A new `results_clear` event is handled by the existing `progressReducer` in `useBenchmarkProgress.ts`, which owns `progressState.results`. The CLEAR button in `App.tsx` dispatches this event; it renders only when rows exist and is disabled while a run is in progress. No backend/DB changes — persisted runs on `/results` are untouched.

**Tech Stack:** React 18, TypeScript 5, Vitest 4 + Testing Library, Vite 7.

---

## File Structure

- **Modify** `frontend/src/ws/useBenchmarkProgress.ts` — add `"results_clear"` to the event union + a reducer case that empties `results`/`promptTps`/`decodeTps`.
- **Modify** `frontend/src/App.tsx:542-548` — add the CLEAR button to the `05 · RESULTS — RANKED` panel.
- **Test** `frontend/src/ws/useBenchmarkProgress.test.ts` — reducer behavior.
- **Test** `frontend/src/App.test.tsx` — button appears, clears the table, disappears.

---

## Task 1: `results_clear` reducer event

**Files:**
- Modify: `frontend/src/ws/useBenchmarkProgress.ts:4` (union) and after line 64 (reducer case)
- Test: `frontend/src/ws/useBenchmarkProgress.test.ts`

- [ ] **Step 1: Write the failing test** — append to `useBenchmarkProgress.test.ts`:

```ts
test("results_clear empties results and live metrics", () => {
  let state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  state = progressReducer(state, ev("config_done", 1, {
    index: 0,
    result: { status: "ok", decode_tps: 42.0, prompt_processing_tps: 100.0 },
  }));
  expect(state.results).toHaveLength(1);
  const next = progressReducer(state, { type: "results_clear" });
  expect(next.results).toEqual([]);
  expect(next.promptTps).toBeNull();
  expect(next.decodeTps).toBeNull();
  expect(next.runId).toBe(1);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/ws/useBenchmarkProgress.test.ts`
Expected: FAIL — `results_clear` is not assignable to `ProgressEvent["type"]` (TS error), reducer returns unchanged state.

- [ ] **Step 3: Implement the reducer event**

In `frontend/src/ws/useBenchmarkProgress.ts:4`, change the union to:

```ts
type: "run_started" | "config_start" | "config_done" | "run_done" | "run_sync" | "run_watch" | "bench_log" | "config_wait" | "results_clear";
```

Add this case immediately after the `run_started` block (after line 64):

```ts
if (event.type === "results_clear") {
  return { ...state, results: [], promptTps: null, decodeTps: null };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/ws/useBenchmarkProgress.test.ts`
Expected: PASS (all 18 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/ws/useBenchmarkProgress.ts frontend/src/ws/useBenchmarkProgress.test.ts
git commit -m "feat: add results_clear event to benchmark progress reducer"
```

---

## Task 2: CLEAR button in the results panel

**Files:**
- Modify: `frontend/src/App.tsx:542-548`
- Test: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write the failing test** — append to `App.test.tsx`:

```ts
test("CLEAR empties the ranked results table", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.getRun).mockResolvedValue({
    status: "completed",
    total: 1,
    results: [
      {
        config_id: 1,
        server_id: "llama.cpp",
        flag_conf: { "--max-model-len": "8192" },
        serving_command: "llama-server --hf-repo org/model --hf-file model.gguf --ctx-size 8192",
        prompt_processing_tps: 100.0,
        decode_tps: 42.0,
      },
    ],
  });

  render(<MemoryRouter><App /></MemoryRouter>);

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);
  fireEvent.click(screen.getByText(/generate/i));
  await screen.findByText(/python serve/i);
  fireEvent.click(screen.getByText(/run benchmark/i));

  await waitFor(() => {
    const table = document.querySelector(".results-table") as HTMLElement | null;
    expect(table).not.toBeNull();
    expect(within(table!).getByText("42.0")).toBeInTheDocument();
  }, { timeout: 3000 });

  fireEvent.click(screen.getByRole("button", { name: "CLEAR" }));

  await waitFor(() => {
    expect(screen.queryByRole("button", { name: "CLEAR" })).not.toBeInTheDocument();
  });
  const table = document.querySelector(".results-table") as HTMLElement | null;
  expect(within(table!).queryByText("42.0")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: FAIL — `getByRole("button", { name: "CLEAR" })` throws (no CLEAR button exists).

- [ ] **Step 3: Implement the CLEAR button**

Replace lines 542-548 in `frontend/src/App.tsx`:

```tsx
<section className="panel">
  <div className="row">
    <span className="panel-cap" style={{ marginBottom: 0 }}>05 · RESULTS — RANKED</span>
    {progressState.results.length > 0 && (
      <button
        className="btn-neutral"
        onClick={() => dispatch({ type: "results_clear" })}
        disabled={progressState.running}
      >
        CLEAR
      </button>
    )}
  </div>
  <ResultsTable rows={progressState.results} />
  <Link to="/results" className="results-link" style={{ fontSize: 12 }}>
    view all runs →
  </Link>
</section>
```

Uses existing `btn-neutral` style (`app.css:67`) and `.row` flex class. `dispatch` is already in scope in `App`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat: add CLEAR button to ranked results panel"
```

---

## Task 3: Full local suite verification

- [ ] **Step 1: Frontend typecheck + all unit tests**

Run: `cd frontend && npx tsc -b && npx vitest run`
Expected: PASS — no type errors, all component/ws/api tests green.

- [ ] **Step 2: Backend tests (unchanged, regression guard)**

Run: `cd backend && pytest`
Expected: PASS — all tests green (no backend changes).

- [ ] **Step 3: Playwright e2e**

Run: `cd frontend && npx playwright test`
Expected: PASS — `full flow: analyze, generate, run, see ranked results` still passes (CLEAR button doesn't affect it).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: verify clear-results against full local suite" || echo "nothing to commit"
```

---

## Task 4: Restore latest run's results on page load

**Why:** `progressState` is in-memory only, so a browser refresh wipes the ranked results table and the CLEAR button (which only renders when rows exist). Restoring the most recent terminal run's results on mount repopulates the table so CLEAR is visible after a refresh.

**Files:**
- Modify: `frontend/src/App.tsx` — add a mount effect after the `useReducer` declaration (after line 235)
- Test: `frontend/src/App.test.tsx`

No reducer changes — reuses the existing `run_started` + `run_sync` events. No backend changes (`listRuns` is ordered by `id DESC`, db.py:178; `getRun` returns results, api.py:748).

- [ ] **Step 1: Write the failing test** — append to `App.test.tsx`:

```tsx
test("restores the latest completed run's results on load and shows CLEAR", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.listRuns).mockResolvedValue({
    runs: [{ id: 3, repo_id: "org/model", requested_n: 1, created_at: "", status: "completed" }],
  });
  vi.mocked(api.getRun).mockResolvedValue({
    status: "completed",
    total: 1,
    results: [{
      config_id: 1,
      server_id: "llama.cpp",
      flag_conf: { "--max-model-len": "8192" },
      serving_command: "llama-server --hf-repo org/model --hf-file model.gguf --ctx-size 8192",
      prompt_processing_tps: 100.0,
      decode_tps: 42.0,
    }],
  });

  render(<MemoryRouter><App /></MemoryRouter>);

  await waitFor(() => {
    const table = document.querySelector(".results-table") as HTMLElement | null;
    expect(table).not.toBeNull();
    expect(within(table!).getByText("42.0")).toBeInTheDocument();
  });
  expect(screen.getByRole("button", { name: "CLEAR" })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/App.test.tsx -t "restores"`
Expected: FAIL — table stays empty on mount (no restore logic yet), `42.0` never appears.

- [ ] **Step 3: Implement the restore effect**

In `frontend/src/App.tsx`, immediately after `const [progressState, dispatch] = useReducer(progressReducer, INITIAL_STATE);`, add:

```tsx
useEffect(() => {
  let cancelled = false;
  api
    .listRuns()
    .then(({ runs }) => {
      if (cancelled) return;
      const latest = runs.find((r) => r.status !== "running" && r.status !== "queued");
      if (!latest) return;
      return api.getRun(latest.id).then((detail) => {
        if (cancelled) return;
        dispatch({ type: "run_started", run_id: latest.id, total: latest.requested_n ?? 0 });
        dispatch({
          type: "run_sync",
          run_id: latest.id,
          status: detail.status ?? latest.status,
          total: detail.total ?? latest.requested_n ?? 0,
          results: (detail.results ?? []).map(toResultRow),
        });
      });
    })
    .catch(() => {});
  return () => {
    cancelled = true;
  };
}, []);
```

`useEffect`, `api`, `dispatch`, and `toResultRow` are already imported/in scope in `App.tsx`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat: restore latest run results on page load"
```

---

## Task 5: Full local suite verification

- [ ] **Step 1: Frontend typecheck + all unit tests**

Run: `cd frontend && npx tsc -b && npx vitest run`
Expected: PASS — no type errors, all component/ws/api tests green.

- [ ] **Step 2: Backend tests (unchanged, regression guard)**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: PASS — all tests green (no backend changes).

- [ ] **Step 3: Playwright e2e**

Run: `cd frontend && npx playwright test` (stop app first with `./down.sh` if ports 5173/8000 are busy)
Expected: PASS — full flow still passes.

- [ ] **Step 4: Restart app and commit**

Run: `./up.sh`, then `git add -A && git commit -m "chore: verify restore-on-load against full local suite"` (or nothing to commit).

---

## Self-Review

- **Spec coverage:** CLEAR button (Task 2) + reducer event (Task 1) + initial verification (Task 3) + restore-on-load (Task 4) + final verification (Task 5). All covered.
- **Placeholders:** none — every step has concrete code/commands.
- **Type consistency:** `run_sync`/`run_started` event shapes match the existing `ProgressEvent` union; `toResultRow` produces `ResultRow` as consumed by `run_sync`; `dispatch` typed via `useReducer`.

