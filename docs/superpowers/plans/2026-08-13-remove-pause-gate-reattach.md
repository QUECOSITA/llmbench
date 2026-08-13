# Remove Pause Gate + Re-attach to Running Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the real-time bench panel deadlock — a run can hang forever at the backend continue gate when a browser is connected (blocking all new runs with 409), and a page reload during an active run never re-attaches to it. Remove the pause/continue gate entirely and make the panel re-attach to an active run on load.

**Architecture:** Backend drops the `pause` param, the `config_wait` broadcast, the continue gate (`_await_continue`), and the `/benchmarks/continue` endpoint; `_run_job` streams all configs straight through. Frontend removes the PAUSE checkbox, waiting/continue UI, and `config_wait` reducer state, and the App mount effect re-attaches to a running/queued run via `watchRun` so WS `bench_log` events stream after a reload.

**Tech Stack:** FastAPI + asyncio (backend), React 18 + TS + Vitest (frontend), Playwright (e2e).

---

## Root Cause

1. `_await_continue` (backend/app/api.py:716-730) only auto-advances when `len(_ws_clients) == 0`. With the app open (WS connected), a run paused at the continue gate waits forever — run 154 sat "running" for 35+ min, no process, no events, and every new `POST /benchmarks` returned 409.
2. The App mount effect (App.tsx:237-261) restores only the latest **non-running** run. After a reload during an active run, `state.runId` stays null, so WS events for the running run are dropped by the reducer (`event.run_id === state.runId` mismatch) and the console shows nothing — "the panel outputting benches in real time" appears dead.

Decision (confirmed with user): **remove the pause gate entirely.**

---

## File Structure

- **Modify** `backend/app/api.py` — remove pause/continue gate.
- **Modify** `backend/tests/test_api.py` — replace pause tests with straight-through tests.
- **Modify** `frontend/src/api/client.ts` — remove `continueRun`.
- **Modify** `frontend/src/App.tsx` — remove pause/continue UI wiring; re-attach to active run on load.
- **Modify** `frontend/src/ws/useBenchmarkProgress.ts` — remove `config_wait`/`waiting`.
- **Modify** `frontend/src/components/RunPanel.tsx` — remove PAUSE/continue UI.
- **Modify** `frontend/src/ws/useBenchmarkProgress.test.ts`, `frontend/src/components/RunPanel.test.tsx`, `frontend/src/App.test.tsx` — update tests.

---

### Task 1: Backend — remove the pause/continue gate

**Files:**
- Modify: `backend/app/api.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests** — replace the pause/continue tests in `backend/tests/test_api.py`:

Delete:
- `test_pause_run_streams_and_waits_for_continue` (lines ~1019-1060)
- `test_failed_config_with_pause_does_not_wait_for_continue` (lines ~1063-1103)
- `test_pause_false_runs_straight_through` (lines ~1106-1132)
- `test_pause_run_auto_advances_when_no_clients` (lines ~1135-1161)
- `test_continue_with_no_pending_run_409` (lines ~1164-1166)
- `test_double_continue_does_not_skip_next_wait` (lines ~1169-1211)

Add in their place:

```python
def test_run_streams_straight_through_with_ws_client(client, monkeypatch):
    """A connected browser must never wedge the run at a continue gate: the run
    completes on its own and _job_active clears so the next run is not blocked."""
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_create(*a, **k):
        return FakeProcess(FAKE_BENCH.encode())

    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    class FakeWs:
        pass

    ws = FakeWs()
    api_mod.state._ws_clients.add(ws)
    try:
        cfg = {
            "server_id": "llama.cpp",
            "flags": {"-c": "4096"},
            "model_id": "org/model",
            "serving_command": "llama-server -m x",
            "bench_command": ["llama-bench", "-m", "x"],
        }
        r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg]})
        assert r.status_code == 200
        run_id = r.json()["run_id"]

        assert _poll(lambda: api_mod.db_mod.get_run_status(api_mod.state.conn, run_id) == "completed")
        assert not any(e["type"] == "config_wait" for e in events)
        assert any(e["type"] == "bench_log" for e in events)
        assert api_mod.state._job_active is False

        r2 = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg]})
        assert r2.status_code == 200
    finally:
        api_mod.state._ws_clients.discard(ws)


