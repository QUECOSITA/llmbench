# Follow-ups (fit banner + HF CLI download) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the hardware-fit verdict in the analyze panel and replace the stubbed HF download with a real background `hf download` job streamed over WebSocket.

**Architecture:** Backend adds `fit_verdict`/`hardware` to `POST /api/models/analyze` and a new `POST /api/models/download` endpoint that runs `hf download` as an asyncio background task, streaming output lines as WS `download_log` events and upserting the model row on completion. Frontend renders the fit warning inline in the MODEL INPUT panel, adds per-server Download buttons under the analysis summary, and consumes download WS events via a new `useDownloadProgress` hook. Finally the feature branch is finished into `master`.

**Tech Stack:** Python/FastAPI/asyncio/sqlite3 (backend), Vite/React 18/TypeScript/vitest/@testing-library/react/Playwright (frontend). Tests: pytest + httpx-mock on backend; vitest + RTL on frontend.

**Spec:** `docs/superpowers/specs/2026-08-02-followups-design.md`

---

## File Structure

**Backend (modify):**
- `backend/app/api.py` — add `fit_verdict`+`hardware` to analyze; add `POST /api/models/download`, `_download_command`, `_manual_download_command`, `_download_job`, `_resolve_download_path`, `_hf_snapshot_dir`, `_download_active` guard; add `from app.fit import fit_verdict`, `import shutil`, `from datetime import datetime, timezone`, `from pathlib import Path`.
- `backend/app/hf.py` — unchanged (existing `download_command` kept; endpoint builds its own command list).
- `backend/tests/test_api.py` — new tests; extend the `client` fixture with `hf_cache_dir=tmp_path/"hf"`.

**Frontend (modify):**
- `frontend/src/api/client.ts` — extend `Analysis`; add `downloadModel`.
- `frontend/src/ws/useDownloadProgress.ts` — new hook (create).
- `frontend/src/App.tsx` — fit banner + per-server download rows + `downloads` state.
- `frontend/src/App.test.tsx` — mock `useDownloadProgress`; new tests.
- `frontend/src/ws/useDownloadProgress.test.ts` — new hook test (create).
- `frontend/e2e/mock-server.ts` — reflect new analyze/download shape.

---

## Part A — Backend

### Task 1: analyze returns fit_verdict + hardware

