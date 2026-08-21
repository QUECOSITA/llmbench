# Plan — Agentic bench: interactive branches, ctx tiers, heavy injection

Date: 2026-08-20
Spec: `docs/superpowers/specs/2026-08-20-agentic-interactive-ctx-tiers-design.md`

## Summary
Make the agentic bench a true human-in-the-loop agentic workload: ask the user
for each Phase-2 ACT branch decision (propose → edit/accept), add a ctx-tier
selector (low/medium/heavy), inject 2× the tier's context as filler plus heavy
thinking, raise the `--max-tokens` cap to 65728, and classify failures with a
human-readable reason.

## Tasks

1. **servers.py** — allow `--tier`; raise `--max-tokens` cap 32768 → 65728;
   validate tiers; `agentic_default_flags` includes `--tier medium`.
2. **agentic.py** — `AGENTIC_TIERS` + `AGENTIC_THINKING` + `_build_filler()`;
   `run_agent_session(..., tier, fill_tokens, decide, session_timeout_s)`:
   inject filler+thinking, Phase-1 forced `submit_plan`, Phase-2 asks `decide()`
   for the branch, model-call budget excludes user-wait.
3. **config.py** — `agentic_tier` setting (default medium).
4. **api.py** — resolve tier → override `--ctx-size` on agentic serving
   commands; carry `tier` in `agentic_params`; build the `decide` callback in
   `_run_job` (broadcast `agentic_decision`, await user reply); handle incoming
   `agentic_decision_reply` on the WS; persist tier/user_decisions/failure_reason;
   add `agentic_tier` to the `config_done` result.
5. **benchmark.py** — `AgenticRunner(decide=...)`, pass tier/fill/decide +
   `session_timeout_s`; `_classify_agentic_failure()` for overflow/OOM/etc.
6. **db.py** — migration v3: `agentic_tier`, `user_decisions`,
   `failure_reason_key`, `failure_reason`; read them back.
7. **Frontend** — `ConfigBank` tier dropdown; new `DecisionModal`
   (propose/edit/accept); `useBenchmarkProgress` handles `agentic_decision` →
   `pendingDecision` + `sendDecision`; `App` renders modal + pre-run notice +
   passes `agentic_tier`; `client.ts` types; i18n keys (all 15 locales).
8. **Tests** — backend: tier→ctx, cap 65728, decide path, filler, budget-exempt,
   failure classifier, DB migration. Frontend: tier dropdown, decision modal,
   reducer decision events. e2e: tier dropdown + interactive notice.
9. **Docs** — README agentic paragraphs + design doc.

## Verification
- Backend `pytest` — 373 passed.
- Frontend `tsc -b` clean; `vitest run` — 145 passed.
- Playwright e2e — 12 passed.

## Notes
- `backend/data/llmbench.db` is local user data and must NOT be committed.
- **2026-08-21 retune:** the "inject 2× tier context as filler" overshot —
  medium/heavy filler exceeded the context window, so runs failed before decode
  and heavy was unusable. Retuned (see
  `2026-08-21-retune-agentic-filler.md`): filler is now a one-time context
  message at 50% of the tier's ctx, and per-tier thinking is bounded to a fixed
  token target (~80/160/320). `--max-tokens` cap (65728) is unchanged.
