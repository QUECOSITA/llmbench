# Clear Benchmark History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CLEAR HISTORY button to the `/results` page that deletes every benchmark run (configs/results included) from the SQLite DB and the raw `speed-bench-*.json` artifact files, without touching downloaded models.

**Architecture:** Backend `DELETE /api/benchmarks` endpoint (patterned after the existing `delete_model` endpoint) calls a new `db.clear_history()` that deletes rows in FK-safe order, then best-effort unlinks `speed-bench-*.json` files from `data_dir`. The endpoint refuses (409) while a job is active. Frontend `api.clearRuns()` calls it; the `Results` page renders a CLEAR HISTORY button (disabled while any listed run is `running`/`queued`) that confirms via `window.confirm`, then clears the list on success.

**Tech Stack:** Python 3 / FastAPI / sqlite3; React 18, TypeScript 5, Vitest 4 + Testing Library, Vite 7, Playwright.

---

## File Structure

- **Modify** `backend/app/db.py` — add `clear_history(conn)`.
- **Modify** `backend/app/api.py` — add `DELETE /api/benchmarks` endpoint (after `run_detail`, line 756).
- **Test** `backend/tests/test_db.py` — `clear_history` behavior.
- **Test** `backend/tests/test_api.py` — endpoint ok/clear, artifact deletion, 409 guard.
- **Modify** `frontend/src/api/client.ts` — add `clearRuns`.
- **Test** `frontend/src/api/client.test.ts` — `clearRuns` issues `DELETE`.
- **Modify** `frontend/src/pages/Results.tsx` — CLEAR HISTORY button + error line.
- **Test** `frontend/src/pages/Results.test.tsx` — confirm/cancel/disabled behavior.
- **Modify** `frontend/e2e/mock-server.ts` — `GET /api/benchmarks` + `DELETE /api/benchmarks` routes.
- **Test** `frontend/e2e/flow.spec.ts` — e2e clear-history flow.

---

## Task 1: `clear_history` DB function

**Files:**
- Modify: `backend/app/db.py` (append after `fail_stale_runs`, line 185)
- Test: `backend/tests/test_db.py`

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_db.py`, and add `clear_history` + `list_configs` to the import on line 5:

Update the import on line 5 to:

```python
from app.db import init_db, upsert_model, get_model, list_models, create_run, finish_run, save_result, list_runs, get_results_for_run, create_config, fail_stale_runs, get_run_status, set_run_status, get_active_run, clear_history, list_configs
```

Append this test:

```python
def test_clear_history_empties_runs_but_keeps_models(tmp_path):
    conn = init_db(tmp_path / "test.db")
    upsert_model(conn, repo_id="org/model", server_id="llama.cpp", format="hf", local_path="/x", status="downloaded")
    run_id = create_run(conn, repo_id="org/model", requested_n=2)
    finish_run(conn, run_id, status="completed")
    cfg_id = create_config(conn, run_id=run_id, server_id="llama.cpp", model_id=1,
                           flag_conf_json=[], serving_command="x", bench_command="y")
    save_result(conn, config_id=cfg_id, prompt_processing_tps=1200.0, decode_tps=86.4,
                duration_s=30.0, output_snippet="", status="ok")
    assert len(list_runs(conn)) == 1
    assert len(list_configs(conn, run_id)) == 1

    clear_history(conn)

    assert list_runs(conn) == []
    assert list_configs(conn, run_id) == []
    assert len(list_models(conn)) == 1
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_db.py -q`
Expected: FAIL — `ImportError: cannot import name 'clear_history'`.

- [ ] **Step 3: Write minimal implementation** — append to `backend/app/db.py`:

```python
def clear_history(conn):
    """Delete all benchmark runs, configs, and results. Keeps models/servers."""
    conn.execute("DELETE FROM results")
    conn.execute("DELETE FROM configs")
    conn.execute("DELETE FROM runs")
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_db.py -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/db.py backend/tests/test_db.py
git commit -m "feat: add clear_history to wipe benchmark runs"
```

---

## Task 2: `DELETE /api/benchmarks` endpoint

**Files:**
- Modify: `backend/app/api.py` (append after `run_detail`, line 756)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_api.py`:

```python
def test_clear_history_endpoint_deletes_runs_and_artifacts(client, tmp_path):
    import app.api as api_mod
    from app import db as db_mod
    run_id = db_mod.create_run(api_mod.state.conn, "org/model", 1)
    db_mod.set_run_status(api_mod.state.conn, run_id, "completed")
    (tmp_path / "speed-bench-abc123.json").write_text("{}")

    assert len(client.get("/api/benchmarks").json()["runs"]) == 1
    assert (tmp_path / "speed-bench-abc123.json").exists()
    assert (tmp_path / "llmbench.db").exists()

    r = client.delete("/api/benchmarks")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert client.get("/api/benchmarks").json()["runs"] == []
    assert not (tmp_path / "speed-bench-abc123.json").exists()
    assert (tmp_path / "llmbench.db").exists()


def test_clear_history_409_when_job_active(client):
    import app.api as api_mod
    api_mod.state._job_active = True
    try:
        r = client.delete("/api/benchmarks")
        assert r.status_code == 409
        assert r.json()["detail"] == "A benchmark is already running"
        assert r.json()["context"]["active_run"] is not None
    finally:
        api_mod.state._job_active = False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -k "clear_history" -q`
