# Download Console WS Connect Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the DOWNLOAD console so that after clicking DOWNLOAD it shows the command header (`$ hf download ...`) and the real-time streaming text, by making the download WebSocket connect eagerly at mount (matching the benchmark console) instead of only after the download POST fires.

**Architecture:** The backend already streams all events correctly. The regression is purely frontend timing: `useDownloadProgress(downloadActiveNow)` opens its WebSocket only when `downloadActiveNow` becomes true, which happens at the same time `onDownload` fires the POST `/api/models/download`. The backend broadcasts `download_started` as soon as the job starts, racing the WS handshake — for fast/cached downloads every event is missed, so the console renders `$ ` with no command and no lines. The fix connects the download WS unconditionally at mount (like `useBenchmarkProgress`), so it never misses events. The `downloadReducer` already ignores events without `server_id`/`repo_id` (i.e. run events), so an always-on download WS is safe.

**Tech Stack:** Vite/React 18/TypeScript/vitest/@testing-library/react/Playwright (frontend only; backend unchanged).

---

## File Structure

**Frontend (modify):**
- `frontend/src/ws/useDownloadProgress.ts` — connect WS at mount unconditionally; drop the `active` gating.
- `frontend/src/App.tsx` — call `useDownloadProgress()` without the arg; remove now-unused `downloadActiveNow` and the `downloadActive` import.
- `frontend/src/ws/useDownloadProgress.test.ts` — update tests for always-connected behavior.
- `frontend/e2e/flow.spec.ts` — restore the command-header assertion the plan originally intended.
- `frontend/e2e/mock-server.ts` — (only if needed) no change required; the WS has no mock endpoint and the console still renders its CANCEL action from the optimistic state.

---

### Task 1: Connect the download WebSocket at mount

**Files:**
- Modify: `frontend/src/ws/useDownloadProgress.ts`
- Test: `frontend/src/ws/useDownloadProgress.test.ts`

- [ ] **Step 1: Write the failing test**

Replace the contents of `frontend/src/ws/useDownloadProgress.test.ts` with:

```ts
import { act, renderHook } from "@testing-library/react";
import { useDownloadProgress } from "./useDownloadProgress";
import type { DownloadEvent } from "./useDownloadProgress";

class FakeWS {
  static instances: FakeWS[] = [];
  onmessage: ((e: { data: string }) => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeWS.instances.push(this);
  }
  close() {
    this.closed = true;
  }
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

beforeEach(() => {
  FakeWS.instances = [];
});

test("useDownloadProgress connects on mount and collects events", () => {
  const orig = globalThis.WebSocket;
  (globalThis as { WebSocket: unknown }).WebSocket = FakeWS;
  try {
    const { result } = renderHook(() => useDownloadProgress());
    expect(FakeWS.instances).toHaveLength(1);
    const ws = FakeWS.instances[0];
    act(() => {
      ws.emit({ type: "download_log", server_id: "vllm", repo_id: "org/model", line: "Fetching" });
      ws.emit({ type: "download_done", server_id: "vllm", repo_id: "org/model", status: "downloaded" });
    });
    const events = result.current as DownloadEvent[];
    expect(events).toHaveLength(2);
    expect(events[0].type).toBe("download_log");
    expect(events[1].type).toBe("download_done");
  } finally {
    (globalThis as { WebSocket: unknown }).WebSocket = orig;
  }
});

test("useDownloadProgress stays connected across renders and closes only on unmount", () => {
  const orig = globalThis.WebSocket;
  (globalThis as { WebSocket: unknown }).WebSocket = FakeWS;
  try {
    const { rerender, unmount } = renderHook(() => useDownloadProgress());
    expect(FakeWS.instances).toHaveLength(1);
    const ws = FakeWS.instances[0];
    rerender();
    expect(FakeWS.instances).toHaveLength(1);
    expect(ws.closed).toBe(false);
    unmount();
    expect(ws.closed).toBe(true);
  } finally {
    (globalThis as { WebSocket: unknown }).WebSocket = orig;
  }
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/ws/useDownloadProgress.test.ts`
Expected: FAIL — `useDownloadProgress` still requires an `active` argument and only connects when it is true.

- [ ] **Step 3: Implement the fix**

Replace the body of `useDownloadProgress` in `frontend/src/ws/useDownloadProgress.ts`:

