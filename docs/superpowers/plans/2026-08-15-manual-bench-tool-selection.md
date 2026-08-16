# Manual Bench-Tool Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a model's README proposes no llama.cpp serving config (`readme_has_serving_command === false`) and the model is downloaded, let the user pick the bench tool (llama-bench / speed-bench) in the CONFIG BANK before generating configs, then run the normal workflow.

**Architecture:** The `generate` endpoint already decides `uses_speed_bench`; it gains an optional `bench_tool` payload override (validated to `llama-bench`|`speed-bench`). The `analyze` endpoint exposes the auto-detected default (`auto_bench_tool`). The frontend adds a `<select>` in the CONFIG BANK row next to N/GENERATE that is only visible when `readme_has_serving_command === false`, defaults to `auto_bench_tool`, is disabled until the model is downloaded, and passes `bench_tool` to `/configs/generate` only in that case. Run dispatch, `_rebuild_bench_command`, and speed-bench availability/error handling are unchanged.

**Tech Stack:** Python 3.11+ / FastAPI (backend), React 18 + TypeScript + Vitest + react-i18next (frontend), 15 locale JSON files.

**Spec:** `docs/superpowers/specs/2026-08-15-manual-bench-tool-selection-design.md`

---

## File Structure

- **Modify:** `backend/app/api.py` — `analyze` adds `auto_bench_tool`; `generate` accepts optional `bench_tool` override + validation.
- **Modify:** `backend/tests/test_api.py` — analyze auto_bench_tool tests; generate bench_tool override + 422 tests.
- **Modify:** `frontend/src/api/client.ts` — `Analysis.auto_bench_tool`, `generateConfigs` body `bench_tool`.
- **Modify:** `frontend/src/App.tsx` — `benchTool` state, reset on analyze, pass `bench_tool` in generate, new ConfigBank props.
- **Modify:** `frontend/src/components/ConfigBank.tsx` — bench-tool `<select>` in the N/GENERATE row.
- **Modify:** `frontend/src/components/ConfigBank.test.tsx` — selector render/disabled/change tests.
- **Modify:** `frontend/src/App.test.tsx` — selector visibility, generate payload, round-trip tests.
- **Modify:** `frontend/src/i18n/locales/*/translation.json` (15 files) — add `config.benchTool`.
- **Modify:** `frontend/e2e/mock-server.ts` — optionally add `auto_bench_tool` to the analyze mock (not required; `en` tests unaffected).

---

### Task 1: Backend — `analyze` exposes `auto_bench_tool`

**Files:**
- Modify: `backend/app/api.py:163-180`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py` (after `test_analyze_readme_has_serving_command_true`):

```python
def test_analyze_auto_bench_tool_speed_bench_for_mtp_repo(client, httpx_mock):
    httpx_mock.add_response(
        url="https://huggingface.co/api/models/org/Qwen3-MTP/tree/main",
        json=[{"path": "README.md", "type": "file", "size": 100},
              {"path": "model.Q4_K_M.gguf", "type": "file", "size": 4_000_000_000}],
    )
    httpx_mock.add_response(url="https://huggingface.co/org/Qwen3-MTP/raw/main/README.md",
                            text="# M\n")
    r = client.post("/api/models/analyze", json={"input": "org/Qwen3-MTP"})
    assert r.status_code == 200
    assert r.json()["auto_bench_tool"] == "speed-bench"


def test_analyze_auto_bench_tool_speed_bench_for_spec_readme(client, httpx_mock):
    httpx_mock.add_response(
        url="https://huggingface.co/api/models/org/model/tree/main",
        json=[{"path": "README.md", "type": "file", "size": 100},
              {"path": "model.Q4_K_M.gguf", "type": "file", "size": 4_000_000_000}],
    )
    httpx_mock.add_response(url="https://huggingface.co/org/model/raw/main/README.md",
                            text="# M\n\n```\nllama-server -m model.gguf --spec-type draft-mtp\n```\n")
    r = client.post("/api/models/analyze", json={"input": "org/model"})
    assert r.status_code == 200
    assert r.json()["auto_bench_tool"] == "speed-bench"


