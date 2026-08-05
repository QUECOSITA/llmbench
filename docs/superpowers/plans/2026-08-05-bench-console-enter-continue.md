# Live Bench Command Console + Enter-to-Continue — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream each bench command's live output into an accumulating console in the 03 · RUN panel and, when the PAUSE toggle is on, wait for an Enter keypress after every config (including the last) before continuing.

**Architecture:** Backend streams line events over the existing WebSocket (`bench_log`) by rewriting `BenchmarkRunner` to read stdout/stderr concurrently through `TtyStream` instead of `communicate()`. A continue gate in `_run_job` (an `asyncio.Queue` on `AppState`) blocks between configs until the client POSTs `/benchmarks/continue`; a watchdog auto-advances after 3s of zero WS clients. Frontend extends the `progressReducer` with `lines`/`currentCommand`/`waiting` state and renders a reused `.dl-console` in `RunPanel` with a PAUSE checkbox and a `PRESS ENTER TO CONTINUE` prompt.

**Tech Stack:** Python 3 / FastAPI (pytest TDD), React + TypeScript (vitest), Playwright e2e.

**Working dirs:** backend steps run from `backend/`, frontend steps from `frontend/`. All git commands run from the repo root `/home/ruben/test` and only ever touch `llmbench/...` paths (the git repo is a scratch repo containing unrelated projects — never `git add .`).

---

## Task 1: `BenchmarkRunner` streams output lines

**Files:**
- Modify: `llmbench/backend/app/benchmark.py`
- Test: `llmbench/backend/tests/test_benchmark.py`

- [ ] **Step 1: Write the failing tests**

Replace the entire `backend/tests/test_benchmark.py` file's runner section (everything from line 98 `import asyncio` to the end) with:

```python
import asyncio

from app.benchmark import BenchmarkRunner
from app.tty_stream import TtyStream

FAKE_BENCH = """\
model,size,params,backend,test,t,n_threads,batch,ngl,ms,t/s
x,Q4,7B,CUDA,pp,0,8,512,999,40,1000.0
x,Q4,7B,CUDA,tg,0,8,512,999,900,80.0
"""


def _reader(data: bytes) -> asyncio.StreamReader:
    r = asyncio.StreamReader()
    if data:
        r.feed_data(data)
    r.feed_eof()
    return r


class FakeProc:
    def __init__(self, out: bytes, err: bytes = b"", rc: int = 0):
        self.stdout = _reader(out)
        self.stderr = _reader(err)
        self.returncode = rc
        self.killed = False

    async def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class HangReader(asyncio.StreamReader):
    async def read(self, n=-1):
        await asyncio.sleep(3600)
        return b""


class HangProc(FakeProc):
    def __init__(self):
        self.stdout = HangReader()
        self.stderr = _reader(b"")
        self.returncode = 0
        self.killed = False


async def test_runner_streams_output_and_returns_full_output(monkeypatch):
    seen = []

    async def fake_create(*a, **k):
        return FakeProc(FAKE_BENCH.encode(), err=b"warning: loading model\n")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="llama.cpp", bench_command=["llama-bench", "-m", "x"],
                             timeout_s=60)

    async def on_output(kind, text):
        seen.append((kind, text))

    result = await runner.run(on_output=on_output)
    assert result["status"] == "ok"
    assert result["decode_tps"] == 80.0
    assert result["prompt_processing_tps"] == 1000.0
    assert ("line", "warning: loading model") in seen
    assert "warning: loading model" in result["output"]
    assert FAKE_BENCH in result["output"]


async def test_runner_emits_progress_for_carriage_returns(monkeypatch):
    seen = []

    async def fake_create(*a, **k):
        return FakeProc(FAKE_BENCH.encode(),
                        err=b"Processing: 0%\rProcessing: 50%\rProcessing: 100%\r\n")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="llama.cpp", bench_command=["llama-bench", "-m", "x"],
                             timeout_s=60)

    async def on_output(kind, text):
        seen.append((kind, text))

    result = await runner.run(on_output=on_output)
    assert result["status"] == "ok"
    assert any(kind == "progress" for kind, _ in seen)


async def test_runner_merges_stderr_only_for_output_not_parse(monkeypatch):
    async def fake_create(*a, **k):
        return FakeProc(b"bunch of non-json text", err=b"stderr noise")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="vllm", bench_command=["bench"], timeout_s=60)
    result = await runner.run()
    assert result["status"] == "failed"
    assert "stderr noise" in result["output"]


async def test_runner_timeout_kills(monkeypatch):
    async def fake_create(*a, **k):
        return HangProc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="llama.cpp", bench_command=["llama-bench"],
                             timeout_s=0.05)
    result = await runner.run()
    assert result["status"] == "failed"


async def test_runner_abort(monkeypatch):
    async def fake_create(*a, **k):
        return FakeProc(b"")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="llama.cpp", bench_command=["llama-bench"],
                             timeout_s=60)
    runner.abort()
    result = await runner.run()
    assert result["status"] == "aborted"
```

Note: the parser tests at the top of `test_benchmark.py` (lines 1-96) are untouched.

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `source .venv/bin/activate && python -m pytest tests/test_benchmark.py -q`
Expected: the new runner tests FAIL with `TypeError: run() got an unexpected keyword argument 'on_output'`.

