# speed-bench for Speculative-Decoding / MTP Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Benchmark llama.cpp models that qualify for speculative decoding (README proposes `--spec-type`/spec flags, or repo/GGUF name contains `MTP`) with llama.cpp's `speed-bench` server benchmark instead of `llama-bench`.

**Architecture:** A config-level `bench_tool` flag (`"speed-bench" | "llama-bench"`) is computed once in `POST /configs/generate` from the model README flags + name, stored on each config, and round-tripped by the frontend. At run time, `_run_job` branches to a new `SpeedBenchRunner` that starts `llama-server` (the user's edited serving command on a free port), waits for `/health`, runs `speed_bench.py --limit 1 --category all --bench throughput_1k --osl 128 --output <json>`, parses the JSON, and kills the server. All existing llama-bench / vLLM / sglang paths are untouched when the criteria are not met.

**Tech Stack:** Python 3.11+/FastAPI/asyncio (backend), React/TS (frontend), llama.cpp `speed-bench` (`speed_bench.py` client + `llama-server`), pytest/pytest-asyncio, vitest.

---

## File Structure

- `backend/app/servers.py` — add detection + speed-bench/server command builders (no change to `build_bench_command`).
- `backend/app/benchmark.py` — add `parse_speed_bench_json`, `SpeedBenchRunner`, helpers; extract shared `_collect_proc`.
- `backend/app/config.py` — add `speed_bench_script`, `speed_bench_timeout_s`, `speed_bench_osl`.
- `backend/app/api.py` — compute `bench_tool`, rebuild server+client commands, 422 on unavailable, branch runner.
- `backend/pyproject.toml` — optional `[speed-bench]` extra.
- `backend/tests/test_servers.py`, `backend/tests/test_benchmark.py`, `backend/tests/test_api.py` — tests.
- `frontend/src/api/client.ts`, `frontend/src/components/ConfigBank.tsx`, `frontend/src/App.tsx`, `frontend/e2e/mock-server.ts` — round-trip `bench_tool` + badge.
- `frontend/src/components/ConfigBank.test.tsx`, `frontend/src/App.test.tsx` — frontend tests.
- `README.md` — feature bullet.

---

### Task 1: Detection + command builders (`servers.py`)

**Files:**
- Modify: `backend/app/servers.py`
- Test: `backend/tests/test_servers.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_servers.py`:

```python
import sys

from app.servers import (SERVERS, detect_binaries, build_bench_command, resolve_bench_binary, README_FLAG_MAP)
from app.servers import (parse_serving_command, model_ref_from_flags, is_spec_decoding_model,
                         resolve_serving_binary, resolve_speed_bench_script,
                         build_server_command, build_speed_bench_command)


def test_is_spec_decoding_model_mtp_in_repo():
    assert is_spec_decoding_model("GazTrab/Qwen3.6-27B-MTP-UD-IQ3_XXS-GGUF") is True


def test_is_spec_decoding_model_mtp_in_gguf():
    assert is_spec_decoding_model("org/model", gguf_filename="Qwen3.6-27B-MTP-UD-IQ3_XXS.gguf") is True


def test_is_spec_decoding_model_mtp_case_insensitive():
    assert is_spec_decoding_model("org/qwen3-mtp-model") is True


def test_is_spec_decoding_model_readme_spec_type():
    assert is_spec_decoding_model("org/model", readme_flags={"--spec-type": "draft-mtp"}) is True


def test_is_spec_decoding_model_readme_draft_flag():
    assert is_spec_decoding_model("org/model", readme_flags={"-md": "draft.gguf"}) is True


def test_is_spec_decoding_model_false():
    assert is_spec_decoding_model("org/model", gguf_filename="model.Q4_K_M.gguf",
                                  readme_flags={"--ctx-size": "4096"}) is False
    assert is_spec_decoding_model("org/model", readme_flags={}) is False


def test_resolve_serving_binary_uses_bin_dir(tmp_path):
    fake = tmp_path / "llama-server"
    fake.write_text("#!/bin/sh\n")
    assert resolve_serving_binary("llama.cpp", bin_dir=str(tmp_path)) == str(fake)


def test_resolve_speed_bench_script_configured_wins(tmp_path):
    configured = tmp_path / "speed_bench.py"
    configured.write_text("x")
    other = tmp_path / "other.py"
    other.write_text("x")
    assert resolve_speed_bench_script(configured=configured) == str(configured)


def test_resolve_speed_bench_script_auto_discovers(tmp_path):
    bin_dir = tmp_path / "build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    script = tmp_path / "tools" / "server" / "bench" / "speed-bench" / "speed_bench.py"
    script.parent.mkdir(parents=True)
    script.write_text("x")
    assert resolve_speed_bench_script(bin_dir=str(bin_dir)) == str(script)


def test_resolve_speed_bench_script_missing(tmp_path):
    bin_dir = tmp_path / "build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    assert resolve_speed_bench_script(bin_dir=str(bin_dir)) is None


def test_build_speed_bench_command_shape(tmp_path):
    script = str(tmp_path / "speed_bench.py")
    cmd = build_speed_bench_command(script, osl=128, url="localhost:8080", output="/tmp/out.json")
    assert cmd[0] == sys.executable
    assert cmd[1] == script
    assert cmd[cmd.index("--url") + 1] == "localhost:8080"
    assert cmd[cmd.index("--limit") + 1] == "1"
    assert cmd[cmd.index("--category") + 1] == "all"
    assert cmd[cmd.index("--bench") + 1] == "throughput_1k"
    assert cmd[cmd.index("--osl") + 1] == "128"
    assert cmd[cmd.index("--output") + 1] == "/tmp/out.json"


def test_build_server_command_swaps_binary_and_strips_port(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    tokens = build_server_command(
        "llama-server -m /models/x.gguf --spec-type draft-mtp --port 9999 --host 0.0.0.0 -p 4",
        bin_dir=str(bin_dir))
    assert tokens[0] == str(bin_dir / "llama-server")
    assert "--port" not in tokens and "9999" not in tokens
    assert "--host" not in tokens and "0.0.0.0" not in tokens
    assert "-p" in tokens and "4" in tokens
    assert tokens[tokens.index("--spec-type") + 1] == "draft-mtp"
```

Also update `test_detect_missing` to include the new readiness key:

```python
def test_detect_missing(monkeypatch):
    monkeypatch.setattr("app.servers.shutil.which", lambda name: None)
    assert detect_binaries() == {"llama.cpp": False, "vllm": False, "sglang": False, "speed-bench": False}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_servers.py -q`
Expected: FAIL — `ImportError: cannot import name 'is_spec_decoding_model'` (and `test_detect_missing` fails on the extra key).

- [ ] **Step 3: Implement**

In `backend/app/servers.py` add `import sys` at the top. Add:

```python
_SPEC_DECODING_FLAGS = {
    "--spec-type", "-md", "--model-draft", "--model-mtp", "-mtmd",
    "--draft-max", "--draft-min", "--draft-p-min",
    "--spec-draft-n-max", "--spec-draft-n-min", "--spec-raw-logits",
    "--spec-heuristics", "--spec-heuristic-acc", "--spec-heuristic-min-tokens",
}


def is_spec_decoding_model(repo_id: str, gguf_filename: str | None = None,
                           readme_flags: dict[str, str] | None = None) -> bool:
    """True when a model should be benchmarked with speed-bench: the repo/GGUF
    name contains MTP, or the README proposes a speculative-decoding flag."""
    if "mtp" in f"{repo_id} {gguf_filename or ''}".lower():
        return True
    return any(flag in _SPEC_DECODING_FLAGS for flag in (readme_flags or {}))


def resolve_serving_binary(server_id: str, bin_dir: str | None = None) -> str | None:
    meta = SERVERS[server_id]
    if server_id == "llama.cpp" and bin_dir:
        candidate = Path(bin_dir) / "llama-server"
        if candidate.is_file():
            return str(candidate)
    for b in meta["serving_binaries"]:
        found = shutil.which(b)
        if found:
            return found
    return None


def resolve_speed_bench_script(bin_dir: str | None = None,
                               configured: str | Path | None = None) -> str | None:
    """Locate speed_bench.py. Honors an explicitly configured path, otherwise
    auto-discovers it in the llama.cpp source tree that contains the resolved
    llama-server binary."""
    if configured:
        p = Path(configured)
        if p.is_file():
            return str(p)
    server = resolve_serving_binary("llama.cpp", bin_dir)
    if not server:
        return None
    bin_path = Path(server).parent
    for parent in [bin_path, *bin_path.parents[:3]]:
        candidate = parent / "tools" / "server" / "bench" / "speed-bench" / "speed_bench.py"
        if candidate.is_file():
            return str(candidate)
    return None


def build_speed_bench_command(script: str, osl: int = 128, url: str = "localhost:8080",
                              output: str = "speed-bench.json") -> list[str]:
    return [
        sys.executable, script,
        "--url", url,
        "--bench", "throughput_1k",
        "--category", "all",
        "--limit", "1",
        "--osl", str(osl),
        "--output", output,
    ]


def build_server_command(serving_command: str, bin_dir: str | None = None) -> list[str]:
    """Turn the editable llama-server serving command into an executable token
    list: swap in the resolved binary and drop --port/--host (the runner injects
    its own). -p (--parallel) is left alone."""
    import shlex
    tokens = shlex.split(serving_command)
    if not tokens:
        return []
    resolved = resolve_serving_binary("llama.cpp", bin_dir)
    if resolved:
        tokens[0] = resolved
    out: list[str] = []
    skip_next = False
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if tok in ("--port", "--host"):
            skip_next = True
            continue
        out.append(tok)
    return out
```

Update `detect_binaries`:

```python
def detect_binaries(bin_dir: str | None = None) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for server_id in SERVERS:
        out[server_id] = resolve_bench_binary(server_id, bin_dir) is not None
    out["speed-bench"] = resolve_speed_bench_script(bin_dir) is not None
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_servers.py -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/servers.py backend/tests/test_servers.py
git commit -m "feat: detect speed-bench models and build speed-bench/server commands"
```

---

### Task 2: Parser + `SpeedBenchRunner` (`benchmark.py`)

**Files:**
- Modify: `backend/app/benchmark.py`
- Test: `backend/tests/test_benchmark.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_benchmark.py`:

```python
import json
import sys

import app.benchmark as bench_mod
from app.benchmark import parse_speed_bench_json, SpeedBenchRunner

SPEED_JSON = json.dumps({
    "summary": [
        {"category": "high_entropy", "requests": 1, "avg_prompt_t_s": 900.0, "avg_pred_t_s": 50.0},
        {"category": "overall", "requests": 3, "avg_prompt_t_s": 1000.0, "avg_pred_t_s": 88.8},
    ],
})


def test_parse_speed_bench_json_overall():
    r = parse_speed_bench_json(SPEED_JSON)
    assert r["prompt_processing_tps"] == 1000.0
    assert r["decode_tps"] == 88.8


def test_parse_speed_bench_json_no_overall():
    r = parse_speed_bench_json(json.dumps({"summary": [{"category": "high_entropy"}]}))
    assert r["prompt_processing_tps"] is None
    assert r["decode_tps"] is None


def test_parse_speed_bench_json_invalid():
    r = parse_speed_bench_json("not json")
    assert r["prompt_processing_tps"] is None
    assert r["decode_tps"] is None


def test_substitute_speed_bench_command():
    cmd = bench_mod._substitute_speed_bench_command(
        ["python", "s.py", "--url", "localhost:8080", "--limit", "1", "--output", "out.json"],
        port=9999, output_path="/tmp/real.json")
    assert cmd[cmd.index("--url") + 1] == "localhost:9999"
    assert cmd[cmd.index("--output") + 1] == "/tmp/real.json"
    assert cmd[cmd.index("--limit") + 1] == "1"


def test_free_port_returns_int():
    assert isinstance(bench_mod._free_port(), int)


class _FakeTempfile:
    def __init__(self, path):
        self._path = str(path)

    def mktemp(self, **kwargs):
        return self._path


async def test_speed_bench_runner_ok(monkeypatch, tmp_path):
    seen = []
    procs = []
    spawned = []

    def new_proc(out=b"", rc=0):
        p = FakeProc(out, rc=rc)
        procs.append(p)
        return p

    async def fake_create(*a, **k):
        spawned.append(a)
        return new_proc(out=b"")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    monkeypatch.setattr(bench_mod, "_free_port", lambda: 9123)
    monkeypatch.setattr(bench_mod, "_wait_health", lambda *a, **k: True)
    out_path = tmp_path / "out.json"
    out_path.write_text(SPEED_JSON)
    monkeypatch.setattr(bench_mod, "tempfile", _FakeTempfile(out_path))

    runner = SpeedBenchRunner(
        server_command=["llama-server", "-m", "/models/x.gguf", "--spec-type", "draft-mtp"],
        bench_command=["python", "speed_bench.py", "--url", "localhost:8080", "--limit", "1",
                       "--category", "all", "--bench", "throughput_1k", "--output", "x.json"],
        timeout_s=60, startup_timeout_s=60, output_dir=tmp_path)

    async def on_output(kind, text):
        seen.append((kind, text))

    result = await runner.run(on_output=on_output)
    assert result["status"] == "ok"
    assert result["decode_tps"] == 88.8
    assert result["prompt_processing_tps"] == 1000.0
    assert len(spawned) == 2
    assert spawned[0][0] == "llama-server"
    assert "--port" in spawned[0] and "9123" in spawned[0]
    assert spawned[1][0] == "python"
    client_cmd = spawned[1]
    assert client_cmd[client_cmd.index("--url") + 1] == "localhost:9123"
    assert client_cmd[client_cmd.index("--output") + 1] == str(out_path)
    assert procs[0].killed is True


async def test_speed_bench_runner_server_not_ready(monkeypatch, tmp_path):
    async def fake_create(*a, **k):
        return FakeProc(b"")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    monkeypatch.setattr(bench_mod, "_free_port", lambda: 9123)
    monkeypatch.setattr(bench_mod, "_wait_health", lambda *a, **k: False)

    runner = SpeedBenchRunner(
        server_command=["llama-server", "-m", "/models/x.gguf"],
        bench_command=["python", "speed_bench.py", "--url", "localhost:8080"],
        timeout_s=60, startup_timeout_s=5, output_dir=tmp_path)
    result = await runner.run()
    assert result["status"] == "failed"
    assert "not become ready" in result["output"]


async def test_speed_bench_runner_client_fails(monkeypatch, tmp_path):
    async def fake_create(*a, **k):
        return FakeProc(b"boom", rc=1)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    monkeypatch.setattr(bench_mod, "_free_port", lambda: 9123)
    monkeypatch.setattr(bench_mod, "_wait_health", lambda *a, **k: True)

    runner = SpeedBenchRunner(
        server_command=["llama-server", "-m", "/models/x.gguf"],
        bench_command=["python", "speed_bench.py", "--url", "localhost:8080"],
        timeout_s=60, startup_timeout_s=5, output_dir=tmp_path)
    result = await runner.run()
    assert result["status"] == "failed"
```

Note: `FakeProc` in `test_benchmark.py` is defined near line 118 with signature `__init__(self, out, err=b"", rc=0)`, so `FakeProc(out, rc=1)` works.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_benchmark.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_speed_bench_json'`.

- [ ] **Step 3: Implement**

In `backend/app/benchmark.py`, add imports at the top (after the existing ones):

```python
import socket
import tempfile
from pathlib import Path
```

Add a module-level `_collect_proc` helper (extracted from `BenchmarkRunner._collect`, behavior identical):

```python
async def _collect_proc(proc, on_output, aborted: asyncio.Event | None = None):
    out_tty = TtyStream()
    err_tty = TtyStream()
    out_parts: list[bytes] = []
    err_parts: list[bytes] = []

    async def pump(stream, tty, parts):
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            if aborted is not None and aborted.is_set():
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

Replace the body of `BenchmarkRunner._collect` with:

```python
    async def _collect(self, proc, on_output) -> tuple[bytes, bytes, int]:
        return await _collect_proc(proc, on_output, self._aborted)
```

Add the parser, helpers, and runner:

```python
def parse_speed_bench_json(text: str) -> dict:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"prompt_processing_tps": None, "decode_tps": None}
    summary = data.get("summary") or []
    overall = next((r for r in summary if r.get("category") == "overall"), None)
    if not overall:
        return {"prompt_processing_tps": None, "decode_tps": None}
    return {
        "prompt_processing_tps": overall.get("avg_prompt_t_s"),
        "decode_tps": overall.get("avg_pred_t_s"),
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _substitute_speed_bench_command(cmd: list[str], port: int, output_path: str) -> list[str]:
    out: list[str] = []
    skip_next = False
    for tok in cmd:
        if skip_next:
            skip_next = False
            continue
        if tok == "--url":
            out += [tok, f"localhost:{port}"]
            skip_next = True
        elif tok == "--output":
            out += [tok, output_path]
            skip_next = True
        else:
            out.append(tok)
    return out


async def _wait_health(port: int, timeout_s: float) -> bool:
    import httpx
    url = f"http://127.0.0.1:{port}/health"
    deadline = asyncio.get_event_loop().time() + timeout_s
    async with httpx.AsyncClient(timeout=2.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return False
```

Add the `SpeedBenchRunner` class after `BenchmarkRunner`:

```python
class SpeedBenchRunner:
    """Benchmark a llama.cpp model via speed-bench: start llama-server, wait for
    /health, run speed_bench.py against it, parse the --output JSON, and kill the
    server. speed-bench cannot run as a standalone CLI like llama-bench."""

    def __init__(self, server_command: list[str], bench_command: list[str],
                 timeout_s: float, startup_timeout_s: float, output_dir: str | Path):
        self.server_command = list(server_command)
        self.bench_command = list(bench_command)
        self.timeout_s = timeout_s
        self.startup_timeout_s = startup_timeout_s
        self.output_dir = Path(output_dir)
        self._aborted = asyncio.Event()
        self._procs: list[asyncio.subprocess.Process] = []

    def abort(self) -> None:
        self._aborted.set()
        for proc in self._procs:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

    async def _pump(self, proc, parts: list[bytes], on_output) -> int:
        out_tty = TtyStream()
        err_tty = TtyStream()

        async def pump(stream, tty):
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

        await asyncio.gather(pump(proc.stdout, out_tty), pump(proc.stderr, err_tty))
        rc = proc.returncode
        if rc is None:
            rc = await proc.wait()
        return rc

    async def run(self, on_output=None) -> dict:
        start = asyncio.get_event_loop().time()
        if not self.server_command or not self.bench_command:
            return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                    "duration_s": 0.0,
                    "output": "speed-bench is not configured: missing server or client command"}
        port = _free_port()
        output_path = tempfile.mktemp(prefix="speed-bench-", suffix=".json", dir=str(self.output_dir))
        server_cmd = list(self.server_command) + ["--port", str(port), "--host", "127.0.0.1"]
        client_cmd = _substitute_speed_bench_command(self.bench_command, port, output_path)

        server_proc = None
        client_proc = None
        server_pump: asyncio.Task | None = None
        parts: list[bytes] = []
        try:
            server_proc = await asyncio.create_subprocess_exec(
                *server_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            self._procs.append(server_proc)
            server_pump = asyncio.create_task(self._pump(server_proc, parts, on_output))

            ready = await _wait_health(port, self.startup_timeout_s)
            if self._aborted.is_set():
                return {"status": "aborted", "prompt_processing_tps": None, "decode_tps": None,
                        "duration_s": asyncio.get_event_loop().time() - start,
                        "output": _decode_parts(parts)}
            if not ready:
                return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                        "duration_s": asyncio.get_event_loop().time() - start,
                        "output": f"llama-server did not become ready on port {port} "
                                  f"within {self.startup_timeout_s}s\n{_decode_parts(parts)}"}

            client_proc = await asyncio.create_subprocess_exec(
                *client_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            self._procs.append(client_proc)
            try:
                await asyncio.wait_for(self._pump(client_proc, parts, on_output), timeout=self.timeout_s)
                rc = client_proc.returncode if client_proc.returncode is not None else 0
            except asyncio.TimeoutError:
                client_proc.kill()
                await client_proc.wait()
                rc = -1
            except Exception:
                client_proc.kill()
                await client_proc.wait()
                raise
            duration = asyncio.get_event_loop().time() - start
            output = _decode_parts(parts)
            if self._aborted.is_set():
                return {"status": "aborted", "prompt_processing_tps": None, "decode_tps": None,
                        "duration_s": duration, "output": output}
            if rc != 0:
                return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                        "duration_s": duration, "output": output}
            try:
                with open(output_path, encoding="utf-8") as fh:
                    parsed = parse_speed_bench_json(fh.read())
            except OSError:
                parsed = {"prompt_processing_tps": None, "decode_tps": None}
            if parsed["decode_tps"] is None:
                return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                        "duration_s": duration, "output": output}
            return {"status": "ok", **parsed, "duration_s": duration, "output": output}
        finally:
            for proc in (client_proc, server_proc):
                if proc is not None and proc.returncode is None:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
            if server_pump is not None:
                server_pump.cancel()
                try:
                    await server_pump
                except (asyncio.CancelledError, Exception):
                    pass
            self._procs.clear()