def test_analyze_auto_bench_tool_llama_bench_for_plain_model(client, httpx_mock):
    httpx_mock.add_response(
        url="https://huggingface.co/api/models/org/model/tree/main",
        json=[{"path": "README.md", "type": "file", "size": 100},
              {"path": "model.Q4_K_M.gguf", "type": "file", "size": 4_000_000_000}],
    )
    httpx_mock.add_response(url="https://huggingface.co/org/model/raw/main/README.md",
                            text="# M\n")
    r = client.post("/api/models/analyze", json={"input": "org/model"})
    assert r.status_code == 200
    assert r.json()["auto_bench_tool"] == "llama-bench"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -k auto_bench_tool -v`
Expected: FAIL with `KeyError: 'auto_bench_tool'`.

- [ ] **Step 3: Implement `auto_bench_tool` in `analyze`**

In `backend/app/api.py`, inside `analyze` before the `return` statement (line ~162), compute the default. `gguf` is `list[dict]` with `path` keys (see `backend/app/hf.py:105-106`); `flags` is the extracted readme flags for the detected server (line ~153). Add:

```python
    first_gguf_basename = os.path.basename(gguf[0]["path"]) if gguf else None
    auto_bench_tool = (
        "speed-bench"
        if is_spec_decoding_model(repo_id, first_gguf_basename, flags)
        else "llama-bench"
    )
```

Then add `"auto_bench_tool": auto_bench_tool,` to the returned dict (alongside `"readme_has_serving_command"`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -k auto_bench_tool -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: analyze exposes auto_bench_tool default"
```

---

### Task 2: Backend — `generate` accepts `bench_tool` override

**Files:**
- Modify: `backend/app/api.py:425-428`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py` (after `test_generate_configs_llama_non_spec_uses_llama_bench`):

```python
def test_generate_configs_manual_speed_bench_on_plain_model(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.speed_bench_deps_available", lambda: True)
    bin_dir = tmp_path / "llama" / "build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    script = tmp_path / "llama" / "tools" / "server" / "bench" / "speed-bench" / "speed_bench.py"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env python3\n")
    settings = Settings(data_dir=tmp_path / "data", gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf",
                        workload_file=tmp_path / "prompts.jsonl",
                        llama_cpp_bin_dir=bin_dir)
    (tmp_path / "prompts.jsonl").write_text("{\"prompt\": \"hi\"}\n")
    with TestClient(create_app(settings)) as c:
        r = c.post("/api/configs/generate", json={
            "server_id": "llama.cpp",
            "repo_id": "org/plain-model",
            "n": 1,
            "readme_flags": {},
            "bench_tool": "speed-bench",
        })
    assert r.status_code == 200
    cfg = r.json()["configs"][0]
    assert cfg["bench_tool"] == "speed-bench"
    assert cfg["bench_command"][0] == sys.executable


def test_generate_configs_manual_llama_bench_on_mtp_model(client):
    r = client.post("/api/configs/generate", json={
        "server_id": "llama.cpp",
        "repo_id": "org/Qwen3-MTP",
        "n": 1,
        "readme_flags": {"--spec-type": "draft-mtp"},
        "bench_tool": "llama-bench",
    })
    assert r.status_code == 200
    cfg = r.json()["configs"][0]
    assert cfg["bench_tool"] == "llama-bench"
    assert cfg["bench_command"][0] == "llama-bench"


def test_generate_configs_invalid_bench_tool_422(client):
    r = client.post("/api/configs/generate", json={
        "server_id": "llama.cpp",
        "repo_id": "org/model",
        "n": 1,
        "readme_flags": {},
        "bench_tool": "bogus",
    })
    assert r.status_code == 422


