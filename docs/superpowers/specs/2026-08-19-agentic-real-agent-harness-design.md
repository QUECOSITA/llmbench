# Agentic Bench v2: Real plan→act agent harness

Date: 2026-08-19

## Problem

The current "agentic" bench tool (`backend/app/agentic.py`) is not an agent. It
drives a scripted multi-turn chat session: 4 fixed turns that grow the message
history, reporting `completion tokens / wall time`. It has no tools, no planning
loop, and no decision branching. The user wants the agentic bench to measure real
serving throughput under a lightweight agent harness — one that uses tools,
plans, and branches — so the user learns how a given `llama-server` config
performs under realistic agentic traffic.

## Goal

Replace the scripted multi-turn loop with an in-process **plan → act** agent
harness that runs against the served model's OpenAI-compatible API. The primary
output is serving throughput under agentic load (not task-success grading). The
headline metric is redefined to **total processing tokens ÷ wall time** (prompt +
completion), reflecting the repeated prefills that dominate agentic traffic.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Primary measure | Serving throughput under agentic load |
| Harness | In-house minimal harness (no new deps) |
| Agent structure | Explicit plan→act two-phase loop (approach C) |
| Tools | Safe load-generating tools (no shell, no host FS) |
| Metrics | Rich metric set (DB + UI) |
| Session termination | Max-steps cap + early `finish` |
| Tasks | Bundled deterministic scenarios |
| Tool-call support | Require it; fail the config clearly if absent |
| UI | Headline AGENTIC bank + compact detail strip |
| Headline metric | `agentic_tps` redefined to total tokens ÷ wall time |

## Architecture

```
frontend ──ws──▶ backend api._run_job
                     │  picks AgenticRunner (bench_tool == "agentic")
                     ▼
              AgenticRunner.run()        (benchmark.py)
                 • build server_cmd + --port/--host
                 • spawn llama-server, wait /health (startup_timeout)
                 • run_agent_session(...)        (agentic.py)
                 • kill server
                     │
                     ▼
              run_agent_session(): plan→act loop
                 • probe tool-calling support (fail clearly if absent)
                 • PHASE 1 PLAN: force tool_choice=submit_plan
                 • PHASE 2 ACT: tool_choice=auto, up to --steps calls
                 • tools: submit_plan / finish (control)
                         read_file / list_dir / search / calculate (workload)
                 • collect metrics + transcript
                     │
                     ▼
              save_result(..., agentic_* detail)  → SQLite (db.py)
```

## Component design

### 1. Agent harness — `backend/app/agentic.py` (rewrite)

**Tools** (OpenAI function-calling schema):

- **Control**
  - `submit_plan({steps: list[str]})` — the model writes a structured plan.
  - `finish({answer: str})` — ends the session early with a final answer.
- **Workload** (safe, deterministic, load-generating)
  - `read_file({path})` — returns file content from the scenario's synthetic
    corpus (large blobs to grow context).
  - `list_dir({path})` — returns a directory listing from the corpus.
  - `search({query})` — returns canned result blobs from the corpus.
  - `calculate({expression})` — safe arithmetic evaluation (no `eval` of
    arbitrary code; a small guarded evaluator).

**Phase 1 — PLAN (forced):** the first model call uses `tool_choice` pinned to
`submit_plan`, guaranteeing every run begins with a structured plan and that
runs are comparable across configs.

**Phase 2 — ACT (`tool_choice: auto`):** the model executes plan steps by
calling tools; results are appended as `tool` messages. It branches freely, may
call `submit_plan` again to **revise** its plan (the planning loop), and calls
`finish` to end. If it emits a plain assistant message with no tool call, the
harness nudges it back toward `submit_plan`/`finish` rather than ending.

**Budget:** `--steps` caps total model API calls (default 10); `--max-tokens`
caps each call's output (default 4096). The existing cancel path aborts the run.

**Tool-calling gate:** one probe call with a trivial tool before the session. If
it errors or returns no `tool_calls`, the config run fails clearly: *"served
model does not support function/tool calling; agentic bench requires it."*

**Bundled scenarios** (embedded dict, same text for every config):
- `codebase_refactor` — synthetic multi-file codebase; `read_file` injects real
  content.
- `data_pipeline` — files + `calculate`.
- `research` — `search` blobs.

### 2. Metrics, DB, flags

**Returned metrics:**
`agentic_tps` (headline, redefined), `steps`, `tool_calls`, `plan_revisions`,
`avg_latency_ms`, `p95_latency_ms`, `total_prompt_tokens`,
`total_completion_tokens`, `total_wall_s`, `finished` / `budget_exhausted`,
transcript.

**DB (`backend/app/db.py`):** add columns via a new migration
(`_migrate_results_agentic_v2`): `agentic_steps`, `agentic_tool_calls`,
`agentic_plan_revisions`, `agentic_avg_ms`, `agentic_p95_ms`,
`total_prompt_tokens`, `total_completion_tokens`. Update `save_result` (detail
param) and `get_results_for_run` (SELECT the new columns).

**Flags/config (`backend/app/servers.py`, `backend/app/config.py`):**
`AGENTIC_CLI_FLAGS` → `("--steps", "--max-tokens", "--task")`;
`Settings.agentic_turns` → `agentic_steps` (env `LLMBENCH_AGENTIC_STEPS`);
validation for ranges and known tasks; `agentic_params` carries
`{model, steps, max_tokens, task}`.

### 3. Frontend

- `MetricsBanks` unchanged (AGENTIC headline bank).
- New `AgenticDetailStrip` component: `10 steps · 14 tool calls · 2 plan revs ·
  avg 1.2s · p95 3.4s · ctx 96k`. Shown in `RunPanel` under the banks (live
  after each config) and as a muted second line under the AGENTIC digit in
  `ResultsTable` rows.
- Types gain the new fields in `client.ts`, `useBenchmarkProgress.ts`,
  `ResultsTable.tsx`. The `config_done` WS event already forwards the full
  result dict.
- i18n keys added to all 15 locale files.

### 4. Testing & docs

- Backend tests (`backend/tests/test_agentic.py` rewrite/additions): two-phase
  flow, plan revision, budget exhaustion, probe failure, tool outputs, flag
  parsing, DB migration.
- Frontend tests: `AgenticDetailStrip`, `ResultsTable` updates.
- e2e: `frontend/e2e/mock-server.ts` agentic flow returns rich fields; update
  `flow.spec.ts`.
- README: update agentic paragraphs (lines 116, 146) to describe the real
  harness + metrics.

## Non-goals

- No task-success grading (SWE-bench/GAIA style).
- No shell or host file-system access for the agent.
- No parallel tool-call execution.
- No real external agent framework dependency.