```

Add the small helper `_decode_parts` at module level:

```python
def _decode_parts(parts: list[bytes]) -> str:
    return "\n".join(p.decode(errors="replace") for p in parts if p)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_benchmark.py -q`
Expected: PASS (all tests, including the pre-existing runner tests which exercise the `_collect_proc` refactor).

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmark.py backend/tests/test_benchmark.py
git commit -m "feat: add speed-bench parser and server-based SpeedBenchRunner"
```

---

### Task 3: Settings (`config.py`)

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_config.py`:

```python
def test_speed_bench_settings_defaults():
    s = Settings()
    assert s.speed_bench_script is None
    assert s.speed_bench_timeout_s == 300
    assert s.speed_bench_osl == 128


def test_speed_bench_settings_env(monkeypatch):
    monkeypatch.setenv("LLMBENCH_SPEED_BENCH_TIMEOUT_S", "450")
    monkeypatch.setenv("LLMBENCH_SPEED_BENCH_OSL", "256")
    s = Settings()
    assert s.speed_bench_timeout_s == 450
    assert s.speed_bench_osl == 256
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_config.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'speed_bench_script'`.

- [ ] **Step 3: Implement**

In `backend/app/config.py`, add three fields to `Settings` (after `llama_cpp_bin_dir`):

```python
    speed_bench_script: Path | None = None
    speed_bench_timeout_s: int = 300
    speed_bench_osl: int = 128
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat: add speed-bench settings"
```

---

### Task 4: API wiring (`api.py`)

**Files:**
- Modify: `backend/app/api.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Update `test_servers_endpoint` in `backend/tests/test_api.py`:

