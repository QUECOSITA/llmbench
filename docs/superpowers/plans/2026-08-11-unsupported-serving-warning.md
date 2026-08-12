# Unsupported-Serving-Command Warning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After ANALYZE (or LOAD), if a repo's README documents no llama.cpp serving command (llama-server / speed-bench / llama-cli / llama-bench), warn that its `.gguf` may not be loadable by LLMBENCH and gate the Download button behind an explicit "YES — DOWNLOAD ANYWAY" confirmation; also warn when a loaded model has a `no_fit` verdict.

**Architecture:** Backend adds a `readme_has_serving_command` boolean to the `/models/analyze` response, computed from a new README-command-token matcher. The frontend drives one shared `analysis`-state block in the MODEL INPUT section that covers both ANALYZE and LOAD (LOAD reuses `onAnalyze`, App.tsx:199-205). `detect_serving_programs`/sync detection is left unchanged (non-destructive).

**Tech Stack:** FastAPI, pytest, React/TS, Vitest, Playwright.

---

### Task 1: Add `has_serving_command` helper to readme_parser

**Files:**
- Modify: `backend/app/readme_parser.py:3-9`
- Test: `backend/tests/test_readme_parser.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_readme_parser.py`:

```python
from app.readme_parser import detect_serving_programs, extract_flags, has_serving_command, top_serving_program


def test_has_serving_command_matches_command_tokens():
    assert has_serving_command("Run: llama-server -m x.gguf", "llama.cpp")
    assert has_serving_command("benchmark with speed-bench", "llama.cpp")
    assert has_serving_command("llama-cli -m x", "llama.cpp")
    assert has_serving_command("llama-bench -m x", "llama.cpp")


def test_has_serving_command_ignores_bare_project_mention():
    assert not has_serving_command("we recommend llama.cpp for inference", "llama.cpp")


def test_has_serving_command_false_when_absent():
    assert not has_serving_command("pip install transformers", "llama.cpp")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_readme_parser.py -v`
Expected: FAIL with `ImportError: cannot import name 'has_serving_command'`

- [ ] **Step 3: Write the minimal implementation**

Modify `backend/app/readme_parser.py`:

```python
_COMMAND_PATTERNS = {
    "llama.cpp": [
        r"\bllama-server\b", r"\bllama-cli\b", r"\bllama-bench\b",
        r"\bspeed-bench\b", r"\bllama\.cpp\b",
    ],
}

_SERVING_COMMAND_PATTERNS = {
    "llama.cpp": [
        r"\bllama-server\b", r"\bllama-cli\b", r"\bllama-bench\b", r"\bspeed-bench\b",
    ],
}


def has_serving_command(readme: str, server: str) -> bool:
    """True when the README names a runnable llama.cpp serving/bench command.
    A bare 'llama.cpp' project mention does not count as a serving command."""
    patterns = _SERVING_COMMAND_PATTERNS.get(server, ())
    return any(re.search(p, readme, re.IGNORECASE) for p in patterns)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_readme_parser.py -v`