def test_run_completes_straight_through_with_failed_config(client, monkeypatch):
    """A failed config must not block; the run reaches a terminal status and the
    next run is not blocked by a stale _job_active."""
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_create(*a, **k):
        return FakeProcess(b"boom\n", rc=1)

    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    cfg = {
        "server_id": "llama.cpp",
        "flags": {"-c": "4096"},
        "model_id": "org/model",
        "serving_command": "llama-server -m x",
        "bench_command": ["llama-bench", "-m", "x"],
    }
    r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg]})
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    assert _poll(lambda: api_mod.db_mod.get_run_status(api_mod.state.conn, run_id) == "failed")
    assert not any(e["type"] == "config_wait" for e in events)
    assert api_mod.state._job_active is False

    r2 = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg]})
    assert r2.status_code == 200


def test_run_detail_has_no_waiting_field(client, monkeypatch):
    async def fake_create(*a, **k):
        return FakeProcess(FAKE_BENCH.encode())

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    cfg = {
        "server_id": "llama.cpp",
        "flags": {"-c": "4096"},
        "model_id": "org/model",
        "serving_command": "llama-server -m x",
        "bench_command": ["llama-bench", "-m", "x"],
    }
    r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg]})
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    assert _poll(lambda: bool(client.get(f"/api/benchmarks/{run_id}").json()["results"]))
    detail = client.get(f"/api/benchmarks/{run_id}").json()
    assert "waiting" not in detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_api.py -x -q`
Expected: `ModuleNotFoundError`/`AttributeError` (`_continue_queue` still exists; new tests reference behavior that still broadcasts `config_wait`) — the three new tests fail.

- [ ] **Step 3: Implement backend changes** in `backend/app/api.py`:

Delete `AUTO_ADVANCE_GRACE_S = 3.0` (line 52).

In `AppState.__init__` delete: `self._continue_queue: asyncio.Queue | None = None` (line 152).

In `start_run` (lines ~627-631) replace:

```python
    pause = bool(payload.get("pause", True))
    run_id = db_mod.create_run(s.conn, repo_id, len(configs))
    with s._state_lock:
        s._job_active = True
    asyncio.create_task(_run_job(s, run_id, configs, pause=pause))
    return {"run_id": run_id}
```

with:

```python
    run_id = db_mod.create_run(s.conn, repo_id, len(configs))
    with s._state_lock:
        s._job_active = True
    asyncio.create_task(_run_job(s, run_id, configs))
    return {"run_id": run_id}
```

Delete the `continue_run` endpoint (lines ~635-645):

```python
@router.post("/benchmarks/continue")
async def continue_run(payload: dict):
    ...
```

In `_run_job` (line 648) change signature:

```python
async def _run_job(s: AppState, run_id: int, configs: list[dict], pause: bool = True):
```

to:

```python
async def _run_job(s: AppState, run_id: int, configs: list[dict]):
```

Delete `    s._continue_queue = None` (line 649).

Delete the pause-gate block (lines ~696-701):

```python
                    if pause and result["status"] == "ok":
                        wait_queue: asyncio.Queue = asyncio.Queue()
                        s._continue_queue = wait_queue
                        await broadcast(s, {"type": "config_wait", "run_id": run_id, "index": i})
                        await _await_continue(s, wait_queue)
                        s._continue_queue = None
```

Delete `        s._continue_queue = None` (line 710).

Delete `_await_continue` (lines ~716-730):

```python
async def _await_continue(s: AppState, queue: asyncio.Queue | None) -> None:
    ...