- [ ] **Step 3: Implement**

In `backend/app/benchmark.py`, add the `TtyStream` import and replace the `BenchmarkRunner.run` method (lines 84-129) and add a `_collect` helper. Add `from app.tty_stream import TtyStream` next to the existing imports (after line 4 `import re`).

Replace the whole `BenchmarkRunner` class body (lines 72-129) with:

```python
class BenchmarkRunner:
    def __init__(self, server_id: str, bench_command: list[str], timeout_s: float):
        self.server_id = server_id
        self.bench_command = bench_command
        self.timeout_s = timeout_s
        self._aborted = asyncio.Event()
        self._done = asyncio.Event()
        self._proc: asyncio.subprocess.Process | None = None

    def abort(self) -> None:
        self._aborted.set()

    async def run(self, on_output=None) -> dict:
        """Run the bench command, streaming decoded (kind, text) events to
        on_output. Returns the parsed result with full output text."""
        self._done.clear()
        if self._aborted.is_set():
            self._done.set()
            return {"status": "aborted", "prompt_processing_tps": None, "decode_tps": None,
                    "duration_s": 0.0, "output": ""}
        start = asyncio.get_event_loop().time()
        self._proc = await asyncio.create_subprocess_exec(
            *self.bench_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes, rc = await asyncio.wait_for(
                self._collect(self._proc, on_output), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            self._proc.kill()
            await self._proc.wait()
            duration = asyncio.get_event_loop().time() - start
            self._done.set()
            return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                    "duration_s": duration, "output": f"timeout after {self.timeout_s}s"}
        finally:
            self._proc = None
        duration = asyncio.get_event_loop().time() - start
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        output = stdout + ("\n" + stderr if stderr else "")
        if self._aborted.is_set():
            self._done.set()
            return {"status": "aborted", "prompt_processing_tps": None, "decode_tps": None,
                    "duration_s": duration, "output": output}
        if rc != 0:
            self._done.set()
            return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                    "duration_s": duration, "output": output}
        try:
            parsed = PARSERS[self.server_id](stdout)
        except Exception:
            self._done.set()
            return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                    "duration_s": duration, "output": output}
        if parsed["decode_tps"] is None:
            self._done.set()
            return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                    "duration_s": duration, "output": output}
        self._done.set()
        return {"status": "ok", **parsed, "duration_s": duration, "output": output}

    async def _collect(self, proc, on_output) -> tuple[bytes, bytes, int]:
        out_tty = TtyStream()
        err_tty = TtyStream()
        out_parts: list[bytes] = []
        err_parts: list[bytes] = []

        async def pump(stream, tty, parts):
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                if self._aborted.is_set():
                    proc.kill()
                    break
                parts.append(chunk)
                if on_output is not None:
                    for kind, text in tty.feed(chunk):
                        await on_output(kind, text)
            if on_output is not None:
                for kind, text in tty.flush():
                    await on_output(kind, text)

        await asyncio.gather(pump(proc.stdout, out_tty, out_parts),
                             pump(proc.stderr, err_tty, err_parts))
        rc = proc.returncode
        if rc is None:
            rc = await proc.wait()
        return b"".join(out_parts), b"".join(err_parts), rc
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `source .venv/bin/activate && python -m pytest tests/test_benchmark.py -q`
Expected: PASS (all runner + parser tests).

- [ ] **Step 5: Commit**

```bash
git -C /home/ruben/test add llmbench/backend/app/benchmark.py llmbench/backend/tests/test_benchmark.py
git -C /home/ruben/test commit -m "feat: benchmark runner streams output lines via TtyStream"
```

---

## Task 2: API pause gate, `bench_log` broadcast, continue endpoint

**Files:**
- Modify: `llmbench/backend/app/api.py`
- Test: `llmbench/backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_api.py`:

1. Replace the `FakeProcess` class (lines 17-30) and add a `_reader` helper right after it:

```python
def _reader(data: bytes) -> asyncio.StreamReader:
    r = asyncio.StreamReader()
    if data:
        r.feed_data(data)
    r.feed_eof()
    return r


class FakeProcess:
    def __init__(self, out, err=b"", rc=0):
        self.stdout = _reader(out)
        self.stderr = _reader(err)
        self.returncode = rc
        self.killed = False

    async def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True
```

2. Update `test_start_run_rejects_duplicate` (lines 178-211) so the hanging proc uses readers instead of `communicate()`:

```python
def test_start_run_rejects_duplicate(client, monkeypatch):
    release = asyncio.Event()

    class HangReader(asyncio.StreamReader):
        async def read(self, n=-1):
            await release.wait()
            return b""

    class HangProcess:
        returncode = 0
        killed = False

        def __init__(self):
            self.stdout = HangReader()
            self.stderr = _reader(b"")

        async def wait(self):
            pass

        def kill(self):
            self.killed = True

    async def fake_create(*a, **k):
        return HangProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    cfg = {
        "server_id": "llama.cpp",
        "flags": {"-c": "4096"},
        "model_id": "org/model",
        "serving_command": "llama-server -m x",
        "bench_command": ["llama-bench", "-m", "x"],
    }
    r1 = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg]})
    assert r1.status_code in (200, 422)
    r2 = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg]})
    assert r2.status_code == 409
    release.set()
