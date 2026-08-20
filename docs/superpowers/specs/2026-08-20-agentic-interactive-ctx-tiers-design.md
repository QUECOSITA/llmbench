# Agentic bench: interactive branches, ctx tiers, heavy injection

Date: 2026-08-20

## Problem

The agentic bench tool currently runs an in-process plan→act agent harness
against a live `llama-server`, but:

1. The ACT-phase branching decision is made automatically by the model
   (`tool_choice: auto`). The user wants to be asked for each branch decision
   so the bench is a true human-in-the-loop agentic workload, not an auto test.
2. There are no predefined context-usage tiers; the user wants three
   (low / medium / heavy) that map to context-window sizes.
3. The injected/prompt context is grown only through tool results, which is a
   soft simulation. The user wants the prefill to be genuinely heavy: 2× the
   tier's context injected as filler plus heavy per-step thinking, so the bench
   measures real long-prefill + long-decode t/s.
4. `--max-tokens` is capped at 32768; the heavy tier needs 65728.
5. Failed configs are reported as a bare failure with no explanation; the user
   wants to know WHY (e.g. context overflow vs insufficient VRAM).

## Goals

- Ask the user for each Phase-2 ACT branch decision (propose → edit/accept).
- Add a ctx-tier selector (low ≤16k, medium ≤64k, heavy ≥128k) that drives the
  serving `--ctx-size`, injected-context size, thinking intensity, and
  `--max-tokens`.
- Inject 2× the tier's context as filler + heavy thinking per step.
- Raise the `--max-tokens` validation cap to 65728 (used by the heavy tier).
- Classify agentic failures into a human-readable reason (context overflow,
  insufficient VRAM, etc.) and surface it in the UI + DB.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Branch decision UX | Interactive modal per branch: backend proposes tool+args, user edits/accepts, run pauses until answered |
| Interactive vs auto | Always interactive (NO auto mode); user is informed up-front that agentic is human-in-the-loop |
| Branch wait | Wait indefinitely for the user (decision wait is exempt from the model-call budget); Cancel aborts |
| Tier defaults | Dropdown next to bench-tool, default **medium** |
| Tier boundaries | low ≤16k, medium ≤64k, heavy ≥128k |
| Injected context | 2× the tier's full ctx value (filler) + heavy thinking; overflow errors accepted |
| Failure handling | Record as failed but report WHY (context_overflow / oom_insufficient_vram / …) |

## Architecture

```
frontend (tier dropdown + decision modal)
   │  REST /configs/generate { bench_tool: agentic, agentic_tier }
   ▼
backend api.generate
   • resolve tier → set --ctx-size on each agentic config's serving command
   • append --tier to bench flags; carry tier in agentic_params
   ▼
api._run_job (per config)
   • build decide() callback → broadcasts agentic_decision, awaits user reply
   • AgenticRunner(decide=decide, params)
   ▼
AgenticRunner.run
   • spawn llama-server (ctx from tier), probe tool calling
   • run_agent_session(tier, fill_tokens=2*ctx, decide, session_timeout_s)
   • classify failures → failure_reason
   ▼
agentic.run_agent_session
   • inject filler + thinking into system prompt
   • Phase 1: forced submit_plan
   • Phase 2: model recommends; decide() asks the user; execute chosen tool
   • budget counts model-call wall time only (user wait is free)
   ▼
db.save_result(tier, user_decisions, failure_reason) → SQLite
```

## Component changes

### Backend

- **`servers.py`** — `AGENTIC_CLI_FLAGS += "--tier"`; cap 32768 → 65728;
  validate tiers; `agentic_default_flags` includes `--tier`.
- **`agentic.py`** — `AGENTIC_TIERS` (ctx/fill/max_tokens), `AGENTIC_THINKING`
  per tier, `_build_filler()`, `decide` callback in `run_agent_session`, and a
  `session_timeout_s` model-call budget that excludes user-wait.
- **`config.py`** — `agentic_tier` setting (default medium).
- **`api.py`** — tier resolution → `--ctx-size` override in `generate`;
  bidir WS: handle `agentic_decision_reply` and resolve a per-config future;
  build the `decide` callback in `_run_job`; pass tier + new fields to
  `save_result` and `config_done`.
- **`benchmark.py`** — `AgenticRunner(decide=...)`, pass tier/fill/decide, and a
  `_classify_agentic_failure()` helper (context_overflow, oom_insufficient_vram,
  no_disk_space, unknown).
- **`db.py`** — migration v3: `agentic_tier`, `user_decisions`,
  `failure_reason_key`, `failure_reason`; read them back in results.

### Frontend

- **`ConfigBank.tsx`** — tier dropdown (low/medium/heavy) shown when agentic.
- **`DecisionModal.tsx`** (new) — proposes tool+args, allows edit/accept,
  sends the reply; validates JSON args.
- **`useBenchmarkProgress.ts`** — handle `agentic_decision` events into
  `pendingDecision`; expose `sendDecision`; carry tier/failure/user_decisions.
- **`App.tsx`** — `agenticTier` state; pass `agentic_tier` to generate; render
  DecisionModal; pre-run interactive notice.
- **`client.ts`** — new types (tier, failure_reason, etc.).
- **i18n** — `config.agenticTier`, `agentic.interactiveNotice`,
  `decision.*` keys in all 15 locales.

### Docs
- README agentic paragraphs updated; design doc (this file) + plan.

## Non-goals
- No task-success grading.
- No shell/host FS access for the agent.
- No parallel tool-call execution.