Expected: FAIL — `client.delete("/api/benchmarks")` → 405 Method Not Allowed (route not defined).

- [ ] **Step 3: Write minimal implementation** — insert after `run_detail` (after line 756) in `backend/app/api.py`:

```python
@router.delete("/benchmarks")
async def clear_history():
    s = _require_state()
    with s._state_lock:
        if s._job_active:
            active = db_mod.get_active_run(s.conn)
            raise ApiError(
                409, "A benchmark is already running",
                context={"active_run": active or {"id": s._active_run_id}})
    db_mod.clear_history(s.conn)
    for p in s.settings.data_dir.glob("speed-bench-*.json"):
        try:
            p.unlink()
        except OSError:
            pass
    return {"ok": True}
```

`ApiError`, `db_mod`, `s._state_lock`, `s._job_active`, `s.settings.data_dir` are all already in scope in `api.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -k "clear_history" -q`
Expected: PASS (2 new tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: add DELETE /api/benchmarks to clear benchmark history"
```

---

## Task 3: `api.clearRuns` frontend client

**Files:**
- Modify: `frontend/src/api/client.ts:182` (after `listRuns`)
- Test: `frontend/src/api/client.test.ts`

- [ ] **Step 1: Write the failing test** — append to `frontend/src/api/client.test.ts`:

```ts
test("api.clearRuns deletes the benchmark history", async () => {
  const fetchMock = vi.fn(
    (_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) } as Response),
  );
  globalThis.fetch = fetchMock;
  const data = await api.clearRuns();
  expect(data.ok).toBe(true);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("http://localhost:8000/api/benchmarks");
  expect((init as RequestInit).method).toBe("DELETE");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL — `api.clearRuns is not a function`.

- [ ] **Step 3: Write minimal implementation** — in `frontend/src/api/client.ts`, after the `listRuns` line (182):

```ts
  clearRuns: () => request<{ ok: boolean }>("/benchmarks", { method: "DELETE" }),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat: add api.clearRuns to delete benchmark history"
```

---

## Task 4: CLEAR HISTORY button on the Results page

**Files:**
- Modify: `frontend/src/pages/Results.tsx`
- Test: `frontend/src/pages/Results.test.tsx`

- [ ] **Step 1: Write the failing tests** — replace the contents of `frontend/src/pages/Results.test.tsx` with:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Results } from "./Results";

vi.mock("./api/client", () => ({
  api: {
    clearRuns: vi.fn().mockResolvedValue({ ok: true }),
  },
}));

function renderResults(initialRuns: Parameters<typeof Results>[0]["initialRuns"]) {
  return render(
    <MemoryRouter initialEntries={["/results"]}>
      <Routes>
        <Route path="/results" element={<Results initialRuns={initialRuns} />} />
      </Routes>
    </MemoryRouter>,
  );
}

const RUNS = [
  { id: 1, repo_id: "org/model", requested_n: 2, created_at: "", status: "completed" },
];

test("shows empty state when no runs", () => {
  renderResults([]);
  expect(screen.getByText(/no benchmark runs yet/i)).toBeInTheDocument();
});

test("CLEAR HISTORY confirms then calls clearRuns and shows the empty state", async () => {
  const { api } = await import("./api/client");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  renderResults(RUNS);
  fireEvent.click(screen.getByRole("button", { name: /clear history/i }));
  expect(window.confirm).toHaveBeenCalledWith(expect.stringMatching(/clear all benchmark history/i));
  await waitFor(() => expect(api.clearRuns).toHaveBeenCalledTimes(1));
  expect(screen.getByText(/no benchmark runs yet/i)).toBeInTheDocument();
});