```

3. Update `test_full_run_completes_and_persists` (lines 265-294) to pass `"pause": False` so it does not block on the gate:

```python
def test_full_run_completes_and_persists(client, monkeypatch):
    async def fake_create(*a, **k):
        return FakeProcess(FAKE_BENCH.encode())

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    cfg = {
        "server_id": "llama.cpp",
        "flags": {"-c": "4096"},
        "model_id": "org/model",
        "serving_command": "llama-server -m x",
        "bench_command": ["llama-bench", "-m", "x"],
    }
    r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg], "pause": False})
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    def results():
        return client.get(f"/api/benchmarks/{run_id}").json()["results"]

    assert _poll(lambda: bool(results()))
    rows = results()
    assert len(rows) == 1
    assert rows[0]["result_status"] == "ok"
    assert rows[0]["prompt_processing_tps"] == 1000.0
    assert rows[0]["decode_tps"] == 80.0

    detail = client.get(f"/api/benchmarks/{run_id}").json()
    assert detail["status"] == "completed"
    assert detail["total"] == 1
```

4. Append these new tests at the end of `test_api.py`:

```python
def test_pause_run_streams_and_waits_for_continue(client, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_create(*a, **k):
        return FakeProcess(FAKE_BENCH.encode(), err=b"progress noise\n")

    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    class FakeWs:
        pass

    api_mod.state._ws_clients.add(FakeWs())
    try:
        cfg = {
            "server_id": "llama.cpp",
            "flags": {"-c": "4096"},
            "model_id": "org/model",
            "serving_command": "llama-server -m x",
            "bench_command": ["llama-bench", "-m", "x"],
        }
        r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg], "pause": True})
        assert r.status_code == 200
        run_id = r.json()["run_id"]

        assert _poll(lambda: any(e["type"] == "config_wait" for e in events))
        assert any(e["type"] == "bench_log" and e["kind"] == "line" for e in events)
        assert api_mod.db_mod.get_run_status(api_mod.state.conn, run_id) == "running"

        r2 = client.post("/api/benchmarks/continue", json={"run_id": run_id})
        assert r2.status_code == 200

        assert _poll(lambda: api_mod.db_mod.get_run_status(api_mod.state.conn, run_id) == "completed")
        assert any(e["type"] == "config_wait" for e in events)
        assert api_mod.state._continue_queue is None
    finally:
        api_mod.state._ws_clients.discard(FakeWs())


def test_pause_false_runs_straight_through(client, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_create(*a, **k):
        return FakeProcess(FAKE_BENCH.encode())

    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    cfg = {
        "server_id": "llama.cpp",
        "flags": {"-c": "4096"},
        "model_id": "org/model",
        "serving_command": "llama-server -m x",
        "bench_command": ["llama-bench", "-m", "x"],
    }
    r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg], "pause": False})
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    assert _poll(lambda: api_mod.db_mod.get_run_status(api_mod.state.conn, run_id) == "completed")
    assert not any(e["type"] == "config_wait" for e in events)
    assert any(e["type"] == "bench_log" for e in events)


def test_pause_run_auto_advances_when_no_clients(client, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_create(*a, **k):
        return FakeProcess(FAKE_BENCH.encode())

    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    monkeypatch.setattr("app.api.AUTO_ADVANCE_GRACE_S", 0.1)

    cfg = {
        "server_id": "llama.cpp",
        "flags": {"-c": "4096"},
        "model_id": "org/model",
        "serving_command": "llama-server -m x",
        "bench_command": ["llama-bench", "-m", "x"],
    }
    r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg], "pause": True})
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    assert _poll(lambda: api_mod.db_mod.get_run_status(api_mod.state.conn, run_id) == "completed")
    assert any(e["type"] == "config_wait" for e in events)


def test_continue_with_no_pending_run_409(client):
    r = client.post("/api/benchmarks/continue", json={"run_id": 1})
    assert r.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `source .venv/bin/activate && python -m pytest tests/test_api.py -q`
Expected: the new tests FAIL with `KeyError: 'bench_log'` / `404` / `KeyError: 'config_wait'`; `test_full_run_completes_and_persists` and `test_start_run_rejects_duplicate` FAIL with `AttributeError` (no `stdout`/`read` on the old FakeProcess) or hang.

- [ ] **Step 3: Implement**

In `backend/app/api.py`:

1. In `AppState.__init__` (after line 117 `self._prune_answer: asyncio.Queue[str] | None = None`), add:

```python
        self._continue_queue: asyncio.Queue | None = None
        self._active_run_id: int | None = None
```

2. Add a module constant near `KNOWN_SERVERS` (after line 29):

```python
AUTO_ADVANCE_GRACE_S = 3.0
```

3. Replace `start_run` (lines 488-500):

```python
@router.post("/benchmarks")
async def start_run(payload: dict):
    s = _require_state()
    with s._state_lock:
        if s._job_active:
            raise HTTPException(409, "A benchmark is already running")
    repo_id = payload["repo_id"]
    configs = payload.get("configs", [])
    pause = bool(payload.get("pause", True))
    run_id = db_mod.create_run(s.conn, repo_id, len(configs))
    with s._state_lock:
        s._job_active = True
    asyncio.create_task(_run_job(s, run_id, configs, pause=pause))
    return {"run_id": run_id}
```

