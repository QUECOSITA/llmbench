# Clear Benchmark History Design

**Date:** 2026-08-12
**Status:** Approved

## Goal

Let the user clear the benchmark history from the `/results` page. A **CLEAR HISTORY** button removes every benchmark run (and its configs/results) from the SQLite DB, plus the raw `speed-bench-*.json` artifact files that accumulate in `~/.llmbench`. Downloaded models and the `models`/`servers` tables are untouched.

## Approach

**Backend — `backend/app/db.py`**

Add `clear_history(conn)`:
- `DELETE FROM results; DELETE FROM configs; DELETE FROM runs;` in FK-safe order (the DB runs with `PRAGMA foreign_keys=ON`).
- Commit. Leaves `models` and `servers` alone.

**Backend — `backend/app/api.py`**

Add `DELETE /api/benchmarks`, patterned after the existing `delete_model` endpoint:
- Under `s._state_lock`, if `s._job_active` → raise `ApiError(409, "A benchmark is already running", context={"active_run": ...})`. This mirrors the guard in `start_run`.
- Call `db_mod.clear_history(s.conn)`.
- Best-effort delete of speed-bench artifacts: `for p in s.settings.data_dir.glob("speed-bench-*.json")` unlink each, ignoring `OSError`.
- Return `{"ok": True}`.

**Frontend — `frontend/src/api/client.ts`**

Add `clearRuns: () => request<{ ok: boolean }>("/benchmarks", { method: "DELETE" })`.

**Frontend — `frontend/src/pages/Results.tsx`**

Add a **CLEAR HISTORY** button in the panel header row:
- Disabled when any listed run has status `running` or `queued` (mirrors the backend 409 guard).
- `onClick`: `window.confirm("Clear all benchmark history? This removes every run and its raw speed-bench outputs. Downloaded models are kept.")`; on accept call `api.clearRuns()` then `setRuns([])`.
- On API error, surface a short error line instead of crashing.

## Data flow

- `GET /api/benchmarks` (unchanged) lists runs; the `/results` page renders them.
- `CLEAR HISTORY` → `DELETE /api/benchmarks` → `clear_history` deletes runs/configs/results and the endpoint unlinks speed-bench artifacts.
- After success the frontend sets the run list to `[]`.

## Error handling

- **409** (benchmark running): the endpoint refuses; the frontend surfaces the message.
- Best-effort artifact deletion never fails the request (OS errors ignored).
- Frontend `api.clearRuns()` rejection renders a short error line; the list stays as-is.

## Testing

- Backend `test_db.py`: `clear_history` empties runs/configs/results but keeps models.
- Backend `test_api.py`: `DELETE /api/benchmarks` returns `{ok: true}` and clears runs; returns 409 when a job is active; deletes `speed-bench-*.json` files in `data_dir`.
- Frontend `client.test.ts`: `clearRuns` issues `DELETE http://localhost:8000/api/benchmarks`.
- Frontend `Results.test.tsx`: confirm → calls `clearRuns` and shows the empty state; cancel → no API call; button disabled while a run is active.
- Frontend `e2e/mock-server.ts`: add `GET /api/benchmarks` returning seeded runs and `DELETE /api/benchmarks` clearing them.
- Frontend `e2e/flow.spec.ts`: visit `/results`, click CLEAR HISTORY, accept the dialog, list empties.
- Full suite: `pytest`, `tsc -b`, `vitest run`, `playwright test`.

## Out of scope

- Deleting downloaded models or anything in the HF cache (the existing per-model REMOVE covers that).
- Reset of SQLite AUTOINCREMENT counters — runs keep their ids; new runs continue numbering.
- Any change to the main bench page's ranked-results CLEAR (that only clears in-memory results).
