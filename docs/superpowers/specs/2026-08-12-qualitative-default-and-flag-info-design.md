# Qualitative Default + Speed-Bench Flag Info Design

**Date:** 2026-08-12
**Status:** Approved

## Goal

Two changes to speed-bench:

1. Change the default `--bench` value from `throughput_1k` to `qualitative`, and align the rest of the default flags string with the upstream `speed_bench.py` CLI defaults (`--osl 4096`), keeping `--limit 1` so default runs stay fast smoke tests.
2. Show a small info block next to the SPEED-BENCH FLAGS textarea in the config bank documenting the accepted values for `--bench`, `--category`, and `--limit`. The `--category` info must be dynamic: it shows the categories valid for the `--bench` value currently typed in the textarea.

## Approach

**Change 1 — default flags string (`backend/app/servers.py`)**

- `speed_bench_default_flags(osl: int = 4096)` returns `--bench qualitative --category all --limit 1 --osl {osl}`.
- `backend/app/config.py`: `speed_bench_osl: int = 4096` (matches the CLI `--osl` default; still overridable via `LLMBENCH_SPEED_BENCH_OSL`).

Rationale: the CLI's own defaults are `--bench qualitative --category all --osl 4096 --limit None`. We keep `--limit 1` (not `None`) because a no-limit default would run the entire qualitative dataset. This is user-approved.

The rest of the speed-bench pipeline (parse/validate/build command) is unchanged; it already works off whatever flags string is set.

**Change 2 — info block next to the SPEED-BENCH FLAGS textarea**

Single source of truth for the accepted values lives in the backend constants (`SPEED_BENCH_BENCHES`, `SPEED_BENCH_CATEGORIES` in `servers.py`). Expose them through a new endpoint and render dynamically in the frontend:

- **New endpoint** `GET /api/speed-bench/info` in `backend/app/api.py` returning:
  ```json
  { "benches": [...], "categories": { "<bench>": [...] } }
  ```
  Built directly from `SPEED_BENCH_BENCHES` / `SPEED_BENCH_CATEGORIES`.
- **`frontend/src/api/client.ts`**: add `api.getSpeedBenchInfo()`.
- **`frontend/src/App.tsx`**: fetch once on mount (like `getServers`), store in state, pass down to `ConfigBank` as a prop.
- **`frontend/src/components/ConfigBank.tsx`**: for rows with `bench_tool === "speed-bench"`, render a small monospace info block under the SPEED-BENCH FLAGS textarea:
  - `--bench` → `qualitative | throughput_1k | throughput_2k | throughput_8k | throughput_16k | throughput_32k`
  - `--category` → `all, or (for bench "<current>")`: comma-separated list for the `--bench` value parsed out of the textarea (updates as the user types). Empty/unknown bench → `all, or one of <union of all categories>`.
  - `--limit` → `optional int — max samples per category`.
- **`frontend/src/components/ConfigBank.test.tsx`**: new tests for rendering the info block and for it updating when the typed `--bench` changes.
- **`frontend/src/App.test.tsx`**: add `getSpeedBenchInfo` to the mocked `api` so the new mount-time fetch resolves.
- **`frontend/e2e/mock-server.ts`**: add the `/api/speed-bench/info` route so e2e doesn't 404 on it; the frontend also tolerates fetch failure gracefully (info block simply not shown).

## Data flow

- Backend constants (`SPEED_BENCH_BENCHES`, `SPEED_BENCH_CATEGORIES`) are the single source of truth.
- `GET /api/speed-bench/info` serializes them; the frontend fetches once at app mount.
- ConfigBank receives the info via props and renders it; the `--category` line recomputes on every `bench_flags` change by parsing the current `--bench` value.

## Error handling

- Frontend: if `getSpeedBenchInfo()` rejects (e.g. backend down), the info block is simply omitted — no error banner, no crash.
- Backend: the endpoint is read-only and has no failure modes beyond routing; no validation changes.

## Testing

- Backend `test_api.py`: `GET /api/speed-bench/info` returns the benches and per-bench categories matching the constants.
- Backend `test_servers.py`: update `test_speed_bench_default_flags` to the new default string (`--bench qualitative --category all --limit 1 --osl 4096`) and `osl=256` form.
- Backend `test_config.py`: `speed_bench_osl` default is now `4096`.
- Backend `test_api.py`: generated `bench_flags` default assertions updated to the qualitative string.
- Frontend `ConfigBank.test.tsx`: info block renders benches + categories for the current bench; editing the flags to a different `--bench` updates the category line.
- Frontend `App.test.tsx`: mount calls `getSpeedBenchInfo`; run payload round-trip test updated to the new default flags string where needed.
- Full suite: `pytest`, `tsc -b`, `vitest run`, `playwright test`.

## Out of scope

- Historical specs/plans under `docs/superpowers/` are not rewritten (they record past decisions).
- No changes to flag parsing/validation (`parse_speed_bench_flags`, `validate_speed_bench_flags`) — the qualitative bench already validates correctly.
- README.md line 22: the speed-bench bullet currently says "always runs with `--limit 1 --category all --bench throughput_1k`"; update it to reflect the new qualitative default (`--bench qualitative --category all --limit 1 --osl 4096`).