```

Also update the two `test_full_run_completes_and_persists` and `test_run_executes_rebuilt_bench_command_from_edited_serving_command` payloads (lines ~412, ~447) to drop the now-unused `"pause": False` field.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_api.py -q`
Expected: PASS (all existing tests, plus the three new ones).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat(backend): remove pause/continue gate so runs always stream straight through"
```

---

### Task 2: Frontend — remove pause/waiting from the reducer

**Files:**
- Modify: `frontend/src/ws/useBenchmarkProgress.ts`
- Test: `frontend/src/ws/useBenchmarkProgress.test.ts`

- [ ] **Step 1: Write the failing tests** in `frontend/src/ws/useBenchmarkProgress.test.ts`:

Delete:
- `test("run_started clears lines and waiting", ...)` (lines ~136-147) → replace with a version asserting `lines`/`currentCommand` clear and no `waiting` key:
- `test("config_wait sets waiting and run_done clears it", ...)` (lines ~191-197)
- `test("config_start clears waiting from a previous config wait", ...)` (lines ~207-219)
- `test("run_sync clears waiting", ...)` (lines ~221-226)

Replace the first with:

```ts
test("run_started clears lines and currentCommand", () => {
  const prev = {
    ...INITIAL_STATE,
    lines: ["old line"],
    waiting: false,
    currentCommand: "old cmd",
  };
  const next = progressReducer(prev, ev("run_started", 1, { total: 2 }));
  expect(next.lines).toEqual([]);
  expect(next.currentCommand).toBe("");
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/ws/useBenchmarkProgress.test.ts`
Expected: FAIL (deleted tests still reference `config_wait`; `waiting` field still exists in `INITIAL_STATE`).

- [ ] **Step 3: Implement reducer changes** in `frontend/src/ws/useBenchmarkProgress.ts`:

- Remove `"config_wait"` from the event union (line 4).
- Remove `waiting: boolean;` from `ProgressState` (line 34).
- Remove `waiting: false,` from `INITIAL_STATE` (line 47).
- Remove `waiting: false,` from `run_started` (line 62), `config_start` (line 79), `run_done` (line 124), `run_watch` (line 139), `run_sync` (line 156).
- Delete the `config_wait` reducer case (lines ~93-95).
- In `config_start`, remove the `waiting: false,` line only if present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/ws/useBenchmarkProgress.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/ws/useBenchmarkProgress.ts frontend/src/ws/useBenchmarkProgress.test.ts
git commit -m "feat(frontend): drop config_wait/waiting from progress reducer"
```

---

### Task 3: Frontend — remove pause/continue from RunPanel

**Files:**
- Modify: `frontend/src/components/RunPanel.tsx`
- Test: `frontend/src/components/RunPanel.test.tsx`

- [ ] **Step 1: Write the failing tests** in `frontend/src/components/RunPanel.test.tsx`:

Delete:
- `test("waiting shows the continue prompt and Enter triggers onContinue", ...)` (lines ~60-78)
- `test("CONTINUE button also triggers onContinue", ...)` (lines ~80-97)
- `test("PAUSE toggle is disabled while running and reflects its value", ...)` (lines ~99-134)
- `test("Enter does nothing when not waiting", ...)` (lines ~153-170)

Remove `waiting`, `pause`, `onPauseChange`, `onContinue` props from every `render(<RunPanel ... />)` in the remaining tests. Also remove the `fireEvent.keyDown(window, ...)` usages tied to continue.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/RunPanel.test.tsx`
Expected: FAIL (RunPanel still requires the removed props; TS/vitest errors).

- [ ] **Step 3: Implement RunPanel changes** in `frontend/src/components/RunPanel.tsx`:

- Remove from `Props`: `waiting: boolean;`, `pause: boolean;`, `onPauseChange: (paused: boolean) => void;`, `onContinue: () => void;`.
- Remove from destructuring: `waiting`, `pause`, `onPauseChange`, `onContinue`.
- Delete the Enter-to-continue `useEffect` (lines ~46-56).
- Delete the PAUSE `<label>...</label>` block (lines ~66-74).
- Delete the `{waiting && (...)}` continue prompt block (lines ~88-97).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/RunPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/RunPanel.tsx frontend/src/components/RunPanel.test.tsx
git commit -m "feat(frontend): remove PAUSE/continue UI from RunPanel"
```

---

### Task 4: Frontend — remove `continueRun` from api client and App pause wiring

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write the failing tests** in `frontend/src/App.test.tsx`:

- Delete `continueRun: vi.fn().mockResolvedValue({ ok: true }),` (line 26) from the api mock.
- Delete `test("enter-to-continue: waiting prompt continues the run", ...)` (lines ~525-560).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: FAIL (App still renders pause/waiting; deleted test removed).

- [ ] **Step 3: Implement client + App changes**:

In `frontend/src/api/client.ts` remove the `continueRun` method (lines ~166-169).

In `frontend/src/App.tsx`:
- Remove `const [pause, setPause] = useState(true);` (line 111).
- Remove `onContinue` (lines ~376-385).
- Remove `pause,` from the `startBenchmark` payload (line 341).
- Remove `pause` from the `onRun` deps array (line 374).
- Remove `waiting={progressState.waiting}`, `pause={pause}`, `onPauseChange={setPause}`, `onContinue={onContinue}` from the `<RunPanel ...>` props (lines ~558-561).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat(frontend): remove continueRun api and App pause/continue wiring"
```

---

### Task 5: Frontend — re-attach to the active run on load

**Files:**
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write the failing test** in `frontend/src/App.test.tsx`:

```ts
test("re-attaches to an active running run on load and streams it", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.listRuns).mockResolvedValue({
    runs: [{ id: 7, repo_id: "org/model", requested_n: 2, created_at: "", status: "running" }],
  });
  vi.mocked(api.getRun).mockResolvedValue({
    status: "running",
    total: 2,
    results: [],
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  await waitFor(() => expect(screen.getByText(/watching benchmark run #7 in progress/i)).toBeInTheDocument());
  expect(api.getRun).toHaveBeenCalledWith(7);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/App.test.tsx -t "re-attaches"`
Expected: FAIL (no watching message; `getRun(7)` never called).

- [ ] **Step 3: Implement** in `frontend/src/App.tsx` — the mount effect (lines ~237-261). Move it **below** the `watchRun` definition so it can reference it, and rework:

```ts
  useEffect(() => {
    let cancelled = false;
    api
      .listRuns()
      .then(({ runs }) => {
        if (cancelled) return;
        const active = runs.find((r) => r.status === "running" || r.status === "queued");
        if (active) {
          setWatchingRunId(active.id);
          dispatch({ type: "run_started", run_id: active.id, total: active.requested_n ?? 0 });
          if (pollTimerRef.current !== null) window.clearTimeout(pollTimerRef.current);
          watchRun(active.id);
          return;
        }
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
```

Note: because `watchRun` dispatches `run_watch` (which requires `state.runId` to match), and we just dispatched `run_started` for the active run, subsequent WS `bench_log`/`config_start`/`config_done` events for that run are now accepted and stream into the console.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat(frontend): re-attach to an active run on load so the panel streams after reload"
```

---

### Task 6: Full local verification

- [ ] **Step 1: Backend tests**

Run: `cd backend && source .venv/bin/activate && pytest -q`
Expected: PASS.

- [ ] **Step 2: Frontend typecheck + unit tests**

Run: `cd frontend && npx tsc -b && npx vitest run`
Expected: PASS (no TS errors, all tests green).

- [ ] **Step 3: E2E**

Run: `cd frontend && npx playwright test`
Expected: PASS (mock-server doesn't exercise pause; full-flow test uses HTTP poll fallback).

- [ ] **Step 4: Manual browser verification** (local dev, using `./up.sh`/`./down.sh`)

1. Start a run in the browser with the real backend. Confirm the console streams continuously through all configs with no continue prompt.
2. Reload the page mid-run. Confirm the panel shows "watching benchmark run #N in progress" and keeps streaming.
3. Confirm a second run can start immediately after the first completes (no 409 wedge).

- [ ] **Step 5: Final commit**

```bash
git status
git log --oneline -8
```