4. Replace `_run_job` (lines 503-542) and add `_await_continue` after it:

```python
async def _run_job(s: AppState, run_id: int, configs: list[dict], pause: bool = True):
    queue: asyncio.Queue | None = asyncio.Queue() if pause else None
    s._continue_queue = queue
    s._active_run_id = run_id
    try:
        async with s.lock:
            try:
                db_mod.set_run_status(s.conn, run_id, "running")
                await broadcast(s, {"type": "run_started", "run_id": run_id, "total": len(configs)})
                status = "completed"
                for i, cfg in enumerate(configs):
                    await broadcast(s, {"type": "config_start", "run_id": run_id, "index": i,
                                        "total": len(configs), "config": cfg})
                    runner = benchmark_mod.BenchmarkRunner(
                        server_id=cfg["server_id"],
                        bench_command=cfg["bench_command"],
                        timeout_s=s.settings.benchmark_timeout_s,
                    )
                    s.runner = runner

                    async def on_output(kind: str, text: str, _i: int = i) -> None:
                        await broadcast(s, {"type": "bench_log", "run_id": run_id, "index": _i,
                                            "kind": kind, "text": text})

                    result = await runner.run(on_output=on_output)
                    s.runner = None
                    cfg_id = db_mod.create_config(
                        s.conn, run_id, cfg["server_id"], _coerce_model_id(cfg.get("model_id")),
                        cfg["flags"], cfg["serving_command"], " ".join(cfg["bench_command"]),
                    )
                    db_mod.save_result(s.conn, cfg_id, result["prompt_processing_tps"],
                                       result["decode_tps"], result["duration_s"],
                                       result["output"], result["status"])
                    await broadcast(s, {"type": "config_done", "run_id": run_id, "index": i,
                                        "result": result})
                    if result["status"] == "aborted":
                        status = "aborted"
                        break
                    if pause:
                        await broadcast(s, {"type": "config_wait", "run_id": run_id, "index": i})
                        await _await_continue(s, queue)
                db_mod.set_run_status(s.conn, run_id, status)
                await broadcast(s, {"type": "run_done", "run_id": run_id, "status": status})
            except Exception:
                logger.exception("run %s failed", run_id)
                db_mod.set_run_status(s.conn, run_id, "failed")
                await broadcast(s, {"type": "run_done", "run_id": run_id, "status": "failed"})
    finally:
        s.runner = None
        s._continue_queue = None
        s._active_run_id = None
        with s._state_lock:
            s._job_active = False


async def _await_continue(s: AppState, queue: asyncio.Queue | None) -> None:
    if queue is None:
        return
    empty_for = 0.0
    while True:
        if not queue.empty():
            queue.get_nowait()
            return
        if len(s._ws_clients) == 0:
            empty_for += 0.2
            if empty_for >= AUTO_ADVANCE_GRACE_S:
                return
        else:
            empty_for = 0.0
        await asyncio.sleep(0.2)
```

5. Add the continue endpoint after `start_run`:

```python
@router.post("/benchmarks/continue")
async def continue_run(payload: dict):
    s = _require_state()
    if s._continue_queue is None or s._active_run_id is None:
        raise HTTPException(409, "No benchmark is waiting for input")
    if payload.get("run_id") != s._active_run_id:
        raise HTTPException(409, "Run is not waiting for input")
    await s._continue_queue.put("continue")
    return {"ok": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `source .venv/bin/activate && python -m pytest tests/test_api.py -q`
Expected: PASS (all tests, including the 4 new ones and both updated ones).

- [ ] **Step 5: Commit**

```bash
git -C /home/ruben/test add llmbench/backend/app/api.py llmbench/backend/tests/test_api.py
git -C /home/ruben/test commit -m "feat: stream bench_log and gate runs on enter-to-continue"
```

---

## Task 3: Frontend progress state — `bench_log` / `config_wait`

**Files:**
- Modify: `llmbench/frontend/src/ws/useBenchmarkProgress.ts`
- Test: `llmbench/frontend/src/ws/useBenchmarkProgress.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/ws/useBenchmarkProgress.test.ts`:

```ts
import { progressReducer, INITIAL_STATE } from "./useBenchmarkProgress";

test("run_started clears lines and waiting", () => {
  const prev = {
    ...INITIAL_STATE,
    lines: ["old line"],
    waiting: true,
    currentCommand: "old cmd",
  };
  const next = progressReducer(prev, ev("run_started", 1, { total: 2 }));
  expect(next.lines).toEqual([]);
  expect(next.waiting).toBe(false);
  expect(next.currentCommand).toBe("");
});

test("config_start appends a command header line", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 2 }));
  const next = progressReducer(state, {
    type: "config_start",
    run_id: 1,
    index: 0,
    total: 2,
    config: { bench_command: ["llama-bench", "-m", "x", "-o", "csv"] },
  });
  expect(next.lines).toEqual(["▸ config 1/2 — $ llama-bench -m x -o csv"]);
  expect(next.currentCommand).toBe("llama-bench -m x -o csv");
});