```python
def test_servers_endpoint(client):
    r = client.get("/api/servers")
    assert r.status_code == 200
    assert set(r.json()["readiness"]) == {"llama.cpp", "vllm", "sglang", "speed-bench"}
```

Add the following tests to `backend/tests/test_api.py`:

```python
import sys


def test_generate_configs_llama_spec_readme_uses_speed_bench(tmp_path):
    bin_dir = tmp_path / "llama" / "build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    (bin_dir / "llama-bench").write_text("#!/bin/sh\n")
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
            "repo_id": "org/Qwen3-MTP",
            "n": 1,
            "readme_flags": {"--spec-type": "draft-mtp"},
        })
    assert r.status_code == 200
    cfg = r.json()["configs"][0]
    assert cfg["bench_tool"] == "speed-bench"
    cmd = cfg["bench_command"]
    assert cmd[0] == sys.executable
    assert cmd[1] == str(script)
    assert cmd[cmd.index("--limit") + 1] == "1"
    assert cmd[cmd.index("--category") + 1] == "all"
    assert cmd[cmd.index("--bench") + 1] == "throughput_1k"
    assert "draft-mtp" in cfg["serving_command"]


def test_generate_configs_llama_non_spec_uses_llama_bench(client):
    r = client.post("/api/configs/generate", json={
        "server_id": "llama.cpp",
        "repo_id": "org/plain-model",
        "n": 1,
        "readme_flags": {},
    })
    assert r.status_code == 200
    cfg = r.json()["configs"][0]
    assert cfg["bench_tool"] == "llama-bench"
    assert cfg["bench_command"][0] == "llama-bench"


def test_rebuild_bench_command_speed_bench(tmp_path):
    from app.api import _rebuild_bench_command, AppState
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    script = tmp_path / "speed_bench.py"
    script.write_text("x")
    settings = Settings(data_dir=tmp_path / "data", gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf",
                        workload_file=tmp_path / "prompts.jsonl",
                        llama_cpp_bin_dir=bin_dir, speed_bench_script=script)
    (tmp_path / "prompts.jsonl").write_text("x\n")
    s = AppState(settings)
    cfg = {
        "server_id": "llama.cpp",
        "bench_tool": "speed-bench",
        "serving_command": "llama-server -m /models/x.gguf --spec-type draft-mtp --port 9999 --host 0.0.0.0",
        "flags": {},
        "bench_command": [],
    }
    _rebuild_bench_command(s, cfg, "org/model")
    assert cfg["server_command"][0] == str(bin_dir / "llama-server")
    assert "--port" not in cfg["server_command"]
    assert "--host" not in cfg["server_command"]
    assert "--spec-type" in cfg["server_command"]
    assert cfg["bench_command"][0] == sys.executable
    assert cfg["bench_command"][1] == str(script)
    assert "bench_error" not in cfg


def test_start_run_speed_bench_unavailable_rejected(client, monkeypatch):
    monkeypatch.setattr("app.api.resolve_speed_bench_script", lambda *a, **k: None)
    config = {
        "server_id": "llama.cpp",
        "bench_tool": "speed-bench",
        "serving_command": "llama-server -m /models/x.gguf --spec-type draft-mtp",
        "flags": {},
        "bench_command": [],
    }
    r = client.post("/api/benchmarks", json={
        "repo_id": "org/model",
        "configs": [config],
        "pause": False,
    })
    assert r.status_code == 422
    assert "speed-bench" in r.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api.py -q`