test("CLEAR HISTORY without confirmation does not call clearRuns", async () => {
  const { api } = await import("./api/client");
  vi.spyOn(window, "confirm").mockReturnValue(false);
  renderResults(RUNS);
  fireEvent.click(screen.getByRole("button", { name: /clear history/i }));
  expect(api.clearRuns).not.toHaveBeenCalled();
  expect(screen.getByText(/#1 · org\/model/i)).toBeInTheDocument();
});

test("CLEAR HISTORY is disabled while a run is active", () => {
  renderResults([
    { id: 1, repo_id: "org/model", requested_n: 1, created_at: "", status: "running" },
  ]);
  expect(screen.getByRole("button", { name: /clear history/i })).toBeDisabled();
});
```

Update the imports at the top of the test file — `waitFor` and `fireEvent` are needed. Change line 1 to:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/Results.test.tsx`
Expected: FAIL — `getByRole("button", { name: /clear history/i })` throws (button doesn't exist).

- [ ] **Step 3: Write minimal implementation** — replace the contents of `frontend/src/pages/Results.tsx` with:

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, RunSummary } from "../api/client";

export function Results({ initialRuns }: { initialRuns?: RunSummary[] }) {
  const [runs, setRuns] = useState<RunSummary[] | null>(initialRuns ?? null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (runs === null) {
      api.listRuns().then((d) => setRuns(d.runs)).catch(() => setRuns([]));
    }
  }, [runs]);

  const runActive = runs?.some((r) => r.status === "running" || r.status === "queued") ?? false;

  const onClear = async () => {
    if (!window.confirm(
      "Clear all benchmark history? This removes every run and its raw speed-bench outputs. Downloaded models are kept.",
    )) return;
    setError(null);
    try {
      await api.clearRuns();
      setRuns([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <section className="panel">
      <div className="row">
        <span className="panel-cap" style={{ marginBottom: 0 }}>RESULTS · ALL RUNS</span>
        {runs && runs.length > 0 && (
          <button className="btn-neutral" onClick={onClear} disabled={runActive}>
            CLEAR HISTORY
          </button>
        )}
      </div>
      <p style={{ color: "var(--anode)", fontSize: 12 }}>
        <Link to="/" className="results-link">← back to bench</Link>
      </p>
      {error && <p style={{ color: "var(--accent)", fontSize: 12 }}>Error: {error}</p>}
      {!runs || runs.length === 0 ? (
        <p style={{ color: "var(--anode)" }}>No benchmark runs yet.</p>
      ) : (
        <ul>
          {runs.map((r) => (
            <li key={r.id}>
              #{r.id} · {r.repo_id} · {r.requested_n} configs · {r.status}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

Uses the existing `.row` and `btn-neutral` classes already used elsewhere (`App.tsx:569-579`, `app.css:67`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/Results.test.tsx`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Results.tsx frontend/src/pages/Results.test.tsx
git commit -m "feat: add CLEAR HISTORY button to results page"
```

---

## Task 5: e2e mock-server routes + flow test

**Files:**
- Modify: `frontend/e2e/mock-server.ts`
- Modify: `frontend/e2e/flow.spec.ts`

- [ ] **Step 1: Add runs state + routes to the mock server**

In `frontend/e2e/mock-server.ts`, after the `seedModel(...)` line (line 7), add:

```ts
const runs = [{ id: 1, repo_id: "org/model", requested_n: 1, created_at: "", status: "completed" }];
```

In the handler, replace the `POST /api/benchmarks` branch (line 75-76) with:

```ts
  } else if (req.method === "GET" && req.url?.startsWith("/api/benchmarks") && req.url !== "/api/benchmarks/") {
    Object.assign(body, { runs });
  } else if (req.method === "POST" && req.url?.startsWith("/api/benchmarks")) {
    Object.assign(body, { run_id: 1 });
  } else if (req.method === "DELETE" && req.url?.startsWith("/api/benchmarks")) {
    runs.length = 0;
    Object.assign(body, { ok: true });
```

The GET branch must come before the existing `req.url?.startsWith("/api/benchmarks/")` run-detail branch so `/api/benchmarks` (exact) returns the run list while `/api/benchmarks/1` still returns the detail shape.

- [ ] **Step 2: Write the failing e2e test** — append to `frontend/e2e/flow.spec.ts`:

```ts
test("CLEAR HISTORY empties the results list", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("http://localhost:5173/results");
  await expect(page.getByText(/#1 · org\/model/i)).toBeVisible();
  await page.getByRole("button", { name: /clear history/i }).click();
  await expect(page.getByText(/no benchmark runs yet/i)).toBeVisible();
});
```

- [ ] **Step 3: Run e2e to verify it passes**

Run: `./down.sh` (if ports 5173/8000 are busy), then `cd frontend && npx playwright test`
Expected: PASS — all flow tests including the new clear-history test.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/mock-server.ts frontend/e2e/flow.spec.ts
git commit -m "test: e2e for clearing benchmark history"
```

---

## Task 6: Full local suite verification

- [ ] **Step 1: Backend tests**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: PASS — all tests green.

- [ ] **Step 2: Frontend typecheck + unit tests**

Run: `cd frontend && npx tsc -b && npx vitest run`
Expected: PASS — no type errors, all component/ws/api tests green.

- [ ] **Step 3: Playwright e2e**

Run: `./down.sh` (if ports busy), then `cd frontend && npx playwright test`
Expected: PASS — full flow + clear-history tests green.

- [ ] **Step 4: Start app and commit**

Run: `./up.sh`, then:

```bash
git add -A
git commit -m "chore: verify clear-benchmark-history against full local suite" || echo "nothing to commit"
```

---

## Self-Review

- **Spec coverage:** DB clear (Task 1), endpoint + 409 + artifacts (Task 2), client (Task 3), button/confirm/disabled/error (Task 4), e2e (Task 5), verification (Task 6). All covered.
- **Placeholders:** none — every step has concrete code and commands.
- **Type consistency:** `api.clearRuns()` returns `{ ok: boolean }` matching `request`; `RunSummary` shape reused for `initialRuns`; `set_run_status`/`create_run`/`get_active_run` match existing `db.py` signatures; mock-server route ordering keeps `/api/benchmarks/1` detail intact.
