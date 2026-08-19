# Always-Available Bench-Tool Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the CONFIG BANK bench-tool selector (llama-bench / speed-bench / agentic) always visible for every model and always send `bench_tool` to `/configs/generate`, while keeping README-driven serving-command generation unchanged.

**Architecture:** Frontend-only change. `ConfigBank.tsx` loses its `showBenchToolSelector` prop and renders the selector unconditionally. `App.tsx` drops the `readme_has_serving_command === false` guards at `onGenerate` and at the `<ConfigBank>` call. The backend already accepts and honors `bench_tool` for any model (`api.py:524-535`), so no backend changes.

**Tech Stack:** React 18, TypeScript, Vitest + Testing Library, Playwright. Test commands run from `frontend/` (`npm test`, `npx tsc -b`, `npm run e2e`). e2e uses Playwright `webServer` to auto-start vite (5173) + mock-server (8000).

**Spec:** `docs/superpowers/specs/2026-08-19-bench-tool-selector-always-available-design.md`

---

### Task 1: ConfigBank.tsx — render the bench-tool selector unconditionally

**Files:**
- Modify: `frontend/src/components/ConfigBank.tsx:48-53,68-81`
- Test: `frontend/src/components/ConfigBank.test.tsx`

- [ ] **Step 1: Update the tests to expect an always-visible selector**

Edit `frontend/src/components/ConfigBank.test.tsx`:

1. Delete the test `"hides the bench tool selector when showBenchToolSelector is false"` (currently lines 169-172).
2. In the tests at lines 83-97, 154-167, 174-189, and 191-205, remove the `showBenchToolSelector` line from every `<ConfigBank ...>` render (lines 90, 161, 182, 199).
3. Rename the test at line 154 from `"renders the bench tool selector when showBenchToolSelector is true"` to `"renders the bench tool selector even without showBenchToolSelector"` so it documents the always-on behavior:

```tsx
test("renders the bench tool selector even without showBenchToolSelector", () => {
  render(
    <ConfigBank
      n={1}
      onNChange={() => {}}
      onGenerate={() => {}}
      configs={[]}
      benchTool="llama-bench"
      onBenchToolChange={() => {}}
    />,
  );
  expect(screen.getByLabelText(/bench tool/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- src/components/ConfigBank.test.tsx`
Expected: FAIL — the renamed test at Step 1 renders `<ConfigBank>` without `showBenchToolSelector`, so the selector is still gated behind `{showBenchToolSelector && ...}` and `getByLabelText(/bench tool/i)` throws "Unable to find an accessible element with the role 'combobox'".

- [ ] **Step 3: Implement the always-on selector in ConfigBank.tsx**

In `frontend/src/components/ConfigBank.tsx`:

1. Remove `showBenchToolSelector?: boolean;` from the `Props` interface (line 50).
2. Remove `showBenchToolSelector` from the destructured props in the component signature (line 53).
3. Replace the gated selector block (lines 68-81) with the ungated version:

```tsx
        <label style={{ color: "var(--anode)", fontSize: 12 }}>
          {t("config.benchTool")}
          <select
            value={benchTool ?? "llama-bench"}
            onChange={(e) => onBenchToolChange?.(e.target.value as "llama-bench" | "speed-bench" | "agentic")}
            disabled={!canGenerate}
          >
            <option value="llama-bench">llama-bench</option>
            <option value="speed-bench">speed-bench</option>
            <option value="agentic">agentic</option>
          </select>
        </label>
```

The result is that the selector renders unconditionally inside `<div className="row">`, between the N input and the GENERATE button.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- src/components/ConfigBank.test.tsx`
Expected: PASS (all 15 tests).

- [ ] **Step 5: Typecheck**

Run: `npx tsc -b`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ConfigBank.tsx frontend/src/components/ConfigBank.test.tsx
git commit -m "feat: render bench tool selector unconditionally in config bank"
```

---

### Task 2: App.tsx — always send `bench_tool` and drop the selector gating

**Files:**
- Modify: `frontend/src/App.tsx:266,630`
- Test: `frontend/src/App.test.tsx:661-686`

- [ ] **Step 1: Write the failing test**

Replace the test `"no bench tool selector and no bench_tool in generate payload when README proposes a serving config"` (currently lines 661-686) with:

```tsx
test("shows the bench tool selector and passes bench_tool even when README proposes a serving config", async () => {
  const { api } = await import("./api/client");
  const generateSpy = vi.spyOn(api, "generateConfigs").mockResolvedValue({
    configs: [{ flags: {}, serving_command: "llama-server --hf-repo org/model --hf-file model.gguf --load-mode none --no-mmproj", bench_command: [], bench_tool: "llama-bench", fit: null }],
  });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: true,
    readme_flags: {},
    auto_bench_tool: "llama-bench",
    downloaded: { "llama.cpp": true },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  const select = screen.getByLabelText(/bench tool/i) as HTMLSelectElement;
  expect(select.value).toBe("llama-bench");

  fireEvent.change(select, { target: { value: "speed-bench" } });
  fireEvent.click(screen.getByText(/generate/i));
  await waitFor(() => expect(generateSpy).toHaveBeenCalled());
  const body = generateSpy.mock.calls[0][0] as { bench_tool?: string };
  expect(body.bench_tool).toBe("speed-bench");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- src/App.test.tsx -t "shows the bench tool selector and passes bench_tool even when README proposes a serving config"`