**Files:**
- Modify: `backend/app/api.py:1-13` (imports), `backend/app/api.py:80-89` (analyze return)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api.py`:

```python
def test_analyze_includes_fit_verdict_and_hardware(client, httpx_mock):
    httpx_mock.add_response(
        url="https://huggingface.co/api/models/org/model/tree/main",
        json=[{"path": "README.md", "type": "file", "size": 100},
              {"path": "model.safetensors", "type": "file", "size": 4000000000}],
    )
    httpx_mock.add_response(url="https://huggingface.co/org/model/raw/main/README.md",
                            text="# M\n")
    r = client.post("/api/models/analyze", json={"input": "org/model"})
    assert r.status_code == 200
    body = r.json()
    fv = body["fit_verdict"]
    assert isinstance(fv["warning"], bool)
    assert isinstance(fv["needed_gb"], float)
    assert fv["stage"] in ("gpu", "ram_offload", "ram", "no_fit")
    hw = body["hardware"]
    assert "gpu_vram_gb" in hw and "ram_total_gb" in hw and "gpu_name" in hw
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api.py::test_analyze_includes_fit_verdict_and_hardware -v`
Expected: FAIL with `KeyError: 'fit_verdict'`.

- [ ] **Step 3: Implement**

In `backend/app/api.py`, add the imports:

```python
from app.fit import fit_verdict
from app.hardware import detect_hardware
```

(`detect_hardware` is already imported.)

Replace the analyze return block:

```python
    weights = _hf.weights_size_bytes(files)
    hw = detect_hardware()
    verdict = fit_verdict(weights, hw["gpu_vram_gb"], hw["ram_total_gb"])
    return {
        "repo_id": repo_id,
        "detected_server": detected,
        "server_scores": scores,
        "readme_flags": flags,
        "gguf_files": gguf,
        "weights_bytes": weights,
        "downloaded": _model_status(s, repo_id),
        "fit_verdict": verdict,
        "hardware": {
            "gpu_vram_gb": hw["gpu_vram_gb"],
            "ram_total_gb": hw["ram_total_gb"],
            "gpu_name": hw["gpu_name"],
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api.py -v`
Expected: PASS (all existing api tests still pass too).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: include fit verdict and hardware in analyze response"
```

### Task 2: download endpoint — validation + CLI-missing 400

**Files:**
- Modify: `backend/app/api.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py`:

```python
def test_download_missing_fields_422(client):
    assert client.post("/api/models/download", json={}).status_code == 422
    assert client.post("/api/models/download", json={"repo_id": "org/model"}).status_code == 422
    assert client.post("/api/models/download",
                       json={"repo_id": "org/model", "server_id": "nope"}).status_code == 422


def test_download_cli_missing_400_with_manual_command(client, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    r = client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
    assert r.status_code == 400
    assert "hf download org/model" in r.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api.py::test_download_missing_fields_422 tests/test_api.py::test_download_cli_missing_400_with_manual_command -v`
Expected: FAIL with `404 Not Found` (route does not exist).

- [ ] **Step 3: Implement**

In `backend/app/api.py`, add imports:

```python
import shutil
from datetime import datetime, timezone
from pathlib import Path
```

Add constants near the top (after `router = APIRouter(...)`):

```python
KNOWN_SERVERS = ("llama.cpp", "vllm", "sglang")


def _download_command(repo_id: str, server_id: str) -> list[str]:
    if server_id == "llama.cpp":
        return ["hf", "download", repo_id, "--include", "*.gguf"]
    return ["hf", "download", repo_id]
```

Add the endpoint after `delete_model`:

```python
@router.post("/models/download")
async def start_download(payload: dict):
    s = _require_state()
    repo_id = payload.get("repo_id")
    server_id = payload.get("server_id")
    if repo_id is None:
        raise HTTPException(422, "Missing required field 'repo_id'.")
    if server_id not in KNOWN_SERVERS:
        raise HTTPException(422, f"'server_id' must be one of {list(KNOWN_SERVERS)}.")
    cmd = _download_command(repo_id, server_id)
    if shutil.which("hf") is None:
        raise HTTPException(400, f"HF CLI not found. Run: {' '.join(cmd)}")
    with s._state_lock:
        if s._download_active:
            raise HTTPException(409, "A download is already running")
        s._download_active = True
    asyncio.create_task(_download_job(s, repo_id, server_id, cmd, payload.get("gguf_filename")))
    return {"ok": True}
```

Add `_download_active` to `AppState.__init__` (next to `_job_active`):

```python
        self._download_active = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api.py::test_download_missing_fields_422 tests/test_api.py::test_download_cli_missing_400_with_manual_command -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: add models/download endpoint with validation and CLI check"
```

### Task 3: download background job — success path (vllm)

**Files:**
- Modify: `backend/app/api.py`
- Test: `backend/tests/test_api.py`
- Modify: `backend/tests/test_api.py` `client` fixture

- [ ] **Step 1: Extend the client fixture so HF cache is hermetic**

In `backend/tests/test_api.py`, change the `client` fixture to:

```python
@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path, gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf",
                        workload_file=tmp_path / "prompts.jsonl")
    (tmp_path / "prompts.jsonl").write_text("{\"prompt\": \"hi\"}\n")
    with TestClient(create_app(settings)) as c:
        yield c
```

- [ ] **Step 2: Write the failing test**

Add to `backend/tests/test_api.py`:

```python
class FakeDownloadProcess:
    def __init__(self, lines, rc=0):
        self._lines = list(lines)
        self._i = 0
        self.returncode = rc
        self.stdout = self

    async def readline(self):
        if self._i < len(self._lines):
            line = self._lines[self._i]
            self._i += 1
            return line.encode()
        return b""

    async def wait(self):
        return self.returncode


def test_download_vllm_success_upserts_downloaded(client, tmp_path, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_create(*a, **k):
        return FakeDownloadProcess(["Fetching files...", "Done"], rc=0)

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    snapshot = tmp_path / "hf" / "models--org--model"
    snapshot.mkdir(parents=True)

    r = client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
    assert r.status_code == 200 and r.json()["ok"] is True

    def row():
        m = api_mod.db_mod.get_model(api_mod.state.conn, "org/model", "vllm")
        return m and m["status"]

    assert _poll(lambda: row() == "downloaded")
    assert events[0]["type"] == "download_started"
    assert "hf download org/model" in events[0]["command"]
    assert any(e["type"] == "download_log" and e["line"] == "Fetching files..." for e in events)
    done = next(e for e in events if e["type"] == "download_done")
    assert done["local_path"] == str(snapshot)
    assert api_mod.state._download_active is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api.py::test_download_vllm_success_upserts_downloaded -v`
Expected: FAIL with `NameError: name '_download_job' is not defined`.

- [ ] **Step 4: Implement**

In `backend/app/api.py`, add after `_model_status` (or after `delete_model`):

```python
def _hf_snapshot_dir(settings: Settings, repo_id: str) -> Path:
    org, name = repo_id.split("/", 1)
    base = settings.hf_cache_dir or (Path.home() / ".cache" / "huggingface" / "hub")
    return base / f"models--{org}--{name}"


def _resolve_download_path(s: AppState, repo_id: str, server_id: str,
                           gguf_filename: str | None) -> tuple[str | None, str | None, int | None]:
    if server_id == "llama.cpp":
        gguf_dir = s.settings.resolved_gguf_dir
        if gguf_filename and (gguf_dir / gguf_filename).exists():
            p = gguf_dir / gguf_filename
            return str(p), gguf_filename, p.stat().st_size
        for p in sorted(gguf_dir.glob("*.gguf")):
            return str(p), p.name, p.stat().st_size
        return None, None, None
    snapshot = _hf_snapshot_dir(s.settings, repo_id)
    if snapshot.exists():
        return str(snapshot), None, None
    return None, None, None


async def _download_job(s: AppState, repo_id: str, server_id: str,
                        cmd: list[str], gguf_filename: str | None):
    try:
        await broadcast(s, {"type": "download_started", "server_id": server_id,
                            "repo_id": repo_id, "command": " ".join(cmd)})
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode(errors="replace").rstrip("\n")
            await broadcast(s, {"type": "download_log", "server_id": server_id,
                                "repo_id": repo_id, "line": line})
        rc = await proc.wait()
        if rc != 0:
            db_mod.upsert_model(s.conn, repo_id=repo_id, server_id=server_id,
                                format="hf", local_path="", status="missing")
            await broadcast(s, {"type": "download_error", "server_id": server_id,
                                "repo_id": repo_id, "message": f"download exited with code {rc}"})
            return
        local_path, gguf_resolved, size = _resolve_download_path(s, repo_id, server_id, gguf_filename)
        if local_path is None:
            db_mod.upsert_model(s.conn, repo_id=repo_id, server_id=server_id,
                                format="hf", local_path="", status="missing")
            await broadcast(s, {"type": "download_error", "server_id": server_id,
                                "repo_id": repo_id, "message": "download finished but no artifact was found"})
            return
        db_mod.upsert_model(s.conn, repo_id=repo_id, server_id=server_id, format="hf",
                            local_path=local_path, status="downloaded",
                            gguf_filename=gguf_resolved, size_bytes=size,
                            downloaded_at=datetime.now(timezone.utc).isoformat())
        await broadcast(s, {"type": "download_done", "server_id": server_id,
                            "repo_id": repo_id, "status": "downloaded", "local_path": local_path})
    except Exception as e:
        await broadcast(s, {"type": "download_error", "server_id": server_id,
                            "repo_id": repo_id, "message": str(e)})
    finally:
        with s._state_lock:
            s._download_active = False
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api.py::test_download_vllm_success_upserts_downloaded -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: run hf download in background job with ws log streaming"
```

### Task 4: llama.cpp GGUF resolution

**Files:**
- Modify: `backend/app/api.py` (only if `_resolve_download_path` needs no change)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api.py`:

```python
def test_download_llama_resolves_gguf_file(client, tmp_path, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_create(*a, **k):
        return FakeDownloadProcess(["ok"], rc=0)

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    gguf = tmp_path / "gguf" / "model.Q4_K_M.gguf"
    gguf.parent.mkdir(parents=True)
    gguf.write_bytes(b"x" * 2048)

    r = client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "llama.cpp"})
    assert r.status_code == 200
    assert _poll(lambda: (api_mod.db_mod.get_model(api_mod.state.conn, "org/model", "llama.cpp") or {})["status"] == "downloaded")
    row = api_mod.db_mod.get_model(api_mod.state.conn, "org/model", "llama.cpp")
    assert row["local_path"] == str(gguf)
    assert row["gguf_filename"] == "model.Q4_K_M.gguf"
    assert row["size_bytes"] == 2048
    assert "download_started" in [e["type"] for e in events]
    start = next(e for e in events if e["type"] == "download_started")
    assert "--include" in start["command"] and "*.gguf" in start["command"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api.py::test_download_llama_resolves_gguf_file -v`
Expected: FAIL (endpoint not implemented yet in this branch of the flow, e.g. `_download_active`/`_download_job` may be present but the llama branch currently never runs) — if Task 3 landed, this will instead PASS immediately. If it passes on first run, that is acceptable (the llama branch was implemented in Task 3); mark the task done after confirming the assertion for `--include` holds.

- [ ] **Step 3: Run the full api suite**

Run: `.venv/bin/python -m pytest tests/test_api.py -v`
Expected: PASS (all download tests + existing tests).

- [ ] **Step 4: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "test: llama.cpp download resolves gguf path and size"
```

### Task 5: 409 when a download is already active

**Files:**
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api.py`:

```python
def test_download_rejects_duplicate(client, monkeypatch):
    import app.api as api_mod
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    api_mod.state._download_active = True
    try:
        r = client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
        assert r.status_code == 409
    finally:
        api_mod.state._download_active = False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api.py::test_download_rejects_duplicate -v`
Expected: FAIL with `assert 200 == 409`.

- [ ] **Step 3: Implement**

In `backend/app/api.py`, inside `start_download`, the active-guard block already raises 409. Verify the block reads:

```python
    with s._state_lock:
        if s._download_active:
            raise HTTPException(409, "A download is already running")
        s._download_active = True
```

If it does, no code change is needed — re-run. Otherwise update it to the above.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: reject concurrent downloads with 409"
```

---

## Part B — Frontend

### Task 6: client types + downloadModel + useDownloadProgress hook

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/ws/useDownloadProgress.ts`
- Create: `frontend/src/ws/useDownloadProgress.test.ts`

- [ ] **Step 1: Write the failing hook test**

Create `frontend/src/ws/useDownloadProgress.test.ts`:

```typescript
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

test("useDownloadProgress connects when active and collects events", () => {
  const orig = globalThis.WebSocket;
  (globalThis as { WebSocket: unknown }).WebSocket = FakeWS;
  try {
    const { result } = renderHook(() => useDownloadProgress(true));
    const ws = FakeWS.instances[FakeWS.instances.length - 1];
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

test("useDownloadProgress closes the socket when deactivated", () => {
  const orig = globalThis.WebSocket;
  (globalThis as { WebSocket: unknown }).WebSocket = FakeWS;
  try {
    const { rerender, unmount } = renderHook(({ active }) => useDownloadProgress(active), {
      initialProps: { active: true },
    });
    const ws = FakeWS.instances[FakeWS.instances.length - 1];
    rerender({ active: false });
    expect(ws.closed).toBe(true);
    unmount();
  } finally {
    (globalThis as { WebSocket: unknown }).WebSocket = orig;
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/ws/useDownloadProgress.test.ts`
Expected: FAIL with "Cannot find module './useDownloadProgress'".

- [ ] **Step 3: Implement**

Create `frontend/src/ws/useDownloadProgress.ts`:

```typescript
import { useEffect, useRef, useState } from "react";

export interface DownloadEvent {
  type: "download_started" | "download_log" | "download_done" | "download_error";
  server_id?: string;
  repo_id?: string;
  command?: string;
  line?: string;
  status?: string;
  local_path?: string;
  message?: string;
}

export function useDownloadProgress(active: boolean) {
  const [events, setEvents] = useState<DownloadEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!active) return;
    const ws = new WebSocket("ws://localhost:8000/api/ws");
    wsRef.current = ws;
    ws.onmessage = (msg) => {
      setEvents((prev) => [...prev, JSON.parse(msg.data) as DownloadEvent]);
    };
    return () => ws.close();
  }, [active]);

  return events;
}
```

Modify `frontend/src/api/client.ts`:

```typescript
export interface FitVerdict {
  stage: string;
  warning: boolean;
  needed_gb: number;
}
```

Extend `Analysis` (add `fit_verdict?` and `hardware?`):

```typescript
export interface Analysis {
  repo_id?: string;
  detected_server?: string | null;
  readme_flags?: Record<string, string>;
  gguf_files?: Array<{ path: string; size: number }>;
  weights_bytes?: number;
  downloaded?: Record<string, boolean>;
  fit_verdict?: FitVerdict;
  hardware?: { gpu_vram_gb?: number; ram_total_gb?: number; gpu_name?: string };
}
```

Add a method to the `api` object:

```typescript
  downloadModel: (body: { repo_id: string; server_id: string; gguf_filename?: string }) =>
    request<{ ok: boolean }>("/models/download", {
      method: "POST",
      body: JSON.stringify(body),
    }),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/ws/useDownloadProgress.test.ts src/api`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/ws/useDownloadProgress.ts frontend/src/ws/useDownloadProgress.test.ts
git commit -m "feat: add downloadModel api and useDownloadProgress ws hook"
```

### Task 7: fit verdict warning banner

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write the failing tests**

Add the mocked api method to the `vi.mock("./api/client", ...)` factory in `frontend/src/App.test.tsx`:

```typescript
    downloadModel: vi.fn().mockResolvedValue({ ok: true }),
```

Add a mock for the new hook next to the `useBenchmarkProgress` mock:

```typescript
let mockDownloadEvents: Array<{ type: string; [k: string]: unknown }> = [];
vi.mock("./ws/useDownloadProgress", () => ({ useDownloadProgress: vi.fn() }));
```

Add tests:

```typescript
test("fit warning banner renders when fit_verdict.warning is true", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "vllm",
    readme_flags: {},
    fit_verdict: { stage: "no_fit", warning: true, needed_gb: 40.5 },
    hardware: { gpu_vram_gb: 8, ram_total_gb: 32, gpu_name: "RTX 4090" },
    downloaded: { "llama.cpp": false, vllm: false, sglang: false },
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));

  expect(await screen.findByText(/headroom tight/i)).toBeInTheDocument();
  expect(screen.getByText(/40\.5 GB/)).toBeInTheDocument();
});

test("fit warning banner absent when fit_verdict.warning is false", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "vllm",
    readme_flags: {},
    fit_verdict: { stage: "gpu", warning: false, needed_gb: 3.8 },
    hardware: { gpu_vram_gb: 24, ram_total_gb: 64, gpu_name: "RTX 4090" },
    downloaded: { "llama.cpp": false, vllm: false, sglang: false },
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

  expect(screen.queryByText(/headroom tight/i)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/App.test.tsx`
Expected: FAIL — banner text never appears.

- [ ] **Step 3: Implement**

In `frontend/src/App.tsx`, extend the local `Analysis` interface:

```typescript
interface Analysis {
  repo_id?: string;
  detected_server?: string | null;
  readme_flags?: Record<string, string>;
  gguf_files?: Array<{ path: string; size: number }>;
  weights_bytes?: number;
  downloaded?: Record<string, boolean>;
  fit_verdict?: { stage: string; warning: boolean; needed_gb: number };
  hardware?: { gpu_vram_gb?: number; ram_total_gb?: number; gpu_name?: string };
}
```

Inside the MODEL INPUT panel, after the existing `analysis?.repo_id && (<p>→ ...</p>)` block, add:

```tsx
                {analysis?.fit_verdict?.warning && (
                  <p style={{ color: "var(--accent)", fontSize: 12, margin: 0 }}>
                    headroom tight — model needs ~{analysis.fit_verdict.needed_gb} GB (weights + KV cache),
                    available {analysis.hardware?.gpu_vram_gb ?? 0} GB VRAM +{" "}
                    {analysis.hardware?.ram_total_gb ?? 0} GB RAM
                  </p>
                )}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/App.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat: show fit verdict warning banner in model input panel"
```

### Task 8: per-server download rows + WS consumption

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/App.test.tsx`:

```typescript
test("download flow: click Download, shows downloading then downloaded and refreshes list", async () => {
  const { api } = await import("./api/client");
  const useDownloadProgress = (await import("./ws/useDownloadProgress")).useDownloadProgress;
  const downloadModelSpy = vi.spyOn(api, "downloadModel");
  downloadModelSpy.mockResolvedValueOnce({ ok: true });

  const view = render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  const downloadBtn = screen.getByText("Download");
  fireEvent.click(downloadBtn);
  expect(downloadModelSpy).toHaveBeenCalledWith({ repo_id: "org/model", server_id: "vllm" });
  expect(await screen.findByText(/downloading/i)).toBeInTheDocument();

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "download_log", server_id: "vllm", repo_id: "org/model", line: "Fetching..." },
    { type: "download_done", server_id: "vllm", repo_id: "org/model", status: "downloaded", local_path: "/x" },
  ]);
  view.rerender(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  expect(await screen.findByText(/downloaded/i)).toBeInTheDocument();
  await waitFor(() => expect(api.listModels).toHaveBeenCalledTimes(2));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/App.test.tsx`
Expected: FAIL — `getByText("Download")` not found (button not implemented).

- [ ] **Step 3: Implement**

In `frontend/src/App.tsx`:

Add a module-level constant and import the hook:

```typescript
import { useDownloadProgress } from "./ws/useDownloadProgress";

const KNOWN_SERVERS = ["llama.cpp", "vllm", "sglang"] as const;
```

Add state and effect wiring (after the existing `downloaded` state):

```typescript
  interface DownloadStatus {
    status: "downloading" | "downloaded" | "error";
    line?: string;
    message?: string;
    local_path?: string;
  }
  const [downloads, setDownloads] = useState<Record<string, DownloadStatus>>({});
  const downloadActive = Object.values(downloads).some((d) => d.status === "downloading");
  const downloadEvents = useDownloadProgress(downloadActive);

  useEffect(() => {
    for (const ev of downloadEvents) {
      if (!ev.server_id || !ev.repo_id) continue;
      const key = `${ev.server_id}::${ev.repo_id}`;
      if (ev.type === "download_log") {
        setDownloads((prev) =>
          prev[key] ? { ...prev, [key]: { ...prev[key], line: ev.line } } : prev,
        );
      } else if (ev.type === "download_done") {
        setDownloads((prev) => ({
          ...prev,
          [key]: { status: "downloaded", local_path: ev.local_path },
        }));
        api.listModels().then((d) => setDownloaded(d.models));
      } else if (ev.type === "download_error") {
        setDownloads((prev) => ({
          ...prev,
          [key]: { status: "error", message: ev.message },
        }));
      }
    }
  }, [downloadEvents]);
```

Add `onDownload` and clear downloads on re-analyze:

```typescript
  const onDownload = useCallback(
    async (serverId: string) => {
      if (!analysis?.repo_id) return;
      const key = `${serverId}::${analysis.repo_id}`;
      setDownloads((prev) => ({ ...prev, [key]: { status: "downloading" } }));
      try {
        await api.downloadModel({ repo_id: analysis.repo_id, server_id: serverId });
        setDownloads((prev) => ({ ...prev, [key]: { status: "downloading" } }));
      } catch (err) {
        setDownloads((prev) => ({
          ...prev,
          [key]: { status: "error", message: err instanceof Error ? err.message : String(err) },
        }));
      }
    },
    [analysis],
  );
```

In `onAnalyze`, add `setDownloads({});` after `setConfigs([]);`.

Render the per-server rows in the MODEL INPUT panel after the fit banner block:

```tsx
                {analysis?.repo_id && (
                  <div className="row" style={{ gap: 12, marginTop: 8, flexWrap: "wrap" }}>
                    {KNOWN_SERVERS.map((sid) => {
                      const key = `${sid}::${analysis.repo_id}`;
                      const dl = downloads[key];
                      const already = analysis.downloaded?.[sid];
                      return (
                        <span key={sid} style={{ fontSize: 12 }}>
                          <b>{sid}:</b>{" "}
                          {dl?.status === "downloading" ? (
                            <span style={{ color: "var(--anode)" }}>
                              downloading{dl.line ? ` — ${dl.line}` : "…"}
                            </span>
                          ) : dl?.status === "downloaded" || already ? (
                            <span style={{ color: "var(--anode)" }}>downloaded</span>
                          ) : dl?.status === "error" ? (
                            <span style={{ color: "var(--accent)" }}>error: {dl.message}</span>
                          ) : (
                            <button onClick={() => onDownload(sid)}>Download</button>
                          )}
                        </span>
                      );
                    })}
                  </div>
                )}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/App.test.tsx`
Expected: PASS.

- [ ] **Step 5: Type-check and full unit suite**

Run: `npx vitest run`
Expected: PASS. Then `npm run build` — expected PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat: per-server download buttons with ws progress in model input panel"
```

### Task 9: e2e mock server reflects new shapes + run e2e

**Files:**
- Modify: `frontend/e2e/mock-server.ts`

- [ ] **Step 1: Update the mock server**

In `frontend/e2e/mock-server.ts`, change the analyze branch to:

```typescript
  } else if (req.url?.startsWith("/api/models/analyze")) {
    Object.assign(body, {
      repo_id: "org/model", detected_server: "vllm",
      readme_flags: { "--max-model-len": "8192" }, weights_bytes: 4e9,
      fit_verdict: { stage: "gpu", warning: false, needed_gb: 3.8 },
      hardware: { gpu_vram_gb: 24, ram_total_gb: 64, gpu_name: "RTX 4090" },
      downloaded: { "llama.cpp": false, vllm: false, sglang: false },
    });
  } else if (req.url?.startsWith("/api/models/download")) {
    Object.assign(body, { ok: true });
```

- [ ] **Step 2: Verify e2e still passes**

Run (port 8000 must be free):
`npm run e2e`
Expected: PASS (1 test).

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/mock-server.ts
git commit -m "test: update e2e mock server for analyze/download endpoints"
```

---

## Part C — Verify and finish branch

### Task 10: full verification

- [ ] **Step 1: Backend suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS (all existing + new).

- [ ] **Step 2: Frontend suite + build**

Run: `npx vitest run && npm run build`
Expected: PASS.

- [ ] **Step 3: e2e**

Run: `npm run e2e`
Expected: PASS.

### Task 11: finish the branch

- [ ] **Step 1: Invoke the finishing-a-development-branch skill**

Use superpowers:finishing-a-development-branch to integrate `feature/llmbench` into `master` (no remote; the skill will recommend merge or squash locally).

---

## Self-Review

**Spec coverage:**
- Fit verdict server-side in analyze + inline MODEL INPUT banner → Tasks 1, 7.
- `POST /api/models/download` validation + CLI-missing 400 with manual command → Task 2.
- `hf download` background job with `download_log` line streaming + `download_done`/`download_error` → Task 3.
- llama.cpp `--include "*.gguf"` + GGUF dir resolution + `gguf_filename` + size → Tasks 2, 4.
- vllm/sglang HF cache snapshot resolution → Task 3 (`_hf_snapshot_dir`).
- `_download_active` guard → 409 → Tasks 2, 5.
- Frontend `downloadModel`, `useDownloadProgress`, per-server rows in MODEL INPUT, refresh `listModels` on done → Tasks 6, 8.
- e2e mock server reflects new shapes → Task 9.

**Placeholders:** none; every code step has full code.

**Type consistency:** `downloads` keyed `"{server_id}::{repo_id}"` in App matches `downloadEvents` handling and `onDownload`. `DownloadEvent.server_id/repo_id` optional in the hook (mirrors `ProgressEvent`). `api.downloadModel` body `{repo_id, server_id, gguf_filename?}` matches backend `start_download` payload. Backend `_resolve_download_path` returns `(local_path, gguf_filename, size_bytes)` and `_download_job` consumes in that order.