test("bench_log line appends and progress replaces the last line", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  const withStart = progressReducer(state, {
    type: "config_start",
    run_id: 1,
    index: 0,
    total: 1,
    config: { bench_command: ["bench"] },
  });
  const withLine = progressReducer(withStart, {
    type: "bench_log", run_id: 1, index: 0, kind: "line", text: "loading...",
  });
  expect(withLine.lines.at(-1)).toBe("loading...");
  const withProgress = progressReducer(withLine, {
    type: "bench_log", run_id: 1, index: 0, kind: "progress", text: "Loading: 50%",
  });
  expect(withProgress.lines).toEqual(["▸ config 1/1 — $ bench", "Loading: 50%"]);
});

test("config_done appends a result line", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  const next = progressReducer(state, ev("config_done", 1, {
    index: 0,
    result: { status: "ok", decode_tps: 42.0, prompt_processing_tps: 100.0 },
  }));
  expect(next.lines.at(-1)).toContain("42.0");
  expect(next.lines.at(-1)).toContain("100.0");
});

test("config_wait sets waiting and run_done clears it", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  const waiting = progressReducer(state, { type: "config_wait", run_id: 1, index: 0 });
  expect(waiting.waiting).toBe(true);
  const done = progressReducer(waiting, ev("run_done", 1));
  expect(done.waiting).toBe(false);
});

test("bench_log for a different run_id is ignored", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  const next = progressReducer(state, {
    type: "bench_log", run_id: 99, index: 0, kind: "line", text: "stray",
  });
  expect(next.lines).toEqual([]);
});
```

Note: the existing `ev` helper is defined at the top of the file; do not redefine it — only add the imports if `progressReducer`/`INITIAL_STATE` are not already imported there. They ARE already imported at the top (lines 1-2), so only append the new tests, without the duplicate import lines. If the appended block repeats an import, remove the duplicate import.

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/ws/useBenchmarkProgress.test.ts`
Expected: new tests FAIL with `TypeError: state.lines is undefined` or similar.

- [ ] **Step 3: Implement**

In `frontend/src/ws/useBenchmarkProgress.ts`:

1. Extend the `ProgressEvent` union type (line 4) to add `"bench_log" | "config_wait"`, and add the `kind`/`text` fields:

```ts
export interface ProgressEvent {
  type: "run_started" | "config_start" | "config_done" | "run_done" | "run_sync" | "bench_log" | "config_wait";
  run_id: number;
  index?: number;
  total?: number;
  config?: unknown;
  kind?: "line" | "progress";
  text?: string;
  result?: { status: string; decode_tps: number | null; prompt_processing_tps: number | null };
  status?: string;
  results?: ResultRow[];
}
```

2. Extend `ProgressState` (lines 22-30) and `INITIAL_STATE` (lines 32-40):

```ts
export interface ProgressState {
  running: boolean;
  runId: number | null;
  index: number;
  total: number;
  promptTps: number | null;
  decodeTps: number | null;
  results: ResultRow[];
  lines: string[];
  currentCommand: string;
  waiting: boolean;
}

export const INITIAL_STATE: ProgressState = {
  running: false,
  runId: null,
  index: 0,
  total: 0,
  promptTps: null,
  decodeTps: null,
  results: [],
  lines: [],
  currentCommand: "",
  waiting: false,
};
```

3. In `progressReducer`, update `run_started` (lines 43-53) to reset the new fields:

```ts
  if (event.type === "run_started") {
    return {
      running: true,
      runId: event.run_id,
      index: 0,
      total: event.total ?? 0,
      promptTps: null,
      decodeTps: null,
      results: [],
      lines: [],
      currentCommand: "",
      waiting: false,
    };
  }
```

4. Replace `config_start` (lines 55-57) with a version that appends the header line:

```ts
  if (event.type === "config_start" && event.run_id === state.runId) {
    const cfg = event.config as { bench_command?: string[] } | undefined;
    const command = cfg?.bench_command?.join(" ") ?? "";
    const header = `▸ config ${(event.index ?? state.index) + 1}/${event.total ?? state.total} — $ ${command}`;
    return {
      ...state,
      index: event.index ?? state.index,
      total: event.total ?? state.total,
      currentCommand: command,
      lines: [...state.lines, header],
    };
  }
```

5. Add `bench_log` and `config_wait` handlers right after the `config_start` block:

```ts
  if (event.type === "bench_log" && event.run_id === state.runId) {
    const text = event.text ?? "";
    const lines =
      event.kind === "progress" && state.lines.length > 0
        ? [...state.lines.slice(0, -1), text]
        : [...state.lines, text];
    return { ...state, lines };
  }

  if (event.type === "config_wait" && event.run_id === state.runId) {
    return { ...state, waiting: true };
  }
```

6. Update `config_done` (lines 59-80) to append a result line. Replace the `return { ...state, index: idx, total: ..., promptTps, decodeTps, results };` return object so it also appends:

