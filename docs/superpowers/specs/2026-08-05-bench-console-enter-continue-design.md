# Design: Live benchmark command console + Enter-to-continue in 03 · RUN

## Problem

The 03 · RUN panel currently shows only a `config i/N` label and the two metric
banks (PROMPT PROC t/s, DECODE STAGE t/s). While a benchmark runs, the user
cannot see the actual `bench_command` being executed or its live output, and
configs run straight through without any opportunity to inspect each result.
The backend buffers all command output with `asyncio.subprocess.communicate()`
and surfaces only the last 2000 characters into the DB.

## Goal

In 03 · RUN, under the prompt/decode metric banks, show a console that streams
the executed bench command and its output in real time. After each config
finishes, pause and wait for an Enter keypress before running the next config
(including after the last config, before the run ends). A toggle lets the user
disable the pauses and run straight through while still streaming live.

## Confirmed decisions (from the user)

- Pause happens after **every config, including the last**.
- A **toggle** (default ON) can disable pausing for straight-through runs.
- The console **accumulates** the whole run (all configs' commands + outputs in
  one scrollable log), rather than resetting per config.
- The console shows the **executed** `bench_command` (the editable
  `serving_command` already lives in 02 CONFIG BANK).
- The pause toggle is captured at run start and locked once running.

## Architecture

### Backend: streaming (`backend/app/benchmark.py`)

`BenchmarkRunner.run()` gains an optional `on_line: Callable[[str], Awaitable[None]] | None`.

- Spawn with `stdout=PIPE, stderr=STDOUT` (merged), read the stream
  line-by-line instead of `communicate()`, accumulating the full text as today.
- Each decoded line is passed to `await on_line(line)` when a callback is given.
- Timeout and abort handling preserved (kill process, return failed/aborted
  status).
- Side benefit: return the **full** output in the result dict; store it in the
  existing `results.output_snippet` column instead of truncating to 2000 chars.

### Backend: the continue gate (`backend/app/api.py`)

- `AppState` gains `self._continue_queue: asyncio.Queue | None`.
- `POST /benchmarks` reads `pause` (default `true`) from the body and passes it
  to `_run_job`.
- `_run_job(pause=...)`:
  - For each config, the runner's `on_line` callback broadcasts
    `{"type": "bench_log", run_id, index, kind, text}` where `kind` is
    `"line"` or `"progress"` (progress lines are TtyStream `\r` overwrites and
    replace the previous line in the UI).
  - After `config_done`, if `pause` is true and the config was not aborted:
    broadcast `{"type": "config_wait", run_id, index}`, then block until a
    continue token arrives on `_continue_queue`.
  - A watchdog auto-advances the gate after ~3s of **zero connected WebSocket
    clients** (grace period for reloads / closed tabs) so a paused run can
    never hang forever.
  - When `pause` is false the run proceeds straight through; `config_wait` is
    never emitted.
- New endpoint `POST /benchmarks/continue` (`{run_id}`): puts a token into
  `_continue_queue`; 409 if no pause is in progress. Mirrors the existing
  `/models/download/prune-answer` pattern.

### Frontend: state (`frontend/src/ws/useBenchmarkProgress.ts`, `src/api/client.ts`)

- `ProgressEvent` gains:
  - `bench_log` `{run_id, index, kind: "line" | "progress", text}`
  - `config_wait` `{run_id, index}`
- `ProgressState` gains `lines: string[]`, `currentCommand: string`,
  `waiting: boolean`.
- Reducer behavior:
  - `run_started` clears `lines` and `waiting`.
  - `config_start` appends a header line `▸ config i/N — $ {bench_command joined}`
    and sets `currentCommand`.
  - `bench_log` appends the line for `kind="line"` or replaces the last line for
    `kind="progress"`.
  - `config_done` appends a result line
    `PROMPT {pp} · DECODE {tg} · {status}`.
  - `config_wait` sets `waiting = true`.
  - `run_done` / `run_sync` clear `waiting`.
- `api/client.ts` adds `continueRun(runId)` → `POST /benchmarks/continue`.

### Frontend: UI (`RunPanel.tsx`, `App.tsx`)

- `RunPanel` renders an accumulating, auto-scrolling console below
  `MetricsBanks`, reusing the `.dl-console` styles.
- A **PAUSE** checkbox sits next to RUN BENCHMARK (default checked, disabled
  while a run is active).
- When `waiting` is true the panel shows a `PRESS ENTER TO CONTINUE` prompt;
  Enter (a keydown handler and a focused button) calls `onContinue`.
- `App.tsx`:
  - `pause` state (default `true`), included in the `startBenchmark` body.
  - `onContinue` calls `api.continueRun(progressState.runId)`.

## Data flow

```
user clicks RUN BENCHMARK
  → POST /benchmarks {repo_id, configs, pause}
  → backend spawns _run_job, broadcasts run_started
  → for each config:
       config_start (carries config.bench_command)
       bench_log * n  (live streamed lines)
       config_done    (result)
       config_wait    (only when pause on)
       [frontend: user presses Enter]
       → POST /benchmarks/continue → next config
  → run_done
```

## Edge cases

- **Reload while paused**: WS drops to zero clients → watchdog auto-advances
  after the grace period → the run continues; the reconnected page picks up the
  next `config_start`. No hang, no DB schema change needed.
- **Pause disabled**: no `config_wait`, straight-through run, still streams.
- **Aborted config**: skips the wait and breaks the loop as today.
- **No WS client ever**: a run started with pause on and no live tab would
  auto-advance after the grace period and complete normally.

## Tests

### Backend (pytest)

- `BenchmarkRunner.run(on_line=...)` streams lines in order and returns the full
  output; the `FakeProcess` helpers gain an async-iterable stdout.
- `_run_job` broadcasts `config_wait` and blocks when `pause` is true;
  `/benchmarks/continue` releases the gate; the watchdog auto-advances when no
  WS clients are connected; `pause=false` runs straight through.

### Frontend (vitest)

- Reducer: `bench_log` line/progress handling, `config_start` header append,
  `config_wait` → waiting, `run_started`/`run_done` clearing.
- `RunPanel`: console renders accumulated lines, wait prompt appears when
  `waiting`, Enter fires `onContinue`, PAUSE toggle disabled while running.
- `App`: continue flow calls `api.continueRun`.

### E2E (Playwright)

- The existing flow test stays green: the mock-server returns `completed`
  immediately and has no WebSocket, so the poll-based `run_sync` bypasses the
  pause. New streaming/pause behavior is covered by unit tests; the mock-server
  is not extended to speak WebSocket.
