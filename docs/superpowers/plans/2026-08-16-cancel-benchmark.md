# Cancel Running Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While a benchmark run is in progress, let the user cancel it: the RUN BENCHMARK button toggles to CANCEL BENCHMARK, the backend stops the current config, marks the run `aborted`, and preserves the configs that already completed.

**Architecture:** The backend keeps an `_cancel_requested` flag on `AppState`. `start_run` resets it; a new `POST /benchmarks/cancel` endpoint sets it and aborts the active runner; `_run_job` checks the flag at the top of each config loop iteration and breaks out, marking the run `aborted`. The frontend adds a `cancelBenchmark()` client call, a `onCancelRun` handler in `App`, and toggles the RunPanel button between RUN BENCHMARK and CANCEL BENCHMARK based on `running`. Status mapping folds `aborted` into the existing `status.cancelled` key so the UI renders "CANCELLED".

**Tech Stack:** Python 3.11+ / FastAPI (backend), React 18 + TypeScript + Vitest + react-i18next (frontend), 15 locale JSON files, Playwright e2e.

**Status:** Implemented and verified on `feature/cancel-benchmark` (commit `37160bc`). This document records the implementation retroactively so the feature ships with docs in the integration PR.

---

## File Structure

- **Modify:** `backend/app/api.py` — `_cancel_requested` flag, `POST /benchmarks/cancel`, loop-top check in `_run_job`, finally reset.
- **Modify:** `backend/tests/test_api.py` — cancel 409 / abort / completed-configs tests.
- **Modify:** `frontend/src/api/client.ts` — `cancelBenchmark()`.
- **Modify:** `frontend/src/App.tsx` — `onCancelRun` handler, pass `onCancel` to RunPanel, ignore `aborted`/`cancelled` in status-error paths.
- **Modify:** `frontend/src/components/RunPanel.tsx` — toggle button RUN ↔ CANCEL, `onCancel` prop.
- **Modify:** `frontend/src/components/RunPanel.test.tsx` — toggle render tests.
- **Modify:** `frontend/src/App.test.tsx` — cancel handler tests.
- **Modify:** `frontend/src/i18n/status.ts` — `aborted → status.cancelled`.
- **Modify:** `frontend/src/i18n/locales/*/translation.json` (15 files) — `common.cancelBenchmark`.
- **Modify:** `frontend/e2e/mock-server.ts` — `/api/benchmarks/cancel` handler.
- **Modify:** `frontend/e2e/flow.spec.ts` — RUN → CANCEL toggle e2e test.

---

### Task 1: Backend — cancel endpoint and abort handling

**Files:**
- Modify: `backend/app/api.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Add the `_cancel_requested` flag to `AppState`**

In `backend/app/api.py`, in `class AppState.__init__`, next to `self._active_run_id`:

```python
        self._active_run_id: int | None = None
        self._cancel_requested = False
```

- [ ] **Step 2: Reset the flag in `start_run`**

In `start_run`, inside the existing `with s._state_lock:` block:

```python
    with s._state_lock:
        s._job_active = True
        s._cancel_requested = False
```

- [ ] **Step 3: Add the `POST /benchmarks/cancel` endpoint**

```python
@router.post("/benchmarks/cancel")
async def cancel_run():
    s = _require_state()
    with s._state_lock:
        if not s._job_active or s._active_run_id is None:
            raise HTTPException(409, "No benchmark is running")
        s._cancel_requested = True
    runner = s.runner
    if runner is not None:
        runner.abort()
    return {"ok": True}
```

- [ ] **Step 4: Check the flag at the top of the config loop in `_run_job`**

```python
                for i, cfg in enumerate(configs):
                    if s._cancel_requested:
                        status = "aborted"
                        break
```

- [ ] **Step 5: Reset the flag in the `finally` block of `_run_job`**

```python
        s._active_run_id = None
        with s._state_lock:
            s._job_active = False
            s._cancel_requested = False
```

- [ ] **Step 6: Write and run the backend tests**

Tests (in `backend/tests/test_api.py`):

- `test_cancel_benchmark_with_no_active_run_409` — `POST /api/benchmarks/cancel` with nothing running → `409`.
- `test_cancel_benchmark_aborts_running_run` — start a run, cancel, poll until status is `aborted`; assert `proc.killed`, `detail["status"] == "aborted"`, `result_status == "aborted"`, and a follow-up cancel → `200`.
- `test_cancel_benchmark_keeps_completed_configs` — run two configs, cancel after the first completes; assert one `ok` result, overall status `aborted`.

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -k cancel -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: cancel running benchmark run"
```