```ts
export function useDownloadProgress() {
  const [events, setEvents] = useState<DownloadEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8000/api/ws");
    wsRef.current = ws;
    ws.onmessage = (msg) => {
      setEvents((prev) => [...prev, JSON.parse(msg.data) as DownloadEvent]);
    };
    return () => ws.close();
  }, []);

  return events;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/ws/useDownloadProgress.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/ruben/test/llmbench && git add frontend/src/ws/useDownloadProgress.ts frontend/src/ws/useDownloadProgress.test.ts && git commit -m "fix: connect download WebSocket at mount so download_started is never missed"
```

---

### Task 2: Update App.tsx wiring

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Update the call site and remove unused code**

In `frontend/src/App.tsx`:

1. Remove `downloadActive` from the `./ws/downloadReducer` import block (lines 15-19) so it becomes:

```tsx
import {
  downloadReducer,
  DownloadState,
} from "./ws/downloadReducer";
```

2. Replace lines 118-119:

```tsx
  const downloadActiveNow = downloadActive(downloads);
  const downloadEvents = useDownloadProgress(downloadActiveNow);
```

with:

```tsx
  const downloadEvents = useDownloadProgress();
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc -b`
Expected: PASS (no unused `downloadActive` import, no `downloadActiveNow` reference).

- [ ] **Step 3: Run the frontend unit suite**

Run: `cd frontend && npm test`
Expected: PASS — `App.test.tsx` mocks `useDownloadProgress` entirely, so the signature change is invisible to it.

- [ ] **Step 4: Commit**

```bash
cd /home/ruben/test/llmbench && git add frontend/src/App.tsx && git commit -m "fix: wire always-on download progress hook into App"
```

---

### Task 3: Restore the e2e command-header assertion

**Files:**
- Modify: `frontend/e2e/flow.spec.ts`

- [ ] **Step 1: Add the assertion**

In `frontend/e2e/flow.spec.ts`, in the `"download console renders with a CANCEL action"` test, after clicking Download add an assertion that the command header renders. The mock server has no WebSocket, so the optimistic `downloads[k]` entry (command: "") still renders the console with a CANCEL button — the command header text assertion must therefore be tolerant. Update the test to:

```ts
test("download console renders with a CANCEL action", async ({ page }) => {
  await page.goto("http://localhost:5173");
  await page.getByPlaceholder(/huggingface/i).fill("org/model");
  await page.getByRole("button", { name: /analyze/i }).click();
  await expect(page.getByText(/server vLLM/i)).toBeVisible();

  await page.getByRole("button", { name: /^download$/i }).first().click();
  await expect(page.locator(".dl-console")).toBeVisible();
  await expect(page.getByRole("button", { name: /cancel/i })).toBeVisible();
  await page.getByRole("button", { name: /cancel/i }).click();
  await expect(page.getByRole("button", { name: /cancel/i })).toBeVisible();
});
```

Note: the `.dl-console` container assertion replaces the brittle command-text check because the mock server has no WS endpoint and therefore cannot deliver `download_started`. The real command-header + live-text behavior is covered by the live browser verification in Final Verification.

- [ ] **Step 2: Verify the e2e suite runs**

Run (after `./down.sh` so the e2e self-managed servers can bind ports):
`cd frontend && npx playwright test`
Expected: PASS (4 tests).

- [ ] **Step 3: Commit**

```bash
cd /home/ruben/test/llmbench && git add frontend/e2e/flow.spec.ts && git commit -m "test: assert download console container in e2e flow"
```

---

## Final Verification

- [ ] **Run the full backend suite**

Run: `cd backend && source .venv/bin/activate && python -m pytest -q`
Expected: PASS (unchanged backend; 242+ passed).

- [ ] **Run the full frontend suite + typecheck**

Run: `cd frontend && npx tsc -b && npm test`
Expected: PASS.

- [ ] **Run Playwright e2e**

Stop the dev servers with `./down.sh`, run `cd frontend && npx playwright test`, then restore with `./up.sh`.
Expected: PASS (4 tests).

- [ ] **Live browser smoke test**

Start the app (`./up.sh`), open http://localhost:5173, analyze `Qwen/Qwen2.5-0.5B-Instruct-GGUF`, click DOWNLOAD, and confirm:
- the console header shows `$ hf download --format human Qwen/Qwen2.5-0.5B-Instruct-GGUF --include *.gguf ...`;
- the console body streams real-time lines (`download_log`/`download_progress`) during the download;
- the row shows `downloaded` and the console shows the downloaded path on completion.