Expected: PASS (all 8 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/readme_parser.py backend/tests/test_readme_parser.py
git commit -m "feat: detect llama.cpp serving commands in READMEs"
```

---

### Task 2: Expose `readme_has_serving_command` in the analyze endpoint

**Files:**
- Modify: `backend/app/api.py:23,209-227`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api.py` (after `test_analyze_llama_readme_returns_per_server_flags`):

```python
def test_analyze_readme_has_serving_command_true(client, httpx_mock):
    httpx_mock.add_response(
        url="https://huggingface.co/api/models/org/model/tree/main",
        json=[{"path": "README.md", "type": "file", "size": 100}],
    )
    httpx_mock.add_response(url="https://huggingface.co/org/model/raw/main/README.md",
                            text="# M\n\n```\nllama-server -m model.gguf --ctx-size 8192\n```")
    r = client.post("/api/models/analyze", json={"input": "org/model"})
    assert r.status_code == 200
    body = r.json()
    assert body["readme_has_serving_command"] is True


def test_analyze_readme_without_serving_command_flag_false(client, httpx_mock):
    """gguf boost still detects llama.cpp, but README has no serving command."""
    httpx_mock.add_response(
        url="https://huggingface.co/api/models/org/model/tree/main",
        json=[{"path": "README.md", "type": "file", "size": 100},
              {"path": "model.gguf", "type": "file", "size": 4_000_000_000}],
    )
    httpx_mock.add_response(url="https://huggingface.co/org/model/raw/main/README.md",
                            text="# M\n\nUse the GGUF below.\n")
    r = client.post("/api/models/analyze", json={"input": "org/model"})
    assert r.status_code == 200
    body = r.json()
    assert body["detected_server"] == "llama.cpp"
    assert body["readme_has_serving_command"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api.py -k serving_command -v`
Expected: FAIL with `KeyError: 'readme_has_serving_command'`

- [ ] **Step 3: Write the minimal implementation**

Modify `backend/app/api.py:23` import:

```python
from app.readme_parser import (detect_serving_programs, extract_flags,
                               has_serving_command, top_serving_program)
```

Modify the analyze response dict (currently `backend/app/api.py:222-238`) to add the field after `"server_scores"`:

```python
    return {
        "repo_id": repo_id,
        "detected_server": detected,
        "server_scores": scores,
        "readme_has_serving_command": has_serving_command(readme, "llama.cpp"),
        "readme_flags": flags,
        ...
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: report readme_has_serving_command from analyze"
```

---

### Task 3: Add `readme_has_serving_command` to the Analysis type

**Files:**
- Modify: `frontend/src/api/client.ts:53-64`

- [ ] **Step 1: Modify the interface**

```ts
export interface Analysis {
  repo_id?: string;
  detected_server?: string | null;
  readme_has_serving_command?: boolean;
  readme_flags?: Record<string, string>;
  ...
}
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && npx tsc -b`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat: type readme_has_serving_command on Analysis"
```

---

### Task 4: Warning + download confirmation in App.tsx

**Files:**
- Modify: `frontend/src/App.tsx:99-197` (state + onAnalyze), `frontend/src/App.tsx:411-445` (JSX)

- [ ] **Step 1: Add state and computed flags**

In `App()` (after line 116 `const [downloadKey, setDownloadKey] = useState<string | null>(null);`):

```tsx
const [confirmUnsupportedDownload, setConfirmUnsupportedDownload] = useState(false);
```

In `onAnalyze` (currently `frontend/src/App.tsx:190-197`) add the reset:

```tsx
const onAnalyze = useCallback(async (input: string) => {
  const data = await api.analyze(input);
  setAnalysis(data);
  setServer(data.detected_server ?? "");
  setConfigs([]);
  setDownloads({});
  setDownloadKey(null);
  setConfirmUnsupportedDownload(false);
}, []);
```

Before the `return (` of `App()` (after line 367, `}, [events]);`) add computed values:

```tsx
const hasServingCommand = analysis?.readme_has_serving_command ?? true;
const hasGguf = (analysis?.gguf_files?.length ?? 0) > 0;
const noFit = analysis?.fit_verdict?.stage === "no_fit";
const alreadyDownloaded = Boolean(analysis?.downloaded?.["llama.cpp"]);
```

- [ ] **Step 2: Replace the download section JSX**

Replace the block at `frontend/src/App.tsx:411-445` (from `{analysis?.repo_id && !analysis.detected_server && (` through the closing of the download row) with:

```tsx
{analysis?.repo_id && !analysis.detected_server && (
  <p style={{ color: "var(--accent)", fontSize: 12, margin: "4px 0 0" }}>
    no serving server proposed by this repo's README — model not supported by llama.cpp
  </p>
)}
{analysis?.fit_verdict && (
  <FitStatusLine verdict={analysis.fit_verdict} hardware={analysis.hardware} />
)}
{analysis?.repo_id && analysis.detected_server && (
  <>
    {(!hasServingCommand && hasGguf) || noFit ? (
      <div className="row" style={{ gap: 12, marginTop: 4, flexWrap: "wrap", alignItems: "center" }}>
        <p style={{ color: "var(--accent)", fontSize: 12, margin: 0 }}>
          {!hasServingCommand
            ? "this repo's README doesn't document a llama.cpp serving command (llama-server / speed-bench / llama-cli) — even though it ships a .gguf, it may not be loadable by LLMBENCH."
            : "this model doesn't fit this machine's VRAM/RAM — it may not be loadable by LLMBENCH."}
        </p>
        {!hasServingCommand && !alreadyDownloaded && !confirmUnsupportedDownload && (
          <>
            <button onClick={() => setConfirmUnsupportedDownload(true)}>YES — DOWNLOAD ANYWAY</button>
            <button onClick={() => setConfirmUnsupportedDownload(false)}>NO</button>
          </>
        )}
      </div>
    ) : null}
    {(hasServingCommand || confirmUnsupportedDownload || alreadyDownloaded) && (
      <div className="row" style={{ gap: 12, marginTop: 8, flexWrap: "wrap" }}>
        {[analysis.detected_server].map((sid) => {
          const k = `${sid}::${analysis.repo_id}`;
          const dl = downloads[k];
          const already = analysis.downloaded?.[sid];
          const busy = dl && (dl.status === "downloading" || dl.status === "cancelled" || dl.status === "pruning");
          const done = dl?.status === "downloaded" || already;
          return (
            <span key={sid} style={{ fontSize: 12 }}>
              <b>{sid}:</b>{" "}
              {busy ? (
                <span style={{ color: "var(--anode)" }}>
                  {dl.status === "downloading" ? "downloading" : "cancelled"}
                </span>
              ) : dl?.status === "error" ? (
                <span style={{ color: "var(--accent)" }}>error: {dl.message}</span>
              ) : done ? (
                <span style={{ color: "var(--anode)" }}>downloaded</span>
              ) : (
                <button onClick={() => onDownload(sid)}>Download</button>
              )}
            </span>
          );
        })}
      </div>
    )}
  </>
)}
```

- [ ] **Step 3: Verify existing frontend tests still pass**

Run: `cd frontend && npx vitest run`
Expected: PASS (existing mocks default `hasServingCommand` to `true` via `?? true`, so the download flow tests at App.test.tsx:360,399,435,663 are unaffected)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: warn and confirm before downloading unsupported gguf"
```

---

### Task 5: Frontend tests for warning, confirm, decline, LOAD, NO FIT

**Files:**
- Modify: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/App.test.tsx`:

```tsx
test("no serving command in README shows warning and hides Download until YES", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: false,
    gguf_files: [{ path: "model.gguf", size: 4_000_000_000 }],
    readme_flags: {},
    downloaded: { "llama.cpp": false },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/may not be loadable by LLMBENCH/i);

  expect(screen.getByText(/YES — DOWNLOAD ANYWAY/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Download" })).not.toBeInTheDocument();
});

test("confirming unsupported download reveals the Download button", async () => {
  const { api } = await import("./api/client");
  const downloadModelSpy = vi.spyOn(api, "downloadModel").mockResolvedValue({ ok: true });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: false,
    gguf_files: [{ path: "model.gguf", size: 4_000_000_000 }],
    readme_flags: {},
    downloaded: { "llama.cpp": false },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/may not be loadable by LLMBENCH/i);

  fireEvent.click(screen.getByText(/YES — DOWNLOAD ANYWAY/i));
  fireEvent.click(screen.getByRole("button", { name: "Download" }));
  expect(downloadModelSpy).toHaveBeenCalledWith({ repo_id: "org/model", server_id: "llama.cpp" });
});

test("declining unsupported download keeps Download hidden", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.downloadModel).mockClear();
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: false,
    gguf_files: [{ path: "model.gguf", size: 4_000_000_000 }],
    readme_flags: {},
    downloaded: { "llama.cpp": false },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/may not be loadable by LLMBENCH/i);

  fireEvent.click(screen.getByRole("button", { name: "NO" }));
  expect(screen.queryByRole("button", { name: "Download" })).not.toBeInTheDocument();
  expect(api.downloadModel).not.toHaveBeenCalled();
});

