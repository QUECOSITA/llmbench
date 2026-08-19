# Always-Available Bench-Tool Selector — Design

**Date:** 2026-08-19
**Status:** Approved by user

## Problem

The CONFIG BANK bench-tool selector (llama-bench / speed-bench / agentic) is
hidden when the model's README proposes a llama.cpp serving config
(`readme_has_serving_command === true`, `App.tsx:630` →
`showBenchToolSelector={!hasServingCommand}`). As a result there is no way to
choose `agentic` (or to manually pick `speed-bench` vs `llama-bench`) for such
models. The `agentic` bench tool therefore only works for models whose README
documents no serving config.

## Goal

The full bench-tool selector is **always available** in the CONFIG BANK for
any model. `bench_tool` is always sent to `/configs/generate`. The serving
command keeps its current README-driven generation — no regression.

## Decisions (confirmed with user)

- **Always visible:** the selector renders unconditionally in the CONFIG BANK
  N/GENERATE row. The `showBenchToolSelector` prop and its conditional are
  removed.
- **`bench_tool` always sent:** `onGenerate` sends `bench_tool: benchTool`
  regardless of `readme_has_serving_command`. The auto-detection default is
  preserved because the selector defaults to `auto_bench_tool`.
- **Default:** `auto_bench_tool` from `/models/analyze` on each analyze
  (already implemented in `onAnalyze`; `agentic` is never auto-selected).
- **Serving command unchanged:** for README-with-serving-config models the
  generated `serving_command` stays seeded from `readme_flags` (config-bank
  baseline). The selector only changes the bench tool, never the serving
  command.
- **Backend unchanged:** `generate` already validates `bench_tool` against
  `{"llama-bench", "speed-bench", "agentic"}` (`api.py:524-535`) and honors it
  for any model. No API/DB changes.
- **Enabled state:** the selector is disabled until the model is downloaded
  (`disabled={!canGenerate}`), mirroring GENERATE.

## Changes

### `frontend/src/components/ConfigBank.tsx`

- Remove the `showBenchToolSelector?: boolean` prop from `Props`.
- Remove the `{showBenchToolSelector && (...)}` wrapper (line 68); render the
  `<label>` + `<select>` block unconditionally inside the `<div className="row">`.

### `frontend/src/App.tsx`

- `onGenerate` (line 266): replace
  `bench_tool: analysis.readme_has_serving_command === false ? benchTool : undefined`
  with `bench_tool: benchTool`.
- Remove `showBenchToolSelector={!hasServingCommand}` (line 630) from the
  `<ConfigBank>` call.
- `hasServingCommand` (line 446): check remaining uses; remove the const if it
  becomes unused.

### `frontend/src/api/client.ts`

- No change. `bench_tool` is already optional in the `generateConfigs` body
  type and `Analysis.auto_bench_tool` already exists.

### i18n

- No new keys. `config.benchTool` exists in all 15 locales; option labels
  (`llama-bench`, `speed-bench`, `agentic`) are proper nouns.

### Tests

- `frontend/src/components/ConfigBank.test.tsx`:
  - Remove the "hides the bench tool selector when `showBenchToolSelector` is
    false" test.
  - Keep the render / disabled-when-`canGenerate`-false / change-fires-callback
    tests (render props stay the same minus the removed prop).
- `frontend/src/App.test.tsx`:
  - Rewrite the test at line 661 ("no bench tool selector and no `bench_tool`
    in generate payload when README proposes a serving config") to assert the
    selector **is** shown for `readme_has_serving_command: true` models and
    `bench_tool` **is** sent (defaults to `auto_bench_tool`; respects a manual
    change).
  - Other generate-payload tests (lines 606-636, 638-659) already assert the
    selector behavior for `readme_has_serving_command: false`; they stay green
    and now also cover the always-on path.
- e2e (`frontend/e2e/flow.spec.ts`): extend the agentic flow or add a small
  test that the selector is visible for `org/model` (which has
  `readme_has_serving_command: true` in the mock-server) and selectable.

### Docs

- `README.md` (line 106 area): note that the manual bench-tool selection
  (`llama-bench` / `speed-bench` / `agentic`) is always available in the CONFIG
  BANK.
- `docs/superpowers/specs/2026-08-15-manual-bench-tool-selection-design.md`:
  superseded by this spec for the selector-visibility rule.

## Testing

- Backend `pytest`: unchanged code — existing suite must stay green.
- Frontend `tsc -b` + `vitest run`.
- Playwright e2e (mock-server already exposes `readme_has_serving_command` per
  repo; `org/noserve` exercises the no-config path, `org/model` the config
  path).

## Edge Cases

- **Re-analyze** resets `benchTool` to `auto_bench_tool` — preserved by
  existing `onAnalyze`.
- **README-config model, default selection:** behaves identically to today —
  `auto_bench_tool` matches backend auto-detection (`is_spec_decoding_model`);
  configs seeded from `readme_flags`.
- **README-config model + `agentic`/`speed-bench`:** the same generated
  `serving_command` is used; only the bench tool changes.
- **Backend older / `auto_bench_tool` absent:** `onAnalyze` falls back to
  `llama-bench`, matching the backend default.