def test_generate_configs_absent_bench_tool_keeps_auto_detection(client):
    r = client.post("/api/configs/generate", json={
        "server_id": "llama.cpp",
        "repo_id": "org/plain-model",
        "n": 1,
        "readme_flags": {},
    })
    assert r.status_code == 200
    assert r.json()["configs"][0]["bench_tool"] == "llama-bench"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -k "manual_speed_bench or manual_llama_bench or invalid_bench_tool or absent_bench_tool" -v`
Expected: FAIL — `bench_tool` payload is ignored (manual_* and absent tests fail the bench_tool assertion; invalid test returns 200 not 422).

- [ ] **Step 3: Implement the `bench_tool` override**

In `backend/app/api.py`, replace lines 425-428 (`uses_speed_bench = ...`):

```python
    requested_bench_tool = payload.get("bench_tool")
    if requested_bench_tool not in (None, "llama-bench", "speed-bench"):
        raise HTTPException(422, "'bench_tool' must be 'llama-bench' or 'speed-bench'.")
    uses_speed_bench = (
        server_id == "llama.cpp"
        and (
            requested_bench_tool == "speed-bench"
            if requested_bench_tool is not None
            else is_spec_decoding_model(repo_id, gguf_filename, payload.get("readme_flags", {}))
        )
    )
```

The rest of the `generate` handler (speed-bench script/flags/error branch, llama-bench `else` branch, fit computation) is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -v`
Expected: PASS — new tests pass and existing generate/speed-bench tests stay green (no `bench_tool` in payload → auto-detection preserved).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: generate accepts explicit bench_tool override"
```

---

### Task 3: Frontend — API client types

**Files:**
- Modify: `frontend/src/api/client.ts:58-70` and `:139-148`

- [ ] **Step 1: Add `auto_bench_tool` to `Analysis`**

In `frontend/src/api/client.ts`, add to the `Analysis` interface (near `readme_has_serving_command`):

```ts
  auto_bench_tool?: string;
```

- [ ] **Step 2: Add `bench_tool` to `generateConfigs` body**

In `frontend/src/api/client.ts`, add to the `generateConfigs` body type (after `model_arch`):

```ts
    bench_tool?: string;
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc -b`
Expected: PASS (types only; no runtime effect).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat: api client types for auto_bench_tool and bench_tool"
```

---

### Task 4: Frontend — CONFIG BANK bench-tool selector

**Files:**
- Modify: `frontend/src/components/ConfigBank.tsx:39-66`
- Test: `frontend/src/components/ConfigBank.test.tsx`

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/components/ConfigBank.test.tsx`:

```tsx
test("renders the bench tool selector when showBenchToolSelector is true", () => {
  render(
    <ConfigBank
      n={1}
      onNChange={() => {}}
      onGenerate={() => {}}
      configs={[]}
      showBenchToolSelector
      benchTool="llama-bench"
      onBenchToolChange={() => {}}
    />,
  );
  expect(screen.getByLabelText(/bench tool/i)).toBeInTheDocument();
});

test("hides the bench tool selector when showBenchToolSelector is false", () => {
  render(<ConfigBank n={1} onNChange={() => {}} onGenerate={() => {}} configs={[]} />);
  expect(screen.queryByLabelText(/bench tool/i)).not.toBeInTheDocument();
});

test("fires onBenchToolChange on selection", () => {
  const onBenchToolChange = vi.fn();
  render(
    <ConfigBank
      n={1}
      onNChange={() => {}}
      onGenerate={() => {}}
      configs={[]}
      showBenchToolSelector
      benchTool="llama-bench"
      onBenchToolChange={onBenchToolChange}
    />,
  );
  fireEvent.change(screen.getByLabelText(/bench tool/i), { target: { value: "speed-bench" } });
  expect(onBenchToolChange).toHaveBeenCalledWith("speed-bench");
});