Expected: FAIL — `test_servers_endpoint` (extra readiness key) and the four new tests (features not implemented).

- [ ] **Step 3: Implement**

In `backend/app/api.py`:

Update the import from `app.servers`:

```python
from app.servers import (build_bench_command, build_server_command, build_speed_bench_command,
                         detect_binaries, is_spec_decoding_model, model_ref_from_flags,
                         parse_serving_command, resolve_speed_bench_script)
```

Update the `AppState.runner` type hint:

```python
        self.runner: benchmark_mod.BenchmarkRunner | benchmark_mod.SpeedBenchRunner | None = None
```

In `POST /configs/generate`, replace the `for cfg in configs:` block body to compute `bench_tool` and build the speed-bench command. After the `bin_dir = ...` line, insert:

```python
    uses_speed_bench = (
        server_id == "llama.cpp"
        and is_spec_decoding_model(repo_id, gguf_filename, payload.get("readme_flags", {}))
    )
```

Then in the loop, replace the `cfg["bench_command"] = build_bench_command(...)` block with:

```python
        cfg["bench_tool"] = "speed-bench" if uses_speed_bench else "llama-bench"
        if uses_speed_bench:
            script = resolve_speed_bench_script(bin_dir, configured=s.settings.speed_bench_script)
            if script:
                cfg["bench_command"] = build_speed_bench_command(
                    script, osl=s.settings.speed_bench_osl,
                    output=str(s.settings.data_dir / "speed-bench.json"))
            else:
                cfg["bench_command"] = []
                cfg["bench_error"] = (
                    "speed-bench is not available for this model: could not locate speed_bench.py "
                    "next to llama-server. Set LLMBENCH_SPEED_BENCH_SCRIPT or install llama.cpp "
                    "with the speed-bench tool.")
        else:
            cfg["bench_command"] = build_bench_command(
                server_id, bench_ref, cfg["flags"],
                workload=str(s.settings.workload_file),
                timeout_s=s.settings.benchmark_timeout_s,
                bin_dir=bin_dir,
                gguf_filename=gguf_filename,
            )
```