Expected: FAIL — the selector is still hidden for `readme_has_serving_command: true` (no `combobox` labeled "bench tool"), so `screen.getByLabelText(/bench tool/i)` throws.

- [ ] **Step 3: Implement the App.tsx changes**

In `frontend/src/App.tsx`:

1. Line 266 — always send `bench_tool`. Replace:

```tsx
      bench_tool: analysis.readme_has_serving_command === false ? benchTool : undefined,
```

with:

```tsx
      bench_tool: benchTool,
```

2. Line 630 — remove the prop from the `<ConfigBank>` call. Delete the line `showBenchToolSelector={!hasServingCommand}`.

3. `hasServingCommand` (line 446) stays — it is still used at lines 513 and 534 for the unsupported-download warning flow. Do not remove it.

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- src/App.test.tsx -t "shows the bench tool selector and passes bench_tool even when README proposes a serving config"`
Expected: PASS.

- [ ] **Step 5: Run the full frontend unit suite**

Run: `npm test`
Expected: PASS (all tests, including the existing selector tests for `readme_has_serving_command: false` at lines 606-636 and 638-659, and the run-payload round-trip tests).

- [ ] **Step 6: Typecheck**

Run: `npx tsc -b`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat: always send bench_tool and show selector for README-serving-config models"
```

---

### Task 3: e2e — regression test that the selector is available for README-config models

**Files:**
- Modify: `frontend/e2e/flow.spec.ts`

- [ ] **Step 1: Add the e2e test**

Append to `frontend/e2e/flow.spec.ts` (after the existing `"agentic flow: ..."` test at line 57):

```ts
test("bench tool selector is available even when README proposes a serving config", async ({ page }) => {
  await page.goto("http://localhost:5173");
  await page.getByPlaceholder(/huggingface/i).fill("org/model");
  await page.getByRole("button", { name: /analyze/i }).click();
  await expect(page.getByText(/server llama.cpp/i)).toBeVisible();
  const selector = page.getByRole("combobox", { name: /bench tool/i });
  await expect(selector).toBeVisible();
  await selector.selectOption("agentic");
  await page.getByRole("button", { name: /generate/i }).click();
  await expect(page.getByText("AGENTIC", { exact: true })).toBeVisible();
});
```

`org/model` in `frontend/e2e/mock-server.ts` has `readme_has_serving_command: true` (line 52: `hasCommand = repoId !== "org/noserve"`) and is pre-downloaded (line 71), so GENERATE is enabled. The generate mock (lines 94-117) already returns an `agentic` config when `bench_tool` is sent.

- [ ] **Step 2: Run the e2e suite**

Run: `npm run e2e`
Expected: PASS (all tests, including the new one and the existing `agentic flow` test that uses `org/noserve`).

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/flow.spec.ts
git commit -m "test: e2e bench tool selector available for README-serving-config models"
```

---

### Task 4: Docs — update README feature line

**Files:**
- Modify: `README.md:106`

- [ ] **Step 1: Update the feature bullet**

In `README.md`, replace line 106:

```markdown
- **Manual bench-tool selection**: `llama-bench` (default), `speed-bench`, or `agentic` per run.
```

with:

```markdown
- **Manual bench-tool selection**: the bench tool (`llama-bench` default, `speed-bench`, or `agentic`) is always selectable in the CONFIG BANK, per run.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: note bench tool selector is always available"
```

---

### Task 5: Full local verification

**Files:** none (verification only)

- [ ] **Step 1: Backend suite (unchanged code must stay green)**

Run: `pytest`
Expected: PASS.

- [ ] **Step 2: Frontend typecheck + unit suite**

Run: `npx tsc -b && npm test`
Expected: PASS.

- [ ] **Step 3: Playwright e2e**

Run: `npm run e2e`
Expected: PASS.

- [ ] **Step 4: Review the diff**

Run: `git status` and `git diff main`
Expected: only `frontend/src/components/ConfigBank.tsx`, `frontend/src/components/ConfigBank.test.tsx`, `frontend/src/App.tsx`, `frontend/src/App.test.tsx`, `frontend/e2e/flow.spec.ts`, `README.md`, and the already-committed spec/plan docs. No backend files changed.

---

## Self-Review

**Spec coverage:**
- "Always visible / selector unconditional" → Task 1.
- "`bench_tool` always sent" → Task 2, Step 3.1.
- "Default `auto_bench_tool`, never `agentic`" → preserved; existing `onAnalyze` (`App.tsx:231`) is untouched.
- "Disabled until downloaded" → preserved; `disabled={!canGenerate}` stays in Task 1's new selector block.
- "Backend unchanged / serving command unchanged" → no backend files in any task; `build_serving_command` and `readme_flags` flow untouched.
- "ConfigBank.test.tsx updates" → Task 1, Step 1.
- "App.test.tsx rewrite" → Task 2, Step 1.
- "e2e" → Task 3.
- "README" → Task 4.
- "Full local verification" → Task 5.

**Placeholder scan:** no TBD/TODO; every step has concrete code or exact commands.

**Type consistency:** the `benchTool` type `"llama-bench" | "speed-bench" | "agentic"` is unchanged across `Props`, `App.tsx`, and the tests; the selector option values match. `showBenchToolSelector` is removed everywhere it was referenced (ConfigBank props, ConfigBank tests, App.tsx call) in Tasks 1-2.