```ts
  if (event.type === "config_done" && event.run_id === state.runId) {
    const idx = event.index ?? state.index;
    const promptTps = event.result?.prompt_processing_tps ?? null;
    const decodeTps = event.result?.decode_tps ?? null;
    const newResult: ResultRow = {
      server_id: "",
      flag_conf: {},
      prompt_processing_tps: promptTps,
      decode_tps: decodeTps,
      result_status: event.result?.status ?? null,
    };
    const results = [...state.results];
    results[idx] = newResult;
    const fmt = (v: number | null) => (v == null ? "—" : v.toFixed(1));
    const resultLine = `PROMPT ${fmt(promptTps)} · DECODE ${fmt(decodeTps)} · ${event.result?.status ?? ""}`;
    return {
      ...state,
      index: idx,
      total: event.total ?? state.total,
      promptTps,
      decodeTps,
      results,
      lines: [...state.lines, resultLine],
    };
  }
```

7. Update `run_done` (lines 82-84) to clear `waiting`, and `run_sync` (lines 86-98) to clear `waiting` too:

```ts
  if (event.type === "run_done" && event.run_id === state.runId) {
    return { ...state, running: false, waiting: false };
  }

  if (event.type === "run_sync" && event.run_id === state.runId) {
    const results = event.results ?? [];
    const last = results[results.length - 1];
    return {
      running: false,
      runId: event.run_id,
      index: results.length,
      total: event.total ?? state.total,
      promptTps: last?.prompt_processing_tps ?? null,
      decodeTps: last?.decode_tps ?? null,
      results,
      lines: state.lines,
      currentCommand: state.currentCommand,
      waiting: false,
    };
  }
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `frontend/`): `npx vitest run src/ws/useBenchmarkProgress.test.ts`
Expected: PASS (all existing + new tests).

- [ ] **Step 5: Commit**

```bash
git -C /home/ruben/test add llmbench/frontend/src/ws/useBenchmarkProgress.ts llmbench/frontend/src/ws/useBenchmarkProgress.test.ts
git -C /home/ruben/test commit -m "feat: progress state streams bench log lines and wait flag"
```

---

## Task 4: `api.continueRun` + RunPanel console / wait prompt / PAUSE toggle

**Files:**
- Modify: `llmbench/frontend/src/api/client.ts`
- Modify: `llmbench/frontend/src/components/RunPanel.tsx`
- Test: `llmbench/frontend/src/components/RunPanel.test.tsx`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/RunPanel.test.tsx`:

```tsx
test("console renders accumulated lines and the current command", () => {
  render(
    <RunPanel
      running={false}
      onRun={vi.fn()}
      progress={{ index: 0, total: 2 }}
      lines={["▸ config 1/2 — $ llama-bench -m x", "loading...", "PROMPT 100.0 · DECODE 80.0 · ok"]}
      currentCommand="llama-bench -m x"
      waiting={false}
      pause={true}
      onPauseChange={vi.fn()}
      onContinue={vi.fn()}
    />,
  );
  expect(screen.getByText(/llama-bench -m x/)).toBeInTheDocument();
  expect(screen.getByText(/loading\.\.\./)).toBeInTheDocument();
  expect(screen.getByText(/DECODE 80.0/)).toBeInTheDocument();
});

test("waiting shows the continue prompt and Enter triggers onContinue", () => {
  const onContinue = vi.fn();
  render(
    <RunPanel
      running
      onRun={vi.fn()}
      progress={{ index: 0, total: 1 }}
      lines={["▸ config 1/1 — $ bench"]}
      currentCommand="bench"
      waiting
      pause={true}
      onPauseChange={vi.fn()}
      onContinue={onContinue}
    />,
  );
  expect(screen.getByText(/press enter to continue/i)).toBeInTheDocument();
  fireEvent.keyDown(window, { key: "Enter" });
  expect(onContinue).toHaveBeenCalledTimes(1);
});

test("CONTINUE button also triggers onContinue", () => {
  const onContinue = vi.fn();
  render(
    <RunPanel
      running
      onRun={vi.fn()}
      progress={null}
      lines={["x"]}
      currentCommand="bench"
      waiting
      pause={true}
      onPauseChange={vi.fn()}
      onContinue={onContinue}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /continue/i }));
  expect(onContinue).toHaveBeenCalledTimes(1);
});

test("PAUSE toggle is disabled while running and reflects its value", () => {
  const onPauseChange = vi.fn();
  const { rerender } = render(
    <RunPanel
      running
      onRun={vi.fn()}
      progress={null}
      lines={[]}
      currentCommand=""
      waiting={false}
      pause={true}
      onPauseChange={onPauseChange}
      onContinue={vi.fn()}
    />,
  );
  const checkbox = screen.getByRole("checkbox");
  expect(checkbox).toBeDisabled();
  expect(checkbox).toBeChecked();

  rerender(
    <RunPanel
      running={false}
      onRun={vi.fn()}
      progress={null}
      lines={[]}
      currentCommand=""
      waiting={false}
      pause={false}
      onPauseChange={onPauseChange}
      onContinue={vi.fn()}
    />,
  );
  const enabled = screen.getByRole("checkbox");
  expect(enabled).toBeEnabled();
  expect(enabled).not.toBeChecked();
});

test("console is hidden when there are no lines", () => {
  render(
    <RunPanel
      running={false}
      onRun={vi.fn()}
      progress={null}
      lines={[]}
      currentCommand=""
      waiting={false}
      pause={true}
      onPauseChange={vi.fn()}
      onContinue={vi.fn()}
    />,
  );
  expect(document.querySelector(".dl-console")).toBeNull();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/components/RunPanel.test.tsx`