Replace `_rebuild_bench_command` with a version that branches on `bench_tool`:

```python
def _rebuild_bench_command(s: AppState, cfg: dict, repo_id: str) -> None:
    """Re-derive the executed commands from the user's edited serving command so
    edits to the config bank actually take effect at run time. speed-bench runs
    need both a server command (llama-server) and a client command
    (speed_bench.py); llama-bench/vllm/sglang keep the single bench command."""
    if not cfg.get("server_id"):
        return
    if cfg.get("bench_tool") == "speed-bench":
        bin_dir = str(s.settings.llama_cpp_bin_dir) if s.settings.llama_cpp_bin_dir else None
        cfg["server_command"] = build_server_command(cfg.get("serving_command", ""), bin_dir)
        script = resolve_speed_bench_script(bin_dir, configured=s.settings.speed_bench_script)
        if not script:
            cfg["bench_command"] = []
            cfg["bench_error"] = (
                "speed-bench is not available: could not locate speed_bench.py next to llama-server. "
                "Set LLMBENCH_SPEED_BENCH_SCRIPT or install llama.cpp with the speed-bench tool.")
            return
        cfg["bench_command"] = build_speed_bench_command(
            script, osl=s.settings.speed_bench_osl,
            output=str(s.settings.data_dir / "speed-bench.json"))
        return
    flags = parse_serving_command(cfg.get("server_id", ""), cfg.get("serving_command", ""))
    if not flags:
        flags = cfg.get("flags") or {}
    if not flags:
        return
    model_ref, gguf_filename = model_ref_from_flags(cfg["server_id"], flags, repo_id)
    cfg["bench_command"] = build_bench_command(
        cfg["server_id"], model_ref, flags,
        workload=str(s.settings.workload_file),
        timeout_s=s.settings.benchmark_timeout_s,
        bin_dir=str(s.settings.llama_cpp_bin_dir) if s.settings.llama_cpp_bin_dir else None,
        gguf_filename=gguf_filename,
    )
```

