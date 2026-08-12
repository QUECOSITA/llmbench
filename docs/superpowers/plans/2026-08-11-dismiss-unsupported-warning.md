# Dismiss Unsupported-Serving Warning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a repo's README has no llama.cpp serving command and the user clicks "NO" on the download-confirmation prompt, both the "YES — DOWNLOAD ANYWAY" and "NO" buttons disappear instead of staying visible.

**Architecture:** The warning buttons in `frontend/src/App.tsx:436-441` only render while `!confirmUnsupportedDownload`. Clicking "NO" currently calls `setConfirmUnsupportedDownload(false)` — a no-op because the state is already `false` — so both buttons remain. Add a new `dismissedUnsupported` boolean state; clicking "NO" sets it to `true`, and the button row renders only when it is not dismissed. The state resets in `onAnalyze` alongside `confirmUnsupportedDownload` so a fresh ANALYZE shows the prompt again.

**Tech Stack:** React/TS, Vitest.

---

### Task 1: Hide both buttons when "NO" is clicked

**Files:**
- Modify: `frontend/src/App.tsx:118` (state), `frontend/src/App.tsx:199` (reset), `frontend/src/App.tsx:436-441` (render + handlers)
- Test: `frontend/src/App.test.tsx:742-767`

- [ ] **Step 1: Write the failing test**

Extend the existing test "declining unsupported download keeps Download hidden" in `frontend/src/App.test.tsx`. After clicking "NO", assert the "YES — DOWNLOAD ANYWAY" button is also gone. Replace the assertion block in that test (currently lines 764-766) with:

```tsx
  fireEvent.click(screen.getByRole("button", { name: "NO" }));
  expect(screen.queryByRole("button", { name: /YES — DOWNLOAD ANYWAY/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "NO" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Download" })).not.toBeInTheDocument();
  expect(api.downloadModel).not.toHaveBeenCalled();
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/App.test.tsx -t "declining unsupported download"`

Expected: FAIL — `expect(...).not.toBeInTheDocument()` fails because both "YES — DOWNLOAD ANYWAY" and "NO" buttons are still in the document after clicking "NO".

- [ ] **Step 3: Add the `dismissedUnsupported` state**

In `frontend/src/App.tsx`, add a new state line directly after line 118:

```tsx
  const [dismissedUnsupported, setDismissedUnsupported] = useState(false);
```

- [ ] **Step 4: Reset the state in `onAnalyze`**

In `frontend/src/App.tsx`, inside `onAnalyze` (line ~199), add a reset line directly after the existing `setConfirmUnsupportedDownload(false);`:

```tsx
    setDismissedUnsupported(false);
```

- [ ] **Step 5: Gate the button row and wire "NO"**

In `frontend/src/App.tsx`, change the button row condition (line 436) from `!confirmUnsupportedDownload` to also require `!dismissedUnsupported`, and change the "NO" handler (line 439) to set `dismissedUnsupported`:

```tsx
                        {hasGguf && !alreadyDownloaded && !confirmUnsupportedDownload && !dismissedUnsupported && (
                          <>
                            <button onClick={() => setConfirmUnsupportedDownload(true)}>YES — DOWNLOAD ANYWAY</button>
                            <button onClick={() => setDismissedUnsupported(true)}>NO</button>
                          </>
                        )}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/App.test.tsx -t "declining unsupported download"`

Expected: PASS

- [ ] **Step 7: Run the full frontend unit suite and typecheck**

Run: `cd frontend && npx vitest run && npx tsc -b`

Expected: All tests pass, no type errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx docs/superpowers/plans/2026-08-11-dismiss-unsupported-warning.md
git commit -m "feat: dismiss YES/NO buttons when declining unsupported download"
```