Expected: FAIL with `TypeError: ... is not a function` / missing props (`lines`, `waiting`, etc.).

- [ ] **Step 3: Implement**

1. In `frontend/src/api/client.ts`, add `continueRun` to the `api` object (after `startBenchmark`, line 123):

```ts
  continueRun: (runId: number) => request<{ ok: boolean }>("/benchmarks/continue", {
    method: "POST",
    body: JSON.stringify({ run_id: runId }),
  }),
```

2. Replace `frontend/src/components/RunPanel.tsx` in full:

```tsx
import { useEffect, useRef } from "react";
import { MetricsBanks } from "./MetricsBanks";

interface Progress {
  index: number;
  total: number;
  promptTps?: number | null;
  decodeTps?: number | null;
}

interface Props {
  running: boolean;
  onRun: () => void;
  progress: Progress | null;
  canRun?: boolean;
  lines: string[];
  currentCommand: string;
  waiting: boolean;
  pause: boolean;
  onPauseChange: (paused: boolean) => void;
  onContinue: () => void;
}

export function RunPanel({
  running,
  onRun,
  progress,
  canRun = true,
  lines,
  currentCommand,
  waiting,
  pause,
  onPauseChange,
  onContinue,
}: Props) {
  const label = progress ? `config ${progress.index + 1}/${progress.total}` : "";
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  useEffect(() => {
    if (!waiting) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Enter") onContinue();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [waiting, onContinue]);

  return (
    <section className="panel">
      <span className="panel-cap">03 · RUN</span>
      <div className="row">
        <button onClick={onRun} disabled={running || !canRun}>
          RUN BENCHMARK
        </button>
        <span style={{ color: "var(--anode)", fontSize: 12 }}>{label}</span>
        <label style={{ color: "var(--anode)", fontSize: 12 }}>
          <input
            type="checkbox"
            checked={pause}
            disabled={running}
            onChange={(e) => onPauseChange(e.target.checked)}
          />
          PAUSE
        </label>
      </div>
      <MetricsBanks
        promptTps={progress?.promptTps ?? null}
        decodeTps={progress?.decodeTps ?? null}
      />
      {lines.length > 0 && (
        <div className="dl-console">
          <div className="dl-console-head">$ {currentCommand}</div>
          <div className="dl-console-body" ref={boxRef}>
            {lines.map((line, i) => (
              <div key={i}>{line || "\u00a0"}</div>
            ))}
          </div>
          {waiting && (
            <div className="dl-console-actions">
              <span style={{ color: "var(--accent)", fontSize: 12 }}>
                PRESS ENTER TO CONTINUE
              </span>
              <button className="btn-neutral" onClick={onContinue}>
                CONTINUE ▸
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `frontend/`): `npx vitest run src/components/RunPanel.test.tsx`
Expected: PASS (all tests, including the 5 new ones).

- [ ] **Step 5: Commit**

```bash
git -C /home/ruben/test add llmbench/frontend/src/api/client.ts llmbench/frontend/src/components/RunPanel.tsx llmbench/frontend/src/components/RunPanel.test.tsx
git -C /home/ruben/test commit -m "feat: run panel live console, enter-to-continue prompt, pause toggle"
```

---

## Task 5: App wiring — `pause` state, continue handler, RunPanel props

**Files:**
- Modify: `llmbench/frontend/src/App.tsx`
- Test: `llmbench/frontend/src/App.test.tsx`

- [ ] **Step 1: Write the failing tests**

1. In `frontend/src/App.test.tsx`, add `continueRun` to the mocked `api` object (after `startBenchmark`, line 14):

```ts
    continueRun: vi.fn().mockResolvedValue({ ok: true }),