---

### Task 2: Frontend — CANCEL BENCHMARK button and wiring

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/RunPanel.tsx`
- Modify: `frontend/src/i18n/status.ts`
- Modify: `frontend/src/i18n/locales/*/translation.json` (15 files)

- [ ] **Step 1: Add `cancelBenchmark` to the API client**

In `frontend/src/api/client.ts`, next to the other run calls:

```ts
  cancelBenchmark: () => request<{ ok: boolean }>("/benchmarks/cancel", { method: "POST" }),
```

- [ ] **Step 2: Add the `onCancelRun` handler in `App`**

```ts
  const onCancelRun = useCallback(async () => {
    setError(null);
    setErrorContext(null);
    try {
      await api.cancelBenchmark();
    } catch (err) {
      const apiErr = err as { status?: number };
      if (apiErr.status === 409) return;
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);
```

- [ ] **Step 3: Pass `onCancel` to RunPanel**

```tsx
                onRun={onRun}
                onCancel={onCancelRun}
```

- [ ] **Step 4: Suppress status errors for aborted/cancelled runs**

In both run-status handlers, widen the guard:

```ts
        if (status && status !== "completed" && status !== "aborted" && status !== "cancelled") {
```

- [ ] **Step 5: Toggle the RunPanel button**

```tsx
        {running ? (
          <button onClick={onCancel}>{t("common.cancelBenchmark")}</button>
        ) : (
          <button onClick={onRun} disabled={!canRun}>
            {t("common.runBenchmark")}
          </button>
        )}
```

- [ ] **Step 6: Fold `aborted` into the cancelled status key**

In `frontend/src/i18n/status.ts`:

```ts
  aborted: "status.cancelled",
```

- [ ] **Step 7: Add `common.cancelBenchmark` to all 15 locales**

Insert `"cancelBenchmark": "<translation>",` in the `common` block of each locale (e.g. `en` → `"CANCEL BENCHMARK"`, `de` → `"BENCHMARK ABBRECHEN"`, `ja` → `"ベンチマークをキャンセル"`).

- [ ] **Step 8: Run frontend tests and typecheck**

Run: `cd frontend && npx tsc -b && npx vitest run src/components/RunPanel.test.tsx src/App.test.tsx`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/App.tsx frontend/src/components/RunPanel.tsx frontend/src/i18n frontend/src/App.test.tsx frontend/src/components/RunPanel.test.tsx
git commit -m "feat: cancel running benchmark run"
```

---

### Task 3: E2E and full verification

**Files:**
- Modify: `frontend/e2e/mock-server.ts`
- Modify: `frontend/e2e/flow.spec.ts`

- [ ] **Step 1: Add the mock-server cancel handler**

In `frontend/e2e/mock-server.ts`, before the generic `/api/benchmarks` GET handler:

```ts
  } else if (req.url?.startsWith("/api/benchmarks/cancel")) {
    Object.assign(body, { ok: true });
  }
```

- [ ] **Step 2: Add the toggle e2e test**

In `frontend/e2e/flow.spec.ts`, after the "full flow" test:

```ts
test("RUN toggles to CANCEL and back after cancelling", async ({ page }) => {
  await page.goto("http://localhost:5173");
  await page.getByPlaceholder(/huggingface/i).fill("org/model");
  await page.getByRole("button", { name: /analyze/i }).click();
  await expect(page.getByText(/server llama.cpp/i)).toBeVisible();
  await page.getByRole("button", { name: /generate/i }).click();
  await expect(page.getByText(/llama-server/i).first()).toBeVisible();
  await page.getByRole("button", { name: /run benchmark/i }).click();
  await expect(page.getByRole("button", { name: /cancel benchmark/i })).toBeVisible();
  await page.getByRole("button", { name: /cancel benchmark/i }).click();
  await expect(page.getByRole("button", { name: /run benchmark/i })).toBeEnabled();
});
```

- [ ] **Step 3: Run the full suite**

Run:
- `cd backend && .venv/bin/python -m pytest -v`
- `cd frontend && npx tsc -b && npx vitest run`
- `cd frontend && npx playwright test`

Expected: all PASS (backend 289 passed, 1 skipped; vitest 113 passed; e2e 8 passed at the time of implementation).

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e
git commit -m "test: cancel benchmark e2e coverage"
```
