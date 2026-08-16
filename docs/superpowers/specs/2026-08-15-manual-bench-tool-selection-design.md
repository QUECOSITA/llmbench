# Manual Bench-Tool Selection — Design

**Date:** 2026-08-15
**Status:** Approved by user (via plan approval)

## Problem

When a model's README does **not** propose a llama.cpp serving configuration
(no `llama-server` / `speed-bench` / `llama-cli` usage, i.e.
`readme_has_serving_command === false`), the bench tool is currently chosen
automatically behind the scenes: `generate` sets `bench_tool` to `speed-bench`
only when the model is MTP/spec-decoding (`is_spec_decoding_model`), otherwise
`llama-bench`. The user has no control over this choice.

For a model already downloaded/loaded whose README documents no serving config,
the user wants to **select the bench tool themselves** (llama-bench or
speed-bench) and then continue the normal workflow (generate configs → run).

## Goal

In the CONFIG BANK, when `readme_has_serving_command === false` and the model is
downloaded, let the user pick the bench tool (llama-bench / speed-bench) before
generating configs. The generated configs then carry the chosen `bench_tool`
and the rest of the workflow (bench_command build, run dispatch) is unchanged.

## Decisions (confirmed with user)

- **Placement:** a selector next to the `N` input / GENERATE button in the
  CONFIG BANK.
- **Visibility:** shown **only** when the README proposes no llama.cpp serving
  config (`readme_has_serving_command === false`). When the README *does*
  propose a config, behavior is unchanged (auto-detection via
  `is_spec_decoding_model`).
- **Enabled state:** the selector is enabled once the model is downloaded
  (mirrors `canGenerate`; GENERATE is already disabled until download).
- **Default:** the auto-detected tool (`speed-bench` if the model is
  MTP/spec-decoding, else `llama-bench`).
- **Generated flags:** kept as-is — no change to the default
  `--spec-type draft-mtp` / `--spec-draft-n-max` flags even when speed-bench is
  manually selected for a non-MTP model. The user can edit the flags/command in
  the config bank as today. Speed-bench availability gating
  (`ensure_speed_bench_script`, `speed_bench_deps_available`, `bench_error`)
  still applies unchanged.
- **Scope:** backend + frontend only. Inherently cross-platform — no
  `up.sh`/`up.bat`/`up.ps1` changes.

## Approach

**Backend-driven `bench_tool` override.** The `generate` endpoint already
decides `uses_speed_bench`; it gains an optional `bench_tool` override in its
payload. The `analyze` endpoint exposes the auto-detected tool so the selector
can default to it. This keeps a single source of truth (backend) and reuses the
existing speed-bench building/error logic untouched.

Rejected alternatives:

- **Frontend post-generation `bench_tool` rewrite** — would duplicate backend
  speed-bench command building (`ensure_speed_bench_script`, deps check, flag
  parsing) in the frontend. Fragile. Rejected.
- **Per-config-row toggle** — changes the run payload shape (mixed tools per
  run) and does not match the requested single pre-generate selector next to
  N/GENERATE. Rejected.

## Changes

### Backend

**`backend/app/api.py`**

1. **`analyze`** (response at line ~163): add
   `"auto_bench_tool"`. Compute it with the existing
   `is_spec_decoding_model(repo_id, first_gguf_basename, flags)` where
   `first_gguf_basename = gguf[0]["path"]` when `gguf` is non-empty. Use the
   same `flags` already extracted for the detected server (line ~153):
   `"speed-bench" if is_spec_decoding_model(...) else "llama-bench"`.

2. **`generate`** (line ~425): read an optional `bench_tool` from the payload.
   Validate: if present and not in `{"llama-bench", "speed-bench"}` → raise
   `HTTPException(422, "'bench_tool' must be 'llama-bench' or 'speed-bench'.")`.
   Compute:

   ```python
   requested = payload.get("bench_tool")
   auto = is_spec_decoding_model(repo_id, gguf_filename, payload.get("readme_flags", {}))
   uses_speed_bench = server_id == "llama.cpp" and (auto if requested is None else requested == "speed-bench")
   ```

   The existing `if uses_speed_bench:` branch (speed-bench script/flags/error)
   and the `else` branch (llama-bench command) run unchanged.

### Frontend

**`frontend/src/api/client.ts`**

- `Analysis`: add `auto_bench_tool?: string;`
- `generateConfigs` body type: add `bench_tool?: string;`

**`frontend/src/App.tsx`**

- Add state `benchTool` (`useState<"llama-bench" | "speed-bench">("llama-bench")`).
- In `onAnalyze` (after `setAnalysis(data)`), reset:
  `setBenchTool(data.auto_bench_tool === "speed-bench" ? "speed-bench" : "llama-bench")`.
- In `onGenerate`, add `bench_tool: hasServingCommand ? undefined : benchTool`
  to the `api.generateConfigs` body. This guarantees README-with-config models
  keep auto-detection (no behavioral change).
- Pass to `<ConfigBank>`: `benchTool`, `onBenchToolChange={setBenchTool}`,
  `showBenchToolSelector={!hasServingCommand}`.

**`frontend/src/components/ConfigBank.tsx`**

- New props:
  ```ts
  benchTool?: "llama-bench" | "speed-bench";
  onBenchToolChange?: (tool: "llama-bench" | "speed-bench") => void;
  showBenchToolSelector?: boolean;
  ```
- In the `N`/GENERATE row (line ~55), when `showBenchToolSelector`, render a
  `<select>` with two options (`llama-bench`, `speed-bench`), value
  `benchTool`, `disabled={!canGenerate}`, label from new i18n key
  `config.benchTool`.

### i18n

- Add `config.benchTool` ("BENCH TOOL") to all 15 locales
  (`frontend/src/i18n/locales/*/translation.json`). `en` is the source;
  others follow the existing translation style. `fallbackLng: "en"` protects
  against a missed key. The option labels (`llama-bench`, `speed-bench`) are
  proper nouns and are not translated.

## Testing

- **Backend `backend/tests/test_api.py`**:
  - `analyze` returns `auto_bench_tool` `"speed-bench"` for an MTP model and
    `"llama-bench"` for a plain model.
  - `generate` with explicit `bench_tool: "speed-bench"` on a non-MTP model →
    configs carry `bench_tool: "speed-bench"` (speed-bench command with mocked
    script/deps).
  - `generate` with `bench_tool: "llama-bench"` on an MTP model → configs carry
    `bench_tool: "llama-bench"`.
  - `generate` with invalid `bench_tool` → 422.
  - `generate` without `bench_tool` → existing auto-detection unchanged
    (existing tests stay green).
- **Frontend `frontend/src/components/ConfigBank.test.tsx`**: selector renders
  when `showBenchToolSelector` is true, hidden otherwise; disabled when
  `canGenerate` is false; selecting fires `onBenchToolChange`.
- **Frontend `frontend/src/App.test.tsx`**: selector visible only when
  `readme_has_serving_command === false`; generate payload includes
  `bench_tool` only in that case; `bench_tool` round-trips through the run
  payload; selector resets on re-analyze.
- Full local suite: backend `pytest`, frontend `tsc -b` + `vitest run`,
  Playwright `e2e` (mock-server unchanged — the analyze mock can optionally
  gain `auto_bench_tool`).