test("disables the bench tool selector when canGenerate is false", () => {
  render(
    <ConfigBank
      n={1}
      onNChange={() => {}}
      onGenerate={() => {}}
      configs={[]}
      canGenerate={false}
      showBenchToolSelector
      benchTool="llama-bench"
      onBenchToolChange={() => {}}
    />,
  );
  expect(screen.getByLabelText(/bench tool/i)).toBeDisabled();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/ConfigBank.test.tsx`
Expected: FAIL — `getByLabelText(/bench tool/i)` throws (no selector rendered).

- [ ] **Step 3: Implement the selector**

In `frontend/src/components/ConfigBank.tsx`, extend `Props`:

```ts
  benchTool?: "llama-bench" | "speed-bench";
  onBenchToolChange?: (tool: "llama-bench" | "speed-bench") => void;
  showBenchToolSelector?: boolean;
```

Destructure the new props in the component signature, and add the selector inside the existing `<div className="row">` (before the GENERATE button, after the N input):

```tsx
        {showBenchToolSelector && (
          <>
            <label style={{ color: "var(--anode)", fontSize: 12 }}>{t("config.benchTool")}</label>
            <select
              value={benchTool ?? "llama-bench"}
              onChange={(e) => onBenchToolChange?.(e.target.value as "llama-bench" | "speed-bench")}
              disabled={!canGenerate}
            >
              <option value="llama-bench">llama-bench</option>
              <option value="speed-bench">speed-bench</option>
            </select>
          </>
        )}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/ConfigBank.test.tsx`
Expected: PASS (4 new + existing all pass).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ConfigBank.tsx frontend/src/components/ConfigBank.test.tsx
git commit -m "feat: config bank bench tool selector"
```

---

### Task 5: Frontend — App wiring

**Files:**
- Modify: `frontend/src/App.tsx:102-105,194-203,213-232,522-535`
- Test: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/App.test.tsx`:

```tsx
test("shows the bench tool selector only when README proposes no serving config and passes bench_tool to generate", async () => {
  const { api } = await import("./api/client");
  const generateSpy = vi.spyOn(api, "generateConfigs").mockResolvedValue({
    configs: [{ flags: {}, serving_command: "llama-server --hf-repo org/model --hf-file model.gguf", bench_command: [], bench_tool: "llama-bench", fit: null }],
  });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: false,
    gguf_files: [{ path: "model.gguf", size: 4_000_000_000 }],
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

test("defaults the selector to auto_bench_tool=speed-bench from analyze", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/Qwen3-MTP",
    detected_server: "llama.cpp",
    readme_has_serving_command: false,
    gguf_files: [{ path: "model.gguf", size: 4_000_000_000 }],
    readme_flags: {},
    auto_bench_tool: "speed-bench",
    downloaded: { "llama.cpp": true },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/Qwen3-MTP" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/Qwen3-MTP/i);

  const select = screen.getByLabelText(/bench tool/i) as HTMLSelectElement;
  expect(select.value).toBe("speed-bench");
});

test("no bench tool selector and no bench_tool in generate payload when README proposes a serving config", async () => {
  const { api } = await import("./api/client");
  const generateSpy = vi.spyOn(api, "generateConfigs").mockResolvedValue({
    configs: [{ flags: {}, serving_command: "llama-server --hf-repo org/model --hf-file model.gguf", bench_command: [], bench_tool: "llama-bench", fit: null }],
  });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: true,
    readme_flags: {},
    downloaded: { "llama.cpp": true },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  expect(screen.queryByLabelText(/bench tool/i)).not.toBeInTheDocument();
  fireEvent.click(screen.getByText(/generate/i));
  await waitFor(() => expect(generateSpy).toHaveBeenCalled());
  const body = generateSpy.mock.calls[0][0] as { bench_tool?: string };
  expect(body.bench_tool).toBeUndefined();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: FAIL — `getByLabelText(/bench tool/i)` throws; `body.bench_tool` is `undefined`/missing.

- [ ] **Step 3: Implement the wiring**

In `frontend/src/App.tsx`:

1. Add state near the other state declarations (line ~105):

```ts
  const [benchTool, setBenchTool] = useState<"llama-bench" | "speed-bench">("llama-bench");
```

2. In `onAnalyze` (line ~196, after `setAnalysis(data)`):

```ts
    setBenchTool(data.auto_bench_tool === "speed-bench" ? "speed-bench" : "llama-bench");
```

3. In `onGenerate` (line ~220), add `bench_tool` to the `api.generateConfigs` body:

```ts
      bench_tool: analysis.readme_has_serving_command === false ? benchTool : undefined,
```

Add `benchTool` to the `onGenerate` `useCallback` dependency array (line ~232): `[analysis, hardware, server, benchTool]`.

4. In the `<ConfigBank>` render (line ~522), add the new props:

```tsx
                benchTool={benchTool}
                onBenchToolChange={setBenchTool}
                showBenchToolSelector={!hasServingCommand}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS — 3 new tests plus the existing "run payload round-trips bench_tool" test all pass.

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npx tsc -b`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat: wire bench tool selector through App state and generate"
```

---

### Task 6: Frontend — i18n key `config.benchTool` in all 15 locales

**Files:**
- Modify: `frontend/src/i18n/locales/en/translation.json:37-43`
- Modify: `frontend/src/i18n/locales/{zh,ja,de,fr,es,ko,ar,pt,it,nl,sv,no,da,fi}/translation.json` (same `config` block)

- [ ] **Step 1: Add the key to English**

In `frontend/src/i18n/locales/en/translation.json`, in the `config` block (after `"bankTitle"`):

```json
    "benchTool": "BENCH TOOL",
```

- [ ] **Step 2: Add the key to the other 14 locales**

Insert `"benchTool": "<translation>",` in the same position in each locale's `config` block. `fallbackLng: "en"` covers any omission, but keep the 15 files in parity. Suggested translations:

- zh: `"BENCH 工具"`, ja: `"BENCH ツール"`, de: `"BENCH-WERKZEUG"`, fr: `"OUTIL DE BENCH"`, es: `"HERRAMIENTA DE BENCH"`, ko: `"BENCH 도구"`, ar: `"أداة BENCH"`, pt: `"FERRAMENTA DE BENCH"`, it: `"STRUMENTO BENCH"`, nl: `"BENCH-GEREEDSCHAP"`, sv: `"BENCH-VERKTYG"`, no: `"BENCH-VERKTØY"`, da: `"BENCH-VÆRKTØJ"`, fi: `"BENCH-TYÖKALU"`.

- [ ] **Step 3: Verify**

Run: `cd frontend && npx vitest run src/i18n/i18n.test.tsx && npx tsc -b`
Expected: PASS (fallback test and typecheck).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/locales
git commit -m "feat: i18n key for bench tool selector in all locales"
```

---

### Task 7: Full local verification

**Files:** (no source changes)

- [ ] **Step 1: Run the backend suite**

Run: `cd backend && .venv/bin/python -m pytest -v`
Expected: PASS (all backend tests, including new analyze/generate tests).

- [ ] **Step 2: Run the frontend typecheck + unit tests**

Run: `cd frontend && npx tsc -b && npx vitest run`
Expected: PASS (ConfigBank, App, i18n, all other suites).

- [ ] **Step 3: Run Playwright e2e**

Run: `cd frontend && npx playwright test`
Expected: PASS. If `auto_bench_tool` is not in the mock-server analyze response, the e2e still works because `readme_has_serving_command` defaults to `true` in the mock for the downloaded `org/model` case (no selector shown). Optionally add `auto_bench_tool: "llama-bench"` to the analyze mock (`frontend/e2e/mock-server.ts:41-61`) for realism — no assertions depend on it.

- [ ] **Step 4: Review the diff**

Run: `git status` and `git diff --stat`
Expected: the 3 backend files and the frontend files listed in File Structure, with no stray files (ignore `backend/data/llmbench.db` if present — it is untracked and unrelated).

- [ ] **Step 5: Final commit if anything drifted**

If any file drifted after the verification runs, commit it:

```bash
git add -A -- frontend backend docs
git commit -m "chore: verification follow-ups"
```
