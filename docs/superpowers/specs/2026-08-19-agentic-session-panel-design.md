# Agentic Session Panel — Live Harness Output

Date: 2026-08-19

## Problem

The agentic bench harness (`backend/app/agentic.py::run_agent_session`) runs a real
plan→act agent loop (tools, planning, branching) but surfaces almost nothing to the
user. Its `transcript` only records sparse one-line tool calls (e.g.
`step 3: read_file({...}) -> ...`) and never captures the model's prompts, thinking /
output content, tool-choice decisions, loop iterations, or which branch (tool) the
model actually selected. The user wants to see **all the output a harness produces**.

## Goal

Add a live, structured **Agentic Session Panel** under the metrics in the RunPanel
that shows everything the harness does while an agentic config runs: prompts, model
thinking/output, tool execution, loop iterations, plan submissions/revisions, and the
branch (tool) the model actually picked each step. The panel is **live only** — it is
not persisted to the database.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Data source | Capture everything in the harness (enrich `run_agent_session`) |
| Panel placement | Under the metrics in `RunPanel` |
| Persistence | Live only — not persisted to DB (no migration) |
| Detail level | Full structured timeline (prompts, thinking, tools, loops, branch taken) |
| Rendering | New dedicated collapsible session panel + structured events |

## Architecture

```
run_agent_session (backend/app/agentic.py)
   └─ on_output("line", structured_block)  per step
         └─ WS bench_log ──▶ frontend ProgressState.lines
                              └─▶ AgenticSessionPanel (in RunPanel)
```

Reuses the existing `bench_log` WS channel (already streams plain-text `lines` live
into `ProgressState.lines` and the existing raw console). No DB migration is needed.

## Component design

### 1. Backend — `backend/app/agentic.py`

Extend `run_agent_session` so that on each step it emits a small structured block of
lines through the existing `on_output` callback (keep the existing `transcript` and
metrics/`agentic_tps` untouched). Each block includes:

- **Step header** — `── step 1/10 ──` (loop-iteration marker)
- **Prompt sent** — the `tool_choice` (forced `submit_plan` on step 1, `auto` after)
  plus the scenario task prompt text, noting the growing message history.
- **Model output / thinking** — the returned assistant `content` (or
  `(tool call only)` when the model emitted a tool call without prose).
- **Branch taken** — which tool the model selected from the offered set, e.g.
  `→ branch: read_file`.
- **Tool execution + result** — tool name + args + returned result (truncated).
- **Plan events** — `submit_plan` on step 1 is the initial plan; a later
  `submit_plan` is a plan revision.
- **Finish / budget** — `finish` or budget-exhausted at the end.

Implementation notes:
- Add a small formatting helper (e.g. `_emit_lines(on_output, lines)`) that joins the
  block and awaits `on_output("line", text)` per line, keeping `run_agent_session`
  readable.
- The existing per-step token/timing line (`step n/N: prompt ... tok + ... tok in
  ...s`) is kept and emitted as part of the block (or immediately after) so the live
  console still shows throughput per step.
- Content blobs (file contents / search results) are truncated to keep the WS payload
  bounded (already bounded to `[:4000]` in `_tool_result`; truncate emitted result
  lines to ~200–400 chars).

### 2. Frontend — new `AgenticSessionPanel.tsx`

- New component rendered inside `RunPanel` under `AgenticDetailStrip`.
- Consumes `lines: string[]` (already in `ProgressState`).
- Parses the structured step blocks into a **timeline** with distinct styling for:
  step headers, prompts, model thinking/output, tool calls, results, plan revisions,
  and branch selections.
- Collapsible (default open during a run), auto-scrolls to the bottom (reuse the
  existing scroll pattern from the `dl-console`).
- Component test (`AgenticSessionPanel.test.tsx`) asserts step structure + key labels
  render.

### 3. `RunPanel.tsx`

- Render `<AgenticSessionPanel lines={lines} />` under the `AgenticDetailStrip`.
- The existing raw `dl-console` remains for server logs.

## Testing & verification

- Backend: extend `backend/tests/test_agentic.py` to assert the emitted step/branch/
  tool/result/finish lines appear (captured via a fake `on_output`).
- Frontend: `AgenticSessionPanel.test.tsx`.
- Full suite: backend `pytest`, frontend `tsc -b` + `vitest run`, Playwright `e2e`.

## Non-goals

- No DB persistence (live only, per user decision).
- No change to metrics/headline `agentic_tps` or `AgenticDetailStrip`.
- No real external agent framework dependency.
- No task-success grading.