In `start_run`, reject configs that failed to rebuild:

```python
    for cfg in configs:
        _rebuild_bench_command(s, cfg, repo_id)
        if cfg.get("bench_error"):
            raise HTTPException(422, cfg["bench_error"])
```

In `_run_job`, replace the runner construction block:

```python
                    if cfg.get("bench_tool") == "speed-bench":
                        runner = benchmark_mod.SpeedBenchRunner(
                            server_command=cfg.get("server_command", []),
                            bench_command=cfg.get("bench_command", []),
                            timeout_s=s.settings.speed_bench_timeout_s,
                            startup_timeout_s=s.settings.speed_bench_timeout_s,
                            output_dir=s.settings.data_dir,
                        )
                    else:
                        runner = benchmark_mod.BenchmarkRunner(
                            server_id=cfg["server_id"],
                            bench_command=cfg["bench_command"],
                            timeout_s=s.settings.benchmark_timeout_s,
                        )
                    s.runner = runner
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_api.py -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: route qualifying llama.cpp configs through speed-bench at run time"
```

---

### Task 5: Optional `[speed-bench]` extra (`pyproject.toml`)

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Modify**

In `backend/pyproject.toml`, replace the `dev` optional-dependencies block with:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-httpx>=0.30",
]
speed-bench = [
    "datasets>=2.19",
    "requests>=2.31",
    "tqdm>=4.66",
]
```

- [ ] **Step 2: Verify no import breakage**

Run: `cd backend && python -c "from app import api, benchmark, servers; print('ok')"`
Expected: `ok` (the extra is not imported by the app; `datasets`/`tqdm` are only used by the spawned `speed_bench.py`).

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml
git commit -m "chore: add optional speed-bench deps extra"
```

