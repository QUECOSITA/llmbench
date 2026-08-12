# GENERATE Requires Downloaded Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the GENERATE button disabled after ANALYZE until the repo/model (or repo/model/file) is actually downloaded, instead of enabling it as soon as a serving server is detected/selected.

**Architecture:** The frontend already knows whether a model is on disk in two places: `analysis.downloaded` (from the analyze response, backend `_model_status`) and the live `downloads` map (`downloads[key]?.status === "downloaded"`, keyed `"${server}::${repo}"`, populated by WebSocket `download_done` events). The download row already uses the combined `done = dl?.status === "downloaded" || already` check (`App.tsx:457-459`). GENERATE's `canGenerate` currently only checks `Boolean(server || analysis?.detected_server)` (`App.tsx:494`). We compute a `modelDownloaded` boolean using the same combined sources and gate `canGenerate` on it. `canRun` needs no change because configs can only exist after a successful GENERATE.

**Tech Stack:** React/TS, Vitest, Playwright.

---

### Task 1: Compute `modelDownloaded` and gate GENERATE

**Files:**
- Modify: `frontend/src/App.tsx:377` (add computed value), `frontend/src/App.tsx:494` (canGenerate)
- Test: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/App.test.tsx` after the test at line 767 ("declining unsupported download keeps Download hidden"):

```tsx
test("GENERATE stays disabled until the model is downloaded, then enables after download", async () => {
  const { api } = await import("./api/client");
  const { useDownloadProgress } = await import("./ws/useDownloadProgress");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_flags: {},
    downloaded: { "llama.cpp": false },
  });

  const view = render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  expect(screen.getByText("GENERATE")).toBeDisabled();

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "download_done", server_id: "llama.cpp", repo_id: "org/model", status: "downloaded", local_path: "/x" },
  ]);
  view.rerender(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  await waitFor(() => expect(screen.getByText("GENERATE")).not.toBeDisabled());
});

test("GENERATE is enabled when the model is already downloaded at analyze time", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_flags: {},
    downloaded: { "llama.cpp": true },
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  expect(screen.getByText("GENERATE")).not.toBeDisabled();
});
```

Also update the existing test "only the README-detected server appears in the select and download row" (line 688). Change its GENERATE assertion from enabled to disabled, because its mock sets `downloaded: { "llama.cpp": false }`:

```tsx
  expect(screen.getByText("GENERATE")).toBeDisabled();
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd frontend && npx vitest run src/App.test.tsx -t "GENERATE"`

Expected: FAIL — "GENERATE stays disabled until the model is downloaded" fails because GENERATE is already enabled (not gated), and "GENERATE is enabled when the model is already downloaded" fails only if the default mock change in Task 2 affects it; primary failure is the "stays disabled" test. The "only the README-detected server" test also fails because GENERATE is now expected disabled but is enabled.

- [ ] **Step 3: Compute `modelDownloaded` in App.tsx**

Modify `frontend/src/App.tsx`, replacing the `alreadyDownloaded` line at 377 with:

```tsx
  const alreadyDownloaded = Boolean(analysis?.downloaded?.["llama.cpp"]);
  const effectiveServer = server || analysis?.detected_server;
  const downloadKeyForModel = effectiveServer && analysis?.repo_id ? `${effectiveServer}::${analysis.repo_id}` : null;
  const modelDownloaded = Boolean(
    effectiveServer &&
      (analysis?.downloaded?.[effectiveServer] || downloads[downloadKeyForModel ?? ""]?.status === "downloaded"),
  );
```

- [ ] **Step 4: Gate `canGenerate`**

Modify `frontend/src/App.tsx:494`:

```tsx
                canGenerate={modelDownloaded}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/App.test.tsx -t "GENERATE"`

Expected: PASS — all three GENERATE tests pass.

---

### Task 2: Fix the default analyze mock so existing flow tests still work

**Files:**
- Modify: `frontend/src/App.test.tsx:10`

The default `analyze` mock (line 10) returns no `downloaded` field, which would now make GENERATE disabled in every flow test that clicks GENERATE. Mark the model as already downloaded by default.

- [ ] **Step 1: Update the default mock**

Modify `frontend/src/App.test.tsx:10`:

```tsx
    analyze: vi.fn().mockResolvedValue({ repo_id: "org/model", detected_server: "llama.cpp", readme_flags: {}, downloaded: { "llama.cpp": true } }),
```

- [ ] **Step 2: Run the full frontend unit suite**

Run: `cd frontend && npx vitest run`

Expected: All tests pass. If a test specifically checks the Download button is present after the default mock, it now sees `downloaded` (no Download button) — check the download-flow tests at lines 360 and 435, which override `api.analyze` explicitly with `downloaded` unset; update them to set `downloaded: { "llama.cpp": false }` in their mockResolvedValue if they fail.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc -b`

Expected: No type errors.

---

### Task 3: Update e2e mock-server and flow spec

**Files:**
- Modify: `frontend/e2e/mock-server.ts:46`
- Modify: `frontend/e2e/flow.spec.ts:24`

The full-flow e2e test clicks GENERATE right after analyzing `org/model`. The mock-server's analyze response sets `downloaded: { "llama.cpp": false }`, which would now keep GENERATE disabled. The mock already seeds `org/model` as a downloaded model (`mock-server.ts:7`), so the analyze response should match that reality: `org/model` → downloaded true. But the download-console e2e test needs `org/model` to still show a Download button. Resolve by analyzing a different, not-yet-downloaded repo in the download-console test.

- [ ] **Step 1: Update mock-server analyze response**

Modify `frontend/e2e/mock-server.ts:46`:

```ts
      downloaded: { "llama.cpp": repoId === "org/model" },
```

- [ ] **Step 2: Update the download-console e2e test**

Modify `frontend/e2e/flow.spec.ts:20-21` (fill/analyze), changing `org/model` to `org/noserve` is wrong (that repo has no serving command). Use a neutral repo that has a serving command but is not downloaded, e.g. `org/dl`:

```ts
  await page.getByPlaceholder(/huggingface/i).fill("org/dl");
  await page.getByRole("button", { name: /analyze/i }).click();
  await expect(page.getByText(/server llama.cpp/i)).toBeVisible();
```

- [ ] **Step 3: Run the e2e suite**

Run: `cd /home/ruben/test/llmbench && ./down.sh` then `cd frontend && npx playwright test`

Expected: All 5 e2e tests pass (full flow analyzes `org/model` → GENERATE enabled; download console analyzes `org/dl` → Download button present).

---

### Task 4: Run the full local suite and commit

- [ ] **Step 1: Backend tests**

Run: `cd backend && .venv/bin/python -m pytest -q`

Expected: 256 passed (backend unchanged; `downloaded` field already existed).

- [ ] **Step 2: Full frontend + e2e**

Run: `cd frontend && npx vitest run && npx tsc -b` then `npx playwright test`

Expected: 94+ unit tests pass, no type errors, 5 e2e pass.

- [ ] **Step 3: Restart the app**

Run: `cd /home/ruben/test/llmbench && ./up.sh` (detached), verify `curl http://localhost:8000/` and `http://localhost:5173/` respond.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/e2e/mock-server.ts frontend/e2e/flow.spec.ts docs/superpowers/plans/2026-08-11-generate-requires-download.md
git commit -m "feat: disable GENERATE until the model is downloaded"
```
