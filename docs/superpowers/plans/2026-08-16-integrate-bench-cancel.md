# Integrate Manual Bench-Tool Selection + Cancel Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring all three features (startup requirements gate, manual bench-tool selection, cancel running benchmark) and their docs onto `main` via a single integration branch and one PR.

**Architecture:** Start from `main` (which already contains the startup requirements gate, feature 1). Merge `feature/manual-bench-tool-selection` (feature 2) resolving the single `frontend/src/App.tsx` conflict, then merge `feature/cancel-benchmark` (feature 3) which is expected to be clean. Verify the full local suite after each layer. Docs are committed on the integration branch first.

**Tech Stack:** git (merge strategy), Python/FastAPI + React/TypeScript/Vitest + Playwright (verification per AGENTS.md).

**Spec:** `docs/superpowers/specs/2026-08-16-integrate-bench-cancel-design.md`

---

## File Structure

- **Create:** `docs/superpowers/plans/2026-08-16-cancel-benchmark.md` — retroactive plan for the cancel feature.
- **Create:** `docs/superpowers/specs/2026-08-16-integrate-bench-cancel-design.md` — this integration's design.
- **Create:** `docs/superpowers/plans/2026-08-16-integrate-bench-cancel.md` — this plan.
- **Modify (via merge, no hand-editing):** `backend/app/api.py`, `backend/tests/test_api.py`, `frontend/src/App.tsx`, `frontend/src/api/client.ts`, `frontend/src/components/ConfigBank.tsx` + `.test.tsx`, `frontend/src/components/RunPanel.tsx` + `.test.tsx`, `frontend/src/App.test.tsx`, `frontend/src/i18n/status.ts`, all 15 `frontend/src/i18n/locales/*/translation.json`, `frontend/e2e/mock-server.ts`, `frontend/e2e/flow.spec.ts`, plus the two stranded docs `docs/superpowers/plans/2026-08-15-manual-bench-tool-selection.md` and `docs/superpowers/specs/2026-08-15-manual-bench-tool-selection-design.md`.

---

### Task 1: Commit the cancel work on its branch

- [ ] **Step 1: Verify branch and status**

On `feature/cancel-benchmark`, confirm the tip is `main` (`2fcbf61`) with the 25 cancel files modified and `backend/data/llmbench.db` untracked.

- [ ] **Step 2: Stage the 25 files (never the db)**

```bash
git add backend/app backend/tests frontend
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: cancel running benchmark run"
```

Expected: 25 files changed, 238 insertions(+), 8 deletions(-).

---

### Task 2: Create the integration branch

- [ ] **Step 1: Sync and branch from `main`**

```bash
git checkout main
git pull
git checkout -b feature/integrate-manual-bench-cancel
```

---

### Task 3: Docs first — commit the three docs on the integration branch

**Files:**
- Create: `docs/superpowers/plans/2026-08-16-cancel-benchmark.md`
- Create: `docs/superpowers/specs/2026-08-16-integrate-bench-cancel-design.md`
- Create: `docs/superpowers/plans/2026-08-16-integrate-bench-cancel.md`

- [ ] **Step 1: Write the three docs** (content per the approved plan; cancel plan documents the implemented feature retroactively).
- [ ] **Step 2: Commit**

```bash
git add docs/superpowers
git commit -m "docs: cancel benchmark plan; integration design and plan"
```

---

### Task 4: Merge feature 2 — manual bench-tool selection

- [ ] **Step 1: Run the merge**

```bash
git merge --no-ff feature/manual-bench-tool-selection -m "merge: manual bench tool selection (#29)"
```

Expected: conflict in `frontend/src/App.tsx` only.

- [ ] **Step 2: Resolve the App.tsx conflict**

The conflict is at the state-declaration block. Keep `n = useState(1)` (already present) and add the branch's `benchTool` line after it:

```ts
  const [n, setN] = useState(1);
  const [benchTool, setBenchTool] = useState<"llama-bench" | "speed-bench">("llama-bench");
  const [configs, setConfigs] = useState<ConfigRow[]>([]);
```

Remove all conflict markers. Verify no other file shows conflict markers (`grep -rn '<<<<<<<\|>>>>>>>' backend frontend`).

- [ ] **Step 3: Stage and complete the merge**

```bash
git add frontend/src/App.tsx
git commit -m "merge: manual bench tool selection (#29)"
```

- [ ] **Step 4: Verify after layer 2**

Run: `cd backend && .venv/bin/python -m pytest -v` and `cd frontend && npx tsc -b && npx vitest run`
Expected: PASS. Confirm `AGENTS.md` still contains the merge-authorization rule (`git show HEAD:AGENTS.md | grep -c 'literal word'` → 1).

---

### Task 5: Merge feature 3 — cancel benchmark

- [ ] **Step 1: Run the merge**

```bash
git merge --no-ff feature/cancel-benchmark -m "merge: cancel running benchmark (#31)"
```

Expected: clean, no conflicts. If the App.tsx ConfigBank/RunPanel adjacency conflicts, resolve by keeping both the ConfigBank props (benchTool) and the RunPanel prop (`onCancel={onCancelRun}`).

- [ ] **Step 2: Verify the full suite**

Run:
- `cd backend && .venv/bin/python -m pytest -v`
- `cd frontend && npx tsc -b && npx vitest run`
- `cd frontend && npx playwright test`

Expected: all PASS. Fix any issue that surfaces, then commit the fix.

- [ ] **Step 3: Commit if anything drifted**

```bash
git add -A -- frontend backend docs
git commit -m "chore: verification follow-ups"
```

---

### Task 6: Review and deliver

- [ ] **Step 1: Inspect**

Run `git status` and `git diff --stat main...HEAD`. Confirm: the three features' files, both stranded manual-bench docs, the three new docs, no `backend/data/llmbench.db`, no conflict markers.

- [ ] **Step 2: Push**

```bash
git push origin feature/integrate-manual-bench-cancel
```

- [ ] **Step 3: Open the PR**

Create a PR against `main` titled to cover all three features, referencing #28/#29 and the cancel work, with the test plan. **Do NOT merge** — wait for CI + security scans (~3 min), then present the merge for the user's explicit approval containing the literal word "merge".