```

2. Append a new test at the end of `App.test.tsx`:

```tsx
test("enter-to-continue: waiting prompt continues the run", async () => {
  const { api } = await import("./api/client");
  const { useBenchmarkProgress } = await import("./ws/useBenchmarkProgress");
  const continueSpy = vi.mocked(api.continueRun).mockResolvedValue({ ok: true });

  const view = render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);
  fireEvent.click(screen.getByText(/generate/i));
  await screen.findByText(/python serve/i);
  fireEvent.click(screen.getByText(/run benchmark/i));
  await screen.findByText(/config 1\/1/i);

  vi.mocked(useBenchmarkProgress).mockReturnValue([
    { type: "config_start", run_id: 1, index: 0, total: 1, config: { bench_command: ["python", "-m", "bench"] } },
    { type: "bench_log", run_id: 1, index: 0, kind: "line", text: "loading..." },
    { type: "config_done", run_id: 1, index: 0, result: { status: "ok", decode_tps: 42.0, prompt_processing_tps: 100.0 } },
    { type: "config_wait", run_id: 1, index: 0 },
  ]);
  view.rerender(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  expect(await screen.findByText(/press enter to continue/i)).toBeInTheDocument();
  fireEvent.keyDown(window, { key: "Enter" });
  await waitFor(() => expect(continueSpy).toHaveBeenCalledWith(1));
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/App.test.tsx`
Expected: new test FAILS (the wait prompt never appears because `App` does not pass `waiting`/`pause`/`onContinue` yet).

- [ ] **Step 3: Implement**

In `frontend/src/App.tsx`:

1. Add a `pause` state (near line 85, with the other `useState` calls):

```ts
  const [pause, setPause] = useState(true);
```

2. Add a `runId`-based continue callback (after the `onRun` callback, ~line 258):

```ts
  const onContinue = useCallback(async () => {
    if (progressState.runId === null) return;
    try {
      await api.continueRun(progressState.runId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [progressState.runId]);
```

3. In `onRun`, add `pause` to the `startBenchmark` body (inside the object passed at line 242):

```ts
      const { run_id } = await api.startBenchmark({
        repo_id: analysis.repo_id,
        pause,
        configs: configs.map((c) => ({
          server_id: analysis.detected_server,
          flags: c.flags,
          serving_command: c.serving_command,
          bench_command: c.bench_command,
        })),
      });
```

   (and add `pause` to the `onRun` dependency array at line 258).

4. Update the `<RunPanel>` element (lines 345-359) to pass the new props:

```tsx
              <RunPanel
                running={running}
                canRun={Boolean(analysis?.repo_id) && configs.length > 0}
                onRun={onRun}
                progress={
                  progressState.running || progressState.results.length > 0
                    ? {
                        index: progressState.index,
                        total: progressState.total,
                        promptTps: progressState.promptTps,
                        decodeTps: progressState.decodeTps,
                      }
                    : null
                }
                lines={progressState.lines}
                currentCommand={progressState.currentCommand}
                waiting={progressState.waiting}
                pause={pause}
                onPauseChange={setPause}
                onContinue={onContinue}
              />
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `frontend/`): `npx vitest run src/App.test.tsx`
Expected: PASS (all tests, including the new continue test).

- [ ] **Step 5: Commit**

```bash
git -C /home/ruben/test add llmbench/frontend/src/App.tsx llmbench/frontend/src/App.test.tsx
git -C /home/ruben/test commit -m "feat: wire pause toggle and enter-to-continue into run flow"
```

---

## Task 6: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend suite**

Run (from `backend/`): `source .venv/bin/activate && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 2: Run the frontend suite**

Run (from `frontend/`): `npx tsc -b && npx vitest run`
Expected: `tsc` clean, all vitest tests PASS.

- [ ] **Step 3: Run the e2e suite**

Run (from `frontend/`): `npx playwright test`
Expected: all 4 e2e tests PASS. The flow test still passes because the mock-server returns `status: "completed"` immediately (poll-based `run_sync` bypasses the pause; the mock has no WebSocket so no `config_wait` is ever delivered).

- [ ] **Step 4: Restart the app**

Run (from `llmbench/`): `./down.sh` then `./up.sh` (per AGENTS.md — never ad-hoc uvicorn/vite).
Expected: backend on :8000, frontend on :5173.

- [ ] **Step 5: Manual smoke test**

Open http://localhost:5173, analyze a model, generate configs, toggle PAUSE on and click RUN BENCHMARK. Expected: the console appears under the metric banks, streams the bench command output, shows `PRESS ENTER TO CONTINUE` after the first config, and the next config only starts after pressing Enter. Toggle PAUSE off, run again: configs run straight through while output still streams.

- [ ] **Step 6: Commit any stray state**

Run: `git -C /home/ruben/test status --short -- llmbench/`
Expected: only the committed plan/spec docs; no unexpected code changes.

---

## Self-Review

**Spec coverage:**
- `BenchmarkRunner` streams lines, returns full output → Task 1.
- `_run_job` broadcasts `bench_log` and `config_wait`, blocks when pausing → Task 2.
- `/benchmarks/continue` releases the gate; 409 without a pending pause → Task 2.
- Watchdog auto-advances with zero WS clients (grace ~3s, module constant) → Task 2.
- `pause` flag in `startBenchmark` body, default true → Tasks 2 & 5.
- Reducer accumulates `lines`, tracks `currentCommand`/`waiting` → Task 3.
- RunPanel console reuses `.dl-console`, PAUSE toggle disabled while running, Enter + CONTINUE button → Task 4.
- E2E stays green (mock has no WS) → Task 6 Step 3.

**Placeholder scan:** every step has exact code, exact commands, expected output. No TODOs.

**Type consistency:**
- `BenchmarkRunner.run(on_output=None)`; `on_output(kind, text)` async; `_collect` returns `(bytes, bytes, int)` — used consistently in Task 1 and called in Task 2 (`runner.run(on_output=on_output)`).
- `_run_job(s, run_id, configs, pause=True)`; `start_run` passes `pause`; `_await_continue(s, queue)`; `AUTO_ADVANCE_GRACE_S` constant defined before use.
- `ProgressEvent` union adds `bench_log`/`config_wait`; `ProgressState` fields `lines`/`currentCommand`/`waiting` match `INITIAL_STATE` and every reducer return.
- `RunPanel` props `lines`/`currentCommand`/`waiting`/`pause`/`onPauseChange`/`onContinue` match App usage in Task 5 and RunPanel tests in Task 4.
- `api.continueRun(runId)` matches the backend `POST /benchmarks/continue` (`{run_id}`).