test("LOAD of a downloaded model with no serving command warns without a download prompt", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.listModels).mockResolvedValue({
    models: [{ server_id: "llama.cpp", repo_id: "org/model", status: "downloaded" }],
  });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValue({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: false,
    gguf_files: [{ path: "model.gguf", size: 4_000_000_000 }],
    readme_flags: {},
    downloaded: { "llama.cpp": true },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  await screen.findByText("llama.cpp");
  fireEvent.click(screen.getByRole("button", { name: "LOAD" }));
  await screen.findByText(/may not be loadable by LLMBENCH/i);

  expect(screen.queryByText(/YES — DOWNLOAD ANYWAY/i)).not.toBeInTheDocument();
  expect(screen.getByText("downloaded")).toBeInTheDocument();
});

test("LOAD of a model that does not fit shows the NO FIT warning", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.listModels).mockResolvedValue({
    models: [{ server_id: "llama.cpp", repo_id: "org/model", status: "downloaded" }],
  });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValue({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: true,
    readme_flags: {},
    fit_verdict: { stage: "no_fit", warning: true, needed_gb: 40.5 },
    hardware: { gpu_vram_gb: 8, ram_total_gb: 32, gpu_name: "RTX 4090" },
    downloaded: { "llama.cpp": true },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  await screen.findByText("llama.cpp");
  fireEvent.click(screen.getByRole("button", { name: "LOAD" }));
  await screen.findByText(/doesn't fit this machine/i);
});
```

- [ ] **Step 2: Run tests to verify the new ones pass**

Run: `cd frontend && npx vitest run`
Expected: all PASS (new + existing)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.test.tsx
git commit -m "test: cover unsupported-serving-command warning and confirm"
```

---

### Task 6: E2E mock-server and spec

**Files:**
- Modify: `frontend/e2e/mock-server.ts:27-35`
- Modify: `frontend/e2e/flow.spec.ts`

- [ ] **Step 1: Update mock-server analyze response**

Modify `frontend/e2e/mock-server.ts:27-35` so the analyze endpoint branches on the requested repo:

```ts
} else if (req.url?.startsWith("/api/models/analyze")) {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk);
  let repoId = "org/model";
  try {
    const parsed = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (parsed.input) repoId = String(parsed.input).split("/resolve/")[0];
  } catch {}
  const hasCommand = repoId !== "org/noserve";
  Object.assign(body, {
    repo_id: repoId,
    detected_server: "llama.cpp",
    readme_has_serving_command: hasCommand,
    readme_flags: { "--ctx-size": "8192" },
    weights_bytes: 4e9,
    gguf_files: [{ path: "model.gguf", size: 4_000_000_000 }],
    fit_verdict: { stage: "gpu", warning: false, needed_gb: 3.8 },
    model_arch: { layers: 32, heads: 32, hidden: 4096, max_ctx: 8192 },
    hardware: { gpu_vram_gb: 24, ram_total_gb: 64, gpu_name: "RTX 4090" },
    downloaded: { "llama.cpp": false },
  });
}
```

- [ ] **Step 2: Add an e2e spec**

Append to `frontend/e2e/flow.spec.ts`:

```ts
test("warns when README has no serving command and requires confirmation to download", async ({ page }) => {
  await page.goto("/");
  const input = page.getByPlaceholder(/model/i);
  await input.fill("org/noserve");
  await page.getByRole("button", { name: /analyze/i }).click();
  await page.getByText(/may not be loadable by LLMBENCH/i).waitFor();
  await page.getByText(/YES — DOWNLOAD ANYWAY/i).waitFor();
  await page.getByRole("button", { name: /YES — DOWNLOAD ANYWAY/i }).click();
  await page.getByRole("button", { name: "Download" }).waitFor();
});
```

- [ ] **Step 3: Run e2e**

Run: `cd frontend && npx playwright test`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/mock-server.ts frontend/e2e/flow.spec.ts
git commit -m "test(e2e): cover unsupported-serving-command warning flow"
```

---

### Task 7: Full local suite verification

- [ ] **Step 1: Run backend tests**

Run: `cd backend && python -m pytest`
Expected: PASS

- [ ] **Step 2: Run frontend typecheck and unit tests**

Run: `cd frontend && npx tsc -b && npx vitest run`
Expected: PASS

- [ ] **Step 3: Run e2e**

Run: `cd frontend && npx playwright test`
Expected: PASS

- [ ] **Step 4: Commit any stragglers**

```bash
git add -A && git commit -m "chore: final verification"
```

---

## Self-Review

- **Spec coverage:** All requirements mapped — warning on no serving command (Tasks 1-4), YES/NO download confirmation (Task 4-5), LOAD reuses the block (Task 4-5), NO FIT warning for LOAD (Task 4-5), tests (Tasks 1-6). ✓
- **Placeholders:** No TBD/TODO; every code step has full code. ✓
- **Type consistency:** `readme_has_serving_command` used identically in client.ts, App.tsx, mock-server.ts; `has_serving_command` signature stable across tasks. ✓