---

### Task 6: Frontend round-trip + badge

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/ConfigBank.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/e2e/mock-server.ts`
- Test: `frontend/src/components/ConfigBank.test.tsx`, `frontend/src/App.test.tsx`

- [ ] **Step 1: Write the failing tests**

In `frontend/src/components/ConfigBank.test.tsx`, add a test (adjust to match the file's existing render helpers):

```tsx
import { ConfigBank } from "./ConfigBank";

// add alongside existing tests
test("renders a SPEED-BENCH badge for speed-bench configs", () => {
  const configs = [
    { flags: {}, serving_command: "llama-server --spec-type draft-mtp", bench_tool: "speed-bench" },
    { flags: {}, serving_command: "llama-server -m x", bench_tool: "llama-bench" },
  ];
  const { container } = render(<ConfigBank n={2} onNChange={() => {}} onGenerate={() => {}} configs={configs} />);
  expect(container.textContent).toContain("SPEED-BENCH");
});
```

In `frontend/src/App.test.tsx`, add a test asserting `bench_tool` is included in the `/benchmarks` payload (mirror the existing run-payload test helper used in that file):

```tsx
test("run payload round-trips bench_tool", async () => {
  // render App with an analysis + configs that include bench_tool, click run,
  // and assert the request body sent to /api/benchmarks contains bench_tool.
});
```

Follow the exact patterns used by existing `App.test.tsx` tests (mocked `api.startBenchmark`) to assert the outgoing body.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/ConfigBank.test.tsx src/App.test.tsx`
Expected: FAIL — `bench_tool` not rendered / not in payload.

