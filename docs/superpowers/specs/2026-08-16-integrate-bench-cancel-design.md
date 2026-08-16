# Integrate Manual Bench-Tool Selection + Cancel Benchmark — Design

**Date:** 2026-08-16
**Status:** Approved by user (via plan approval)

## Problem

Three independent features were built in sequence but never landed together on `main`:

1. **Startup requirements gate** (#28) — already merged to `main` (`8bcfcff`).
2. **Manual bench-tool selection** (#29) — fully implemented and tested on
   `feature/manual-bench-tool-selection` (7 commits: docs `0cd68a2` + 6 feature commits),
   but its PR was **stacked on `feature/startup-requirements-gate`** and never reached
   `main`. The docs for it (`2026-08-15-manual-bench-tool-selection-design.md` and
   `2026-08-15-manual-bench-tool-selection.md`) live only on that branch.
3. **Cancel running benchmark** — fully implemented and tested but **uncommitted** on
   `feature/cancel-benchmark` (tip = `main`), with no design/plan docs.

Result: `main` is missing two complete features and their documentation, and the stranded
squash `5ddd49b` on `origin/feature/startup-requirements-gate` makes the manual-bench
feature look "deleted".

## Goal

Deliver all three features to `main` in **one integration branch and one PR**, layered in
order of creation (startup gate → manual bench-tool selection → cancel benchmark), verifying
the full suite after each layer and preserving all docs. Nothing in the existing workflow or
functionality may break.

## Decisions (confirmed with user)

- **One integration branch + single PR** against `main`:
  `feature/integrate-manual-bench-cancel`.
- **Docs-first:** before any merge, commit on the integration branch:
  - `docs/superpowers/plans/2026-08-16-cancel-benchmark.md` (retroactive plan for cancel —
    it had none).
  - `docs/superpowers/specs/2026-08-16-integrate-bench-cancel-design.md` (this doc).
  - `docs/superpowers/plans/2026-08-16-integrate-bench-cancel.md` (this integration's plan).
  - The two stranded manual-bench docs arrive via the manual-bench merge.
- **Layer order (creation order):**
  1. Start from `main` (already contains feature 1).
  2. Merge `feature/manual-bench-tool-selection` → resolve the single `App.tsx` conflict.
  3. Merge `feature/cancel-benchmark` (after its work is committed) → expected clean.
- **Commit the cancel work on its branch first** (`37160bc`), never staging
  `backend/data/llmbench.db`.

## Conflict analysis (verified via `git merge-tree --write-tree`)

- **Layer 2 (manual-bench → main): exactly one conflict — `frontend/src/App.tsx`.**
  Both sides changed `const [n, setN] = useState(4)` → `useState(1)` (identical change,
  auto-resolves); the branch additionally inserts `benchTool` state after `n`. Resolution:
  take the branch's lines (`n = useState(1)` + `const [benchTool, setBenchTool] =
  useState<"llama-bench" | "speed-bench">("llama-bench");`). All other files
  (api.py, test_api.py, client.ts, ConfigBank.tsx + tests, App.test.tsx, i18n ×15, 2 docs)
  auto-merge. **`AGENTS.md` merge-authorization rule is preserved** (a main-only change from
  #30; 3-way merge keeps main's version).
- **Layer 3 (cancel → merged tree): expected clean.** Cancel's App.tsx hunks
  (255/287/379/550) and api.py hunks (81/556/583/635) are in different regions from
  manual-bench's hunks; ConfigBank props (manual-bench) and RunPanel props (cancel) are
  adjacent but non-overlapping; i18n keys (`config.benchTool` vs `common.cancelBenchmark`)
  are distinct blocks. Confirmed by executing the merge.

## Testing

Per AGENTS.md, the full local suite must pass before the PR is pushed:

- `cd backend && .venv/bin/python -m pytest` — backend.
- `cd frontend && npx tsc -b && npx vitest run` — frontend typecheck + unit.
- `cd frontend && npx playwright test` — e2e (self-managed via `webServer` + mock-server).

## Deliverable

A single PR against `main` covering all three features, with clean commit history:
docs commit → manual-bench merge (with conflict resolution) → cancel merge → verification
follow-ups. The merge is presented to the user for approval; per AGENTS.md it is **never
merged without an explicit instruction containing the literal word "merge"**.