- [ ] **Step 3: Implement**

In `frontend/src/api/client.ts`, add `bench_tool?: string;` to the config item in the `generateConfigs` return type:

```ts
      configs: Array<{
        flags: Record<string, string>;
        serving_command: string;
        bench_command: string[];
        bench_tool?: string;
        fit: ConfigFit | null;
      }>;
```

In `frontend/src/components/ConfigBank.tsx`, add to `ConfigRow` and render the badge:

```tsx
export interface ConfigRow {
  flags: Record<string, string>;
  serving_command: string;
  bench_command?: string[];
  bench_tool?: string;
  fit?: ConfigFit | null;
}
```

And inside the config row, after the textarea:

```tsx
          {cfg.bench_tool === "speed-bench" && (
            <span
              style={{
                fontSize: 10,
                letterSpacing: 1,
                color: "var(--accent)",
                border: "1px solid var(--hairline)",
                padding: "2px 6px",
                whiteSpace: "nowrap",
              }}
            >
              SPEED-BENCH
            </span>
          )}
```

In `frontend/src/App.tsx`, in `onRun`, add `bench_tool` to the mapped config:

```tsx
        configs: configs.map((c) => ({
          server_id: analysis.detected_server,
          flags: c.flags,
          serving_command: c.serving_command,
          bench_command: c.bench_command,
          bench_tool: c.bench_tool,
        })),
```

In `frontend/e2e/mock-server.ts`, add `bench_tool: "llama-bench"` to the canned generate config:

```ts
      configs: [{
        flags: { "--max-model-len": "8192" },
        serving_command: "vllm serve org/model --max-model-len 8192",
        bench_tool: "llama-bench",
        fit: { stage: "gpu", label: "FITS VRAM", fits_vram: true, offloaded: false, needed_gb: 3.8, kv_gb: 4.3, weights_gb: 4 },
      }],
```

- [ ] **Step 4: Run tests + typecheck to verify**

Run: `cd frontend && npx vitest run && npx tsc -b`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/components/ConfigBank.tsx frontend/src/App.tsx frontend/e2e/mock-server.ts frontend/src/components/ConfigBank.test.tsx frontend/src/App.test.tsx
git commit -m "feat: round-trip bench_tool and show speed-bench badge"
```

---

### Task 7: Docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Modify**

In `README.md`, add a bullet to the Features list (after the serial-benchmarks bullet):

```markdown
- llama.cpp models that propose speculative decoding (README `--spec-type` / spec flags) or carry `MTP` in the name are benchmarked with `speed-bench` (llama-server + `speed_bench.py`) instead of `llama-bench`, so MTP configs are actually measured.
```

Also add an operational note in the Requirements section:

```markdown
- To benchmark speculative-decoding / MTP llama.cpp models, the llama.cpp source tree must include `tools/server/bench/speed-bench/speed_bench.py` (auto-discovered next to `llama-server`, or point `LLMBENCH_SPEED_BENCH_SCRIPT` at it) and its Python deps installed (`cd backend && pip install -e '.[speed-bench]'`). The speed-bench client always runs with `--limit 1 --category all --bench throughput_1k`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document speed-bench benchmarking for spec-decoding models"
```

---

### Task 8: Full verification

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all backend tests pass.

- [ ] **Step 2: Run the frontend checks**

Run: `cd frontend && npx tsc -b && npx vitest run`
Expected: typecheck clean, all vitest tests pass.

- [ ] **Step 3: Run the Playwright e2e suite**

Run: `cd frontend && npx playwright test`
Expected: e2e flow passes against the mock server.

- [ ] **Step 4: Manual smoke of detection + command generation**

Run: `cd backend && python -c "from app.servers import is_spec_decoding_model; print(is_spec_decoding_model('org/Qwen3-MTP'), is_spec_decoding_model('org/plain'))"`
Expected: `True False`
