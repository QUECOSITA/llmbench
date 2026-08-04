# Download Console, Cancel, and Interactive Cache Prune — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make downloads in the MODEL INPUT (01) panel stream live terminal-like output, add a CANCEL action, and after a cancel automatically run `hf cache prune` whose `y/N` confirmation is answered interactively in the UI.

**Architecture:** Backend runs `hf download` attached to a pseudo-terminal (so tqdm progress bars render), normalizes the raw pty byte stream through a pure `TtyStream` class into "line" / "progress" events, and broadcasts them over the existing WebSocket. A new `POST /api/models/download/cancel` kills the process; the job then spawns `hf cache prune --format human` with piped stdin, emits a `prune_prompt` event when it sees `Proceed?`, and `POST /api/models/download/prune-answer` feeds the user's `y`/`n` into the process stdin. Frontend gains a `downloadReducer` plus a `DownloadConsole` component rendered in section 01 with a CANCEL button and a `Proceed? [y/N]` prompt.

**Tech Stack:** Python/FastAPI/asyncio (backend, pty via `os.openpty`, `asyncio.create_subprocess_exec`); Vite/React 18/TypeScript/vitest/@testing-library/react/Playwright (frontend). Tests: pytest on backend; vitest + RTL on frontend.

**Spec:** `docs/superpowers/specs/2026-08-03-download-console-cancel-prune-design.md`

---

## File Structure

**Backend (create):**
- `backend/app/tty_stream.py` — `TtyStream` pure normalizer (ANSI strip, `\r`/`\n` handling).
- `backend/tests/test_tty_stream.py` — `TtyStream` unit tests.

**Backend (modify):**
- `backend/app/api.py` — command builders, pty spawn/read helpers, `_download_job` rewrite, `_prune_job`, cancel + prune-answer endpoints, AppState fields.
- `backend/tests/test_api.py` — update download tests; new cancel/prune tests.

**Frontend (create):**
- `frontend/src/ws/downloadReducer.ts` — `DownloadStatus`, `downloadReducer`, `downloadActive`, `key`.
- `frontend/src/ws/downloadReducer.test.ts`
- `frontend/src/components/DownloadConsole.tsx`
- `frontend/src/components/DownloadConsole.test.tsx`

**Frontend (modify):**
- `frontend/src/ws/useDownloadProgress.ts` — extend `DownloadEvent` type.
- `frontend/src/api/client.ts` — add `cancelDownload`, `answerPrune`.
- `frontend/src/App.tsx` — reducer wiring, `DownloadConsole` in section 01, cancel/prune handlers.
- `frontend/src/App.test.tsx` — update download test; add cancel-flow test; extend `api` mock.
- `frontend/src/styles/app.css` — console styles.
- `frontend/e2e/mock-server.ts` — cancel/prune-answer branches (before `/api/models/download`).
- `frontend/e2e/flow.spec.ts` — console + CANCEL assertion.

---

## Part A — Backend: TtyStream

### Task 1: TtyStream module with tests

**Files:**
- Create: `backend/app/tty_stream.py`
- Test: `backend/tests/test_tty_stream.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tty_stream.py`:

```python
from app.tty_stream import TtyStream


def test_newline_lines():
    s = TtyStream()
    events = s.feed(b"Fetching files...\nDone\n")
    assert events == [("line", "Fetching files..."), ("line", "Done")]
    assert s.flush() == []


def test_carriage_return_is_progress_overwrite():
    s = TtyStream()
    events = s.feed(b"\r45%|####| 45/100\r100%|####| 100/100 [00:01<00:00, 5.0MB/s]\n")
    assert events == [
        ("progress", "45%|####| 45/100"),
        ("line", "100%|####| 100/100 [00:01<00:00, 5.0MB/s]"),
    ]
    assert s.flush() == []


def test_crlf_and_mid_line_overwrite():
    s = TtyStream()
    events = s.feed(b"one\r\ntwo\rthree\n")
    assert events == [("line", "one"), ("line", "three")]
    assert s.flush() == []


def test_ansi_escapes_stripped():
    s = TtyStream()
    events = s.feed(b"\x1b[32mgreen\x1b[0m\n")
    assert events == [("line", "green")]


def test_progress_trailing_spaces_trimmed():
    s = TtyStream()
    events = s.feed(b"10%\r100%   \n")
    assert events == [("progress", "10%"), ("line", "100%")]


def test_control_bytes_dropped():
    s = TtyStream()
    events = s.feed(b"a\x07b\x08c\n")
    assert events == [("line", "abc")]


def test_flush_emits_partial_line():
    s = TtyStream()
    s.feed(b"partial")
    assert s.flush() == [("line", "partial")]
    assert s.flush() == []


def test_partial_utf8_buffered_across_chunks():
    s = TtyStream()
    s.feed("\u2713".encode("utf-8")[:1])
    events = s.feed("\u2713".encode("utf-8")[1:] + b" ok\n")
    assert events == [("line", "\u2713 ok")]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_tty_stream.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tty_stream'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/tty_stream.py`:

```python
import codecs
import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(text: str) -> str:
    text = _ANSI_RE.sub("", text)
    text = _CTRL_RE.sub("", text)
    return text


class TtyStream:
    """Normalize raw pty bytes into (kind, text) events.

    kind is "line" (a finalized newline-terminated line) or "progress" (a
    carriage-return overwrite of the current line, e.g. a tqdm bar update).
    """

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buf = ""

    def feed(self, chunk: bytes) -> list[tuple[str, str]]:
        text = _clean(self._decoder.decode(chunk))
        events: list[tuple[str, str]] = []
        for ch in text:
            if ch == "\r":
                if self._buf:
                    events.append(("progress", self._buf.rstrip()))
                self._buf = ""
            elif ch == "\n":
                if self._buf:
                    events.append(("line", self._buf))
                self._buf = ""
            else:
                self._buf += ch
        return events

    def flush(self) -> list[tuple[str, str]]:
        self._decoder.decode(b"", final=True)
        if self._buf:
            line = self._buf.rstrip()
            self._buf = ""
            return [("line", line)] if line else []
        return []
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_tty_stream.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/tty_stream.py backend/tests/test_tty_stream.py && git commit -m "feat: TtyStream normalizes pty output into line/progress events"
```

---

## Part B — Backend: Command builders

### Task 2: `--format human` + `--cache-dir` in download/prune commands

**Files:**
- Modify: `backend/app/api.py:26-30` (`_download_command`), add `_prune_command`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api.py` (replace the existing
`test_download_command_llama_uses_specific_gguf_when_given`):

```python
def test_download_command_llama_uses_specific_gguf_when_given():
    from app.api import _download_command, _prune_command
    assert _download_command("org/model", "llama.cpp", gguf_filename="model.Q4_K_M.gguf") == [
        "hf", "download", "--format", "human", "org/model", "--include", "model.Q4_K_M.gguf",
    ]
    assert _download_command("org/model", "llama.cpp") == [
        "hf", "download", "--format", "human", "org/model", "--include", "*.gguf",
    ]
    assert _download_command("org/model", "vllm") == [
        "hf", "download", "--format", "human", "org/model",
    ]
    assert _download_command("org/model", "vllm", cache_dir="/tmp/hf") == [
        "hf", "download", "--format", "human", "org/model", "--cache-dir", "/tmp/hf",
    ]
    assert _prune_command() == ["hf", "cache", "prune", "--format", "human"]
    assert _prune_command(cache_dir="/tmp/hf") == [
        "hf", "cache", "prune", "--format", "human", "--cache-dir", "/tmp/hf",
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_api.py::test_download_command_llama_uses_specific_gguf_when_given -v`
Expected: FAIL (command lists don't include `--format human` / `_prune_command` doesn't exist)

- [ ] **Step 3: Write the implementation**

In `backend/app/api.py`, replace `_download_command` and add `_prune_command`:

```python
def _download_command(repo_id: str, server_id: str, gguf_filename: str | None = None,
                      cache_dir: str | None = None) -> list[str]:
    cmd = ["hf", "download", "--format", "human", repo_id]
    if server_id == "llama.cpp":
        cmd += ["--include", gguf_filename or "*.gguf"]
    if cache_dir:
        cmd += ["--cache-dir", cache_dir]
    return cmd


def _prune_command(cache_dir: str | None = None) -> list[str]:
    cmd = ["hf", "cache", "prune", "--format", "human"]
    if cache_dir:
        cmd += ["--cache-dir", cache_dir]
    return cmd
```

`--format human` is passed explicitly because `hf` CLI's `--format auto` is
resolved from environment variables (e.g. `AGENT=1`), not the TTY, and would
suppress progress bars / interactive confirmation in agent-like environments.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_api.py -k "command or cli_missing" -v`
Expected: PASS. Note `test_download_cli_missing_400_with_manual_command` will
still FAIL — fix it in Step 5.

- [ ] **Step 5: Fix the CLI-missing test**

In `backend/tests/test_api.py`, update the assertion in
`test_download_cli_missing_400_with_manual_command` so it matches the new
command shape (the fixture sets `hf_cache_dir`, so `--cache-dir` is present):

```python
def test_download_cli_missing_400_with_manual_command(client, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    r = client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "HF CLI not found." in detail
    assert "hf download" in detail and "org/model" in detail
    assert "--format" in detail and "human" in detail
```

- [ ] **Step 6: Run the full download test group**

Run: `cd backend && python -m pytest tests/test_api.py -k "download" -v`
Expected: the command and cli_missing tests PASS; the old pty-dependent tests
(`test_download_vllm_success_upserts_downloaded`,
`test_download_llama_resolves_gguf_file`,
`test_download_llama_with_gguf_filename_uses_exact_file`) will FAIL because the
job now uses `_spawn_pty`/`_stream_download_output` — those are rewritten in
Task 3.

- [ ] **Step 7: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/api.py backend/tests/test_api.py && git commit -m "feat: pass --format human and --cache-dir to hf download and prune commands"
```

---

## Part C — Backend: pty download streaming + cancel

### Task 3: pty spawn/stream helpers, `_download_job` rewrite, cancel endpoint

**Files:**
- Modify: `backend/app/api.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py`. First update the shared fakes block. Add
these fakes near the top of the download test area (replace the existing
`FakeDownloadProcess` class with the two fakes below):

```python
class FakeDownloadProc:
    """Stands in for an asyncio subprocess attached to a pty."""

    def __init__(self, rc=0):
        self._rc = rc
        self.returncode = None
        self.signals = []
        self.killed = False

    async def wait(self):
        self.returncode = self._rc
        return self._rc

    def send_signal(self, sig):
        self.signals.append(sig)

    def kill(self):
        self.killed = True
        self.returncode = -9


class FakeStdin:
    def __init__(self, answered):
        self.written = []
        self._answered = answered

    def write(self, data):
        self.written.append(data)
        self._answered.set()
        return len(data)

    async def drain(self):
        pass


class FakePruneProcess:
    """Simulates `hf cache prune --format human` writing the summary, then
    blocking on stdin at `Proceed? [y/N]: ` until an answer is written."""

    def __init__(self, first="About to delete 1 incomplete download(s) (8.0 total).\nProceed? [y/N]: ",
                 after="\n✓ Deleted 1 incomplete download(s); freed 8.0.\n", rc=0):
        self._first = first
        self._after = after
        self._rc = rc
        self.returncode = None
        self.answered = asyncio.Event()
        self.stdin = FakeStdin(self.answered)
        self._phase = 0

    @property
    def stdout(self):
        return self

    async def read(self, n=1024):
        if self._phase == 0:
            self._phase = 1
            return self._first.encode()
        if self._phase == 1:
            await self.answered.wait()
            self._phase = 2
            return self._after.encode()
        return b""

    async def wait(self):
        self.returncode = self._rc
        return self._rc
```

Rewrite the existing three download flow tests to inject fakes via the new
helpers. Replace `test_download_vllm_success_upserts_downloaded`:

```python
def test_download_vllm_success_upserts_downloaded(client, tmp_path, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_stream(master_fd):
        yield ("line", "Fetching files...")
        yield ("line", "Done")

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("app.api._open_pty", lambda: (111, 112))
    monkeypatch.setattr("app.api._spawn_pty", lambda *a, **k: FakeDownloadProc())
    monkeypatch.setattr("app.api._stream_download_output", fake_stream)

    snapshot = tmp_path / "hf" / "models--org--model"
    snapshot.mkdir(parents=True)

    r = client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
    assert r.status_code == 200 and r.json()["ok"] is True

    def row():
        m = api_mod.db_mod.get_model(api_mod.state.conn, "org/model", "vllm")
        return m and m["status"]

    assert _poll(lambda: row() == "downloaded")
    assert events[0]["type"] == "download_started"
    assert "hf download" in events[0]["command"]
    assert "--format" in events[0]["command"] and "human" in events[0]["command"]
    assert any(e["type"] == "download_log" and e["line"] == "Fetching files..." for e in events)
    done = next(e for e in events if e["type"] == "download_done")
    assert done["local_path"] == str(snapshot)
    assert api_mod.state._download_active is False
```

Replace `test_download_llama_resolves_gguf_file`:

```python
def test_download_llama_resolves_gguf_file(client, tmp_path, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_stream(master_fd):
        yield ("line", "ok")

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("app.api._open_pty", lambda: (111, 112))
    monkeypatch.setattr("app.api._spawn_pty", lambda *a, **k: FakeDownloadProc())
    monkeypatch.setattr("app.api._stream_download_output", fake_stream)

    gguf = tmp_path / "gguf" / "model.Q4_K_M.gguf"
    gguf.parent.mkdir(parents=True)
    gguf.write_bytes(b"x" * 2048)

    r = client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "llama.cpp"})
    assert r.status_code == 200

    def row():
        return api_mod.db_mod.get_model(api_mod.state.conn, "org/model", "llama.cpp")

    assert _poll(lambda: (row() or {}).get("status") == "downloaded")
    row = row()
    assert row["local_path"] == str(gguf)
    assert row["gguf_filename"] == "model.Q4_K_M.gguf"
    assert row["size_bytes"] == 2048
    start = next(e for e in events if e["type"] == "download_started")
    assert "--include" in start["command"] and "*.gguf" in start["command"]
```

Replace `test_download_llama_with_gguf_filename_uses_exact_file`:

```python
def test_download_llama_with_gguf_filename_uses_exact_file(client, tmp_path, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_stream(master_fd):
        yield ("line", "ok")

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("app.api._open_pty", lambda: (111, 112))
    monkeypatch.setattr("app.api._spawn_pty", lambda *a, **k: FakeDownloadProc())
    monkeypatch.setattr("app.api._stream_download_output", fake_stream)

    gguf = tmp_path / "gguf" / "model.Q4_K_M.gguf"
    gguf.parent.mkdir(parents=True)
    gguf.write_bytes(b"x" * 2048)

    r = client.post("/api/models/download", json={
        "repo_id": "org/model", "server_id": "llama.cpp",
        "gguf_filename": "model.Q4_K_M.gguf",
    })
    assert r.status_code == 200

    def row():
        return api_mod.db_mod.get_model(api_mod.state.conn, "org/model", "llama.cpp")

    assert _poll(lambda: (row() or {}).get("status") == "downloaded")
    row = row()
    assert row["local_path"] == str(gguf)
    start = next(e for e in events if e["type"] == "download_started")
    assert "model.Q4_K_M.gguf" in start["command"]
    assert "*.gguf" not in start["command"]
```

Add new cancel tests:

```python
def test_cancel_409_when_no_download(client):
    r = client.post("/api/models/download/cancel")
    assert r.status_code == 409


def test_cancel_sends_sigint_to_active_proc(client, monkeypatch):
    import app.api as api_mod
    proc = FakeDownloadProc()
    api_mod.state._download_proc = proc
    api_mod.state._download_active = True
    try:
        r = client.post("/api/models/download/cancel")
        assert r.status_code == 200 and r.json()["ok"] is True
        assert api_mod.state._download_cancelled is True
        assert proc.signals == [signal.SIGINT]
    finally:
        api_mod.state._download_active = False
        api_mod.state._download_cancelled = False
        api_mod.state._download_proc = None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api.py -k "download" -v`
Expected: FAIL — the three flow tests fail (`_spawn_pty` not defined), and
`test_cancel_*` fail (`signal` may not be imported / endpoint 404).

- [ ] **Step 3: Implement pty helpers + job rewrite + cancel endpoint**

In `backend/app/api.py`:

1. Extend imports:

```python
import asyncio
import os
import shutil
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path

from app import benchmark as benchmark_mod
from app import db as db_mod
from app import sync as sync_mod
from app.tty_stream import TtyStream
```

2. Extend `AppState.__init__` (after `self._download_active = False`):

```python
        self._download_proc: asyncio.subprocess.Process | None = None
        self._download_cancelled = False
        self._prune_proc: asyncio.subprocess.Process | None = None
        self._prune_answer: asyncio.Queue[str] | None = None
```

3. Add pty helpers (module level, after `_download_command`/`_prune_command`):

```python
def _open_pty() -> tuple[int, int]:
    return os.openpty()


async def _spawn_pty(cmd: list[str], stdin_fd: int, stdout_fd: int, stderr_fd: int):
    return await asyncio.create_subprocess_exec(
        *cmd, stdin=stdin_fd, stdout=stdout_fd, stderr=stderr_fd, start_new_session=True,
    )


async def _read_master(master_fd: int) -> asyncio.Queue[bytes | None]:
    """Read a pty master fd on a background thread into an asyncio queue."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    def _read() -> None:
        try:
            while True:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                loop.call_soon_threadsafe(queue.put_nowait, data)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=_read, daemon=True).start()
    return queue


async def _stream_download_output(master_fd: int):
    """Yield (kind, text) events parsed from a pty master fd."""
    queue = await _read_master(master_fd)
    tty = TtyStream()
    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        for event in tty.feed(chunk):
            yield event
    for event in tty.flush():
        yield event


async def _force_kill_after(proc, delay: float) -> None:
    await asyncio.sleep(delay)
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
```

4. Rewrite `_download_job`:

```python
async def _download_job(s: AppState, repo_id: str, server_id: str,
                        cmd: list[str], gguf_filename: str | None):
    proc = None
    master_fd = None
    slave_fd = None
    try:
        await broadcast(s, {"type": "download_started", "server_id": server_id,
                            "repo_id": repo_id, "command": " ".join(cmd)})
        master_fd, slave_fd = _open_pty()
        proc = await _spawn_pty(cmd, slave_fd, slave_fd, slave_fd)
        try:
            os.close(slave_fd)
            slave_fd = None
        except OSError:
            slave_fd = None
        s._download_proc = proc
        async for kind, text in _stream_download_output(master_fd):
            if kind == "line":
                await broadcast(s, {"type": "download_log", "server_id": server_id,
                                    "repo_id": repo_id, "line": text})
            else:
                await broadcast(s, {"type": "download_progress", "server_id": server_id,
                                    "repo_id": repo_id, "line": text})
        rc = await proc.wait()
        s._download_proc = None
        if s._download_cancelled:
            await broadcast(s, {"type": "download_cancelled", "server_id": server_id,
                                "repo_id": repo_id})
            await _prune_job(s, repo_id, server_id)
            return
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
        for fd in (slave_fd, master_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        s._download_proc = None
        s._download_cancelled = False
        with s._state_lock:
            s._download_active = False
```

5. Update `start_download` to pass `cache_dir`:

```python
    cache_dir = str(s.settings.hf_cache_dir) if s.settings.hf_cache_dir else None
    cmd = _download_command(repo_id, server_id, payload.get("gguf_filename"), cache_dir=cache_dir)
```

6. Add the cancel endpoint after `start_download`:

```python
@router.post("/models/download/cancel")
async def cancel_download():
    s = _require_state()
    with s._state_lock:
        if not s._download_active:
            raise HTTPException(409, "No download is running")
        s._download_cancelled = True
    proc = s._download_proc
    if proc is not None:
        try:
            proc.send_signal(signal.SIGINT)
        except (ProcessLookupError, OSError):
            pass
        asyncio.create_task(_force_kill_after(proc, 5.0))
    return {"ok": True}
```

- [ ] **Step 4: Run the download tests**

Run: `cd backend && python -m pytest tests/test_api.py -k "download" -v`
Expected: PASS except `test_cancel_then_prune_*` which are added in Task 4
(they reference `_prune_job`, defined there).

- [ ] **Step 5: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/api.py backend/tests/test_api.py && git commit -m "feat: stream hf download over a pty and add download cancel endpoint"
```

---

## Part D — Backend: interactive prune flow

### Task 4: `_prune_job`, prune-answer endpoint, and tests

**Files:**
- Modify: `backend/app/api.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py`:

```python
def test_cancel_then_prune_prompt_y(client, monkeypatch):
    import app.api as api_mod
    events = []
    release = asyncio.Event()

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_stream(master_fd):
        yield ("line", "Fetching files...")
        await release.wait()
        yield ("line", "Done")

    async def fake_create(*a, **k):
        return FakePruneProcess()

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("app.api._open_pty", lambda: (111, 112))
    monkeypatch.setattr("app.api._spawn_pty", lambda *a, **k: FakeDownloadProc())
    monkeypatch.setattr("app.api._stream_download_output", fake_stream)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    r = client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
    assert r.status_code == 200
    assert _poll(lambda: any(e["type"] == "download_started" for e in events))
    assert _poll(lambda: api_mod.state._download_proc is not None)

    r = client.post("/api/models/download/cancel")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert api_mod.state._download_cancelled is True
    release.set()

    assert _poll(lambda: any(e["type"] == "prune_started" for e in events))
    assert _poll(lambda: any(e["type"] == "prune_prompt" for e in events))

    r = client.post("/api/models/download/prune-answer", json={"answer": "y"})
    assert r.status_code == 200 and r.json()["ok"] is True

    assert _poll(lambda: any(e["type"] == "prune_done" for e in events))
    done = next(e for e in events if e["type"] == "prune_done")
    assert done["accepted"] is True
    assert any(e["type"] == "prune_log" and "About to delete" in e["line"] for e in events)
    assert api_mod.state._download_active is False


def test_cancel_then_prune_prompt_n(client, monkeypatch):
    import app.api as api_mod
    events = []
    release = asyncio.Event()

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_stream(master_fd):
        yield ("line", "Fetching files...")
        await release.wait()
        yield ("line", "Done")

    async def fake_create(*a, **k):
        return FakePruneProcess(after="\nAborted!\n", rc=1)

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("app.api._open_pty", lambda: (111, 112))
    monkeypatch.setattr("app.api._spawn_pty", lambda *a, **k: FakeDownloadProc())
    monkeypatch.setattr("app.api._stream_download_output", fake_stream)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
    assert _poll(lambda: any(e["type"] == "download_started" for e in events))
    client.post("/api/models/download/cancel")
    release.set()

    assert _poll(lambda: any(e["type"] == "prune_prompt" for e in events))
    client.post("/api/models/download/prune-answer", json={"answer": "n"})
    assert _poll(lambda: any(e["type"] == "prune_done" for e in events))
    done = next(e for e in events if e["type"] == "prune_done")
    assert done["accepted"] is False


def test_cancel_then_prune_nothing_to_prune(client, monkeypatch):
    import app.api as api_mod
    events = []
    release = asyncio.Event()

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_stream(master_fd):
        yield ("line", "Fetching files...")
        await release.wait()
        yield ("line", "Done")

    async def fake_create(*a, **k):
        return FakePruneProcess(
            first="No unreferenced revisions or incomplete downloads found. Nothing to prune.\n",
            after="", rc=0,
        )

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("app.api._open_pty", lambda: (111, 112))
    monkeypatch.setattr("app.api._spawn_pty", lambda *a, **k: FakeDownloadProc())
    monkeypatch.setattr("app.api._stream_download_output", fake_stream)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
    assert _poll(lambda: any(e["type"] == "download_started" for e in events))
    client.post("/api/models/download/cancel")
    release.set()

    assert _poll(lambda: any(e["type"] == "prune_done" for e in events))
    assert not any(e["type"] == "prune_prompt" for e in events)
    done = next(e for e in events if e["type"] == "prune_done")
    assert done["accepted"] is True


def test_prune_answer_validation(client):
    import app.api as api_mod
    api_mod.state._download_active = True
    try:
        r = client.post("/api/models/download/prune-answer", json={"answer": "maybe"})
        assert r.status_code == 422
        r = client.post("/api/models/download/prune-answer", json={})
        assert r.status_code == 422
        r = client.post("/api/models/download/prune-answer", json={"answer": "y"})
        assert r.status_code == 409
    finally:
        api_mod.state._download_active = False
```

Note: `test_cancel_*` tests set `_download_active` indirectly via the POST
`/api/models/download` calls; `_prune_job` runs inside the same asyncio task.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api.py -k "prune or cancel_then" -v`
Expected: FAIL — `_prune_job` not defined (job crashes → `download_error`).

- [ ] **Step 3: Implement `_prune_job` + prune-answer endpoint**

In `backend/app/api.py`, add `_prune_job` after `_download_job`:

```python
async def _prune_job(s: AppState, repo_id: str, server_id: str):
    cache_dir = str(s.settings.hf_cache_dir) if s.settings.hf_cache_dir else None
    cmd = _prune_command(cache_dir=cache_dir)
    proc = None
    last_line = ""
    prompt_sent = False
    try:
        await broadcast(s, {"type": "prune_started", "server_id": server_id,
                            "repo_id": repo_id, "command": " ".join(cmd)})
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        s._prune_proc = proc
        buf = ""
        while True:
            chunk = await proc.stdout.read(1024)
            if not chunk:
                break
            buf += chunk.decode(errors="replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.rstrip("\r")
                if line:
                    last_line = line
                    await broadcast(s, {"type": "prune_log", "server_id": server_id,
                                        "repo_id": repo_id, "line": line})
            if not prompt_sent and "Proceed?" in buf:
                prompt_sent = True
                q: asyncio.Queue[str] = asyncio.Queue()
                s._prune_answer = q
                await broadcast(s, {"type": "prune_prompt", "server_id": server_id,
                                    "repo_id": repo_id})
                answer = await q.get()
                assert proc.stdin is not None
                proc.stdin.write((answer + "\n").encode())
                await proc.stdin.drain()
                buf = ""
        rc = await proc.wait()
        await broadcast(s, {"type": "prune_done", "server_id": server_id,
                            "repo_id": repo_id, "accepted": rc == 0, "message": last_line})
    except Exception as e:
        await broadcast(s, {"type": "prune_done", "server_id": server_id,
                            "repo_id": repo_id, "accepted": False, "message": str(e)})
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        s._prune_proc = None
        s._prune_answer = None
```

Add the prune-answer endpoint after the cancel endpoint:

```python
@router.post("/models/download/prune-answer")
async def prune_answer(payload: dict):
    s = _require_state()
    answer = payload.get("answer")
    if answer not in ("y", "n"):
        raise HTTPException(422, "'answer' must be 'y' or 'n'.")
    if s._prune_answer is None:
        raise HTTPException(409, "No prune is waiting for input")
    await s._prune_answer.put(answer)
    return {"ok": True}
```

- [ ] **Step 4: Run the prune + cancel tests**

Run: `cd backend && python -m pytest tests/test_api.py -k "prune or cancel_then or cancel" -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && python -m pytest`
Expected: PASS (all tests, including the rewritten download tests).

- [ ] **Step 6: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/api.py backend/tests/test_api.py && git commit -m "feat: interactive hf cache prune after cancelled download with y/N prompt"
```

---

## Part E — Frontend: events + download reducer

### Task 5: Extend DownloadEvent, add downloadReducer with tests

**Files:**
- Modify: `frontend/src/ws/useDownloadProgress.ts`
- Create: `frontend/src/ws/downloadReducer.ts`
- Test: `frontend/src/ws/downloadReducer.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/ws/downloadReducer.test.ts`:

```ts
import { downloadActive, downloadReducer, key } from "./downloadReducer";
import type { DownloadEvent } from "./useDownloadProgress";

const ev = (type: DownloadEvent["type"], extra: Partial<DownloadEvent> = {}): DownloadEvent => ({
  type,
  server_id: "vllm",
  repo_id: "org/model",
  ...extra,
});

test("started sets downloading and command, resets lines", () => {
  let s = downloadReducer({}, ev("download_started", { command: "hf download org/model" }));
  expect(s["vllm::org/model"].status).toBe("downloading");
  expect(s["vllm::org/model"].command).toBe("hf download org/model");
  expect(key("vllm", "org/model")).toBe("vllm::org/model");
});

test("log appends and progress replaces the last line", () => {
  let s = downloadReducer({}, ev("download_started"));
  s = downloadReducer(s, ev("download_log", { line: "Fetching..." }));
  s = downloadReducer(s, ev("download_progress", { line: "45%" }));
  s = downloadReducer(s, ev("download_progress", { line: "100%" }));
  expect(s["vllm::org/model"].lines).toEqual(["Fetching...", "100%"]);
});

test("progress with no prior lines creates one line", () => {
  const s = downloadReducer({}, ev("download_progress", { line: "45%" }));
  expect(s["vllm::org/model"].lines).toEqual(["45%"]);
});

test("done and error set terminal states", () => {
  let s = downloadReducer({}, ev("download_started"));
  s = downloadReducer(s, ev("download_done", { local_path: "/x" }));
  expect(s["vllm::org/model"].status).toBe("downloaded");
  expect(s["vllm::org/model"].local_path).toBe("/x");
  let t = downloadReducer({}, ev("download_started"));
  t = downloadReducer(t, ev("download_error", { message: "boom" }));
  expect(t["vllm::org/model"].status).toBe("error");
  expect(t["vllm::org/model"].message).toBe("boom");
});

test("cancel then prune sequence keeps the console entry", () => {
  let s = downloadReducer({}, ev("download_started"));
  s = downloadReducer(s, ev("download_cancelled"));
  expect(s["vllm::org/model"].status).toBe("cancelled");
  s = downloadReducer(s, ev("prune_started", { command: "hf cache prune --format human" }));
  expect(s["vllm::org/model"].status).toBe("pruning");
  s = downloadReducer(s, ev("prune_log", { line: "About to delete 1 incomplete download(s)." }));
  s = downloadReducer(s, ev("prune_prompt"));
  expect(s["vllm::org/model"].waitingInput).toBe(true);
  s = downloadReducer(s, ev("prune_done", { accepted: true }));
  expect(s["vllm::org/model"].status).toBe("pruned");
  expect(s["vllm::org/model"].pruneAccepted).toBe(true);
  expect(s["vllm::org/model"].waitingInput).toBe(false);
});

test("downloadActive is true while downloading/cancelled/pruning", () => {
  let s = downloadReducer({}, ev("download_started"));
  expect(downloadActive(s)).toBe(true);
  s = downloadReducer(s, ev("download_cancelled"));
  expect(downloadActive(s)).toBe(true);
  s = downloadReducer(s, ev("prune_started"));
  expect(downloadActive(s)).toBe(true);
  s = downloadReducer(s, ev("prune_done", { accepted: false }));
  expect(downloadActive(s)).toBe(false);
  expect(downloadActive({})).toBe(false);
});

test("events without server/repo are ignored", () => {
  const s = downloadReducer({}, { type: "download_log", line: "x" } as DownloadEvent);
  expect(s).toEqual({});
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/ws/downloadReducer.test.ts`
Expected: FAIL — module `./downloadReducer` not found.

- [ ] **Step 3: Implement `downloadReducer` + extend `DownloadEvent`**

In `frontend/src/ws/useDownloadProgress.ts`, replace the `DownloadEvent`
interface:

```ts
export interface DownloadEvent {
  type:
    | "download_started"
    | "download_log"
    | "download_progress"
    | "download_done"
    | "download_error"
    | "download_cancelled"
    | "prune_started"
    | "prune_log"
    | "prune_prompt"
    | "prune_done";
  server_id?: string;
  repo_id?: string;
  command?: string;
  line?: string;
  status?: string;
  local_path?: string;
  message?: string;
  accepted?: boolean;
}
```

Create `frontend/src/ws/downloadReducer.ts`:

```ts
import type { DownloadEvent } from "./useDownloadProgress";

export type DownloadStatusType =
  | "downloading"
  | "downloaded"
  | "error"
  | "cancelled"
  | "pruning"
  | "pruned";

export interface DownloadStatus {
  status: DownloadStatusType;
  command: string;
  lines: string[];
  waitingInput: boolean;
  pruneAccepted: boolean | null;
  message?: string;
  local_path?: string;
}

export interface DownloadState {
  [key: string]: DownloadStatus;
}

export function key(serverId: string, repoId: string): string {
  return `${serverId}::${repoId}`;
}

export function downloadActive(state: DownloadState): boolean {
  return Object.values(state).some(
    (d) => d.status === "downloading" || d.status === "cancelled" || d.status === "pruning",
  );
}

const IDLE: DownloadStatus = {
  status: "downloading",
  command: "",
  lines: [],
  waitingInput: false,
  pruneAccepted: null,
};

export function downloadReducer(state: DownloadState, event: DownloadEvent): DownloadState {
  if (!event.server_id || !event.repo_id) return state;
  const k = key(event.server_id, event.repo_id);
  const cur: DownloadStatus = state[k] ?? { ...IDLE };
  switch (event.type) {
    case "download_started":
      return { ...state, [k]: { ...cur, status: "downloading", command: event.command ?? "", lines: [] } };
    case "download_log":
      return { ...state, [k]: { ...cur, lines: [...cur.lines, event.line ?? ""] } };
    case "download_progress": {
      const lines = cur.lines.length ? [...cur.lines] : [""];
      lines[lines.length - 1] = event.line ?? "";
      return { ...state, [k]: { ...cur, lines } };
    }
    case "download_done":
      return { ...state, [k]: { ...cur, status: "downloaded", local_path: event.local_path } };
    case "download_error":
      return { ...state, [k]: { ...cur, status: "error", message: event.message } };
    case "download_cancelled":
      return { ...state, [k]: { ...cur, status: "cancelled" } };
    case "prune_started":
      return { ...state, [k]: { ...cur, status: "pruning", command: event.command ?? cur.command } };
    case "prune_log":
      return { ...state, [k]: { ...cur, lines: [...cur.lines, event.line ?? ""] } };
    case "prune_prompt":
      return { ...state, [k]: { ...cur, waitingInput: true } };
    case "prune_done":
      return {
        ...state,
        [k]: {
          ...cur,
          status: "pruned",
          waitingInput: false,
          pruneAccepted: event.accepted ?? false,
          message: event.message,
        },
      };
    default:
      return state;
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/ws/downloadReducer.test.ts`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/ruben/test/llmbench && git add frontend/src/ws/useDownloadProgress.ts frontend/src/ws/downloadReducer.ts frontend/src/ws/downloadReducer.test.ts && git commit -m "feat: download reducer and extended ws event types"
```

---

## Part F — Frontend: DownloadConsole component

### Task 6: DownloadConsole component, styles, and tests

**Files:**
- Create: `frontend/src/components/DownloadConsole.tsx`
- Test: `frontend/src/components/DownloadConsole.test.tsx`
- Modify: `frontend/src/styles/app.css`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/DownloadConsole.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { DownloadConsole } from "./DownloadConsole";
import type { DownloadStatus } from "../ws/downloadReducer";

function status(over: Partial<DownloadStatus> = {}): DownloadStatus {
  return {
    status: "downloading",
    command: "hf download org/model",
    lines: ["Fetching..."],
    waitingInput: false,
    pruneAccepted: null,
    ...over,
  };
}

test("renders command header and console lines, cancel calls onCancel", () => {
  const onCancel = vi.fn();
  const onPruneAnswer = vi.fn();
  render(<DownloadConsole status={status()} onCancel={onCancel} onPruneAnswer={onPruneAnswer} />);
  expect(screen.getByText(/\$ hf download org\/model/i)).toBeInTheDocument();
  expect(screen.getByText("Fetching...")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
  expect(onCancel).toHaveBeenCalledTimes(1);
});

test("no cancel button outside downloading", () => {
  render(
    <DownloadConsole
      status={status({ status: "pruning", command: "hf cache prune --format human" })}
      onCancel={vi.fn()}
      onPruneAnswer={vi.fn()}
    />,
  );
  expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
});

test("y/n prompt answers call onPruneAnswer", () => {
  const onPruneAnswer = vi.fn();
  render(
    <DownloadConsole
      status={status({ status: "pruning", command: "hf cache prune --format human", waitingInput: true })}
      onCancel={vi.fn()}
      onPruneAnswer={onPruneAnswer}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "y" }));
  expect(onPruneAnswer).toHaveBeenCalledWith("y");
  fireEvent.click(screen.getByRole("button", { name: "n" }));
  expect(onPruneAnswer).toHaveBeenCalledWith("n");
});

test("typed y/n submits on Enter", () => {
  const onPruneAnswer = vi.fn();
  render(
    <DownloadConsole
      status={status({ status: "pruning", waitingInput: true })}
      onCancel={vi.fn()}
      onPruneAnswer={onPruneAnswer}
    />,
  );
  const input = screen.getByPlaceholderText("y / n");
  fireEvent.change(input, { target: { value: "y" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onPruneAnswer).toHaveBeenCalledWith("y");
});

test("shows downloaded path and no prompt when complete", () => {
  render(
    <DownloadConsole
      status={status({ status: "downloaded", local_path: "/tmp/x" })}
      onCancel={vi.fn()}
      onPruneAnswer={vi.fn()}
    />,
  );
  expect(screen.getByText(/\/tmp\/x/)).toBeInTheDocument();
  expect(screen.queryByPlaceholderText("y / n")).not.toBeInTheDocument();
});

test("shows pruned summary after prune", () => {
  render(
    <DownloadConsole
      status={status({ status: "pruned", pruneAccepted: true })}
      onCancel={vi.fn()}
      onPruneAnswer={vi.fn()}
    />,
  );
  expect(screen.getByText(/cache pruned/i)).toBeInTheDocument();
});

test("shows error message", () => {
  render(
    <DownloadConsole
      status={status({ status: "error", message: "boom" })}
      onCancel={vi.fn()}
      onPruneAnswer={vi.fn()}
    />,
  );
  expect(screen.getByText(/boom/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/DownloadConsole.test.tsx`
Expected: FAIL — component not found.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/DownloadConsole.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import type { DownloadStatus } from "../ws/downloadReducer";

interface Props {
  status: DownloadStatus;
  onCancel: () => void;
  onPruneAnswer: (answer: "y" | "n") => void;
}

export function DownloadConsole({ status, onCancel, onPruneAnswer }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [answer, setAnswer] = useState("");

  useEffect(() => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [status.lines]);

  const submit = () => {
    const v = answer.trim().toLowerCase();
    if (v === "y" || v === "n") {
      onPruneAnswer(v);
      setAnswer("");
    }
  };

  return (
    <div className="dl-console">
      <div className="dl-console-head">$ {status.command}</div>
      <div className="dl-console-body" ref={boxRef}>
        {status.lines.map((line, i) => (
          <div key={i}>{line || "\u00a0"}</div>
        ))}
      </div>
      <div className="dl-console-actions">
        {status.status === "downloading" && (
          <button className="btn-neutral" onClick={onCancel}>CANCEL</button>
        )}
        {status.waitingInput && (
          <span style={{ color: "var(--anode)", fontSize: 12 }}>
            hf cache prune — Proceed? [y/N]
          </span>
        )}
        {status.waitingInput && (
          <input
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
            placeholder="y / n"
            style={{ width: 90 }}
          />
        )}
        {status.waitingInput && (
          <button onClick={() => onPruneAnswer("y")}>y</button>
        )}
        {status.waitingInput && (
          <button onClick={() => onPruneAnswer("n")}>n</button>
        )}
      </div>
      {status.status === "downloaded" && status.local_path && (
        <div style={{ color: "var(--ok)", fontSize: 12 }}>
          downloaded → {status.local_path}
        </div>
      )}
      {status.status === "pruned" && (
        <div style={{ color: "var(--anode)", fontSize: 12 }}>
          {status.pruneAccepted
            ? "cache pruned — retry the download when ready"
            : "prune skipped — retry the download when ready"}
        </div>
      )}
      {status.status === "error" && (
        <div style={{ color: "var(--accent)", fontSize: 12 }}>error: {status.message}</div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Add console styles**

Append to `frontend/src/styles/app.css`:

```css
.dl-console {
  border: 1px solid var(--rule-bright);
  border-radius: var(--radius);
  background: var(--panel);
  margin-top: 10px;
  padding: 8px;
  font-size: 12px;
}
.dl-console-head {
  color: var(--anode);
  letter-spacing: .04em;
  margin-bottom: 6px;
  white-space: pre-wrap;
  word-break: break-all;
}
.dl-console-body {
  max-height: 220px;
  overflow-y: auto;
  margin: 0;
  padding: 6px;
  background: var(--steel);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--tube);
}
.dl-console-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.btn-neutral {
  background: transparent;
  color: var(--tube);
  border: 1px solid var(--rule-bright);
  font-weight: 400;
}
```

- [ ] **Step 5: Run the component tests**

Run: `cd frontend && npx vitest run src/components/DownloadConsole.test.tsx`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
cd /home/ruben/test/llmbench && git add frontend/src/components/DownloadConsole.tsx frontend/src/components/DownloadConsole.test.tsx frontend/src/styles/app.css && git commit -m "feat: DownloadConsole component with cancel and y/N prune prompt"
```

---

## Part G — Frontend: App wiring + API client

### Task 7: Wire reducer + console into App, add API methods, update tests

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/App.test.tsx`. First extend the `api` mock at the top of
the file:

```tsx
vi.mock("./api/client", () => ({
  api: {
    getServers: vi.fn().mockResolvedValue({ readiness: {}, hardware: {} }),
    listModels: vi.fn().mockResolvedValue({ models: [] }),
    listRuns: vi.fn().mockResolvedValue({ runs: [] }),
    analyze: vi.fn().mockResolvedValue({ repo_id: "org/model", detected_server: "vllm", readme_flags: {} }),
    generateConfigs: vi.fn().mockResolvedValue({
      configs: [{ flags: { "--n-gpu": "1" }, serving_command: "python serve.py", bench_command: [] }],
    }),
    startBenchmark: vi.fn().mockResolvedValue({ run_id: 1 }),
    downloadModel: vi.fn().mockResolvedValue({ ok: true }),
    cancelDownload: vi.fn().mockResolvedValue({ ok: true }),
    answerPrune: vi.fn().mockResolvedValue({ ok: true }),
    removeModel: vi.fn(),
  },
}));
```

Then add this test:

```tsx
test("cancel flow: CANCEL shows prune prompt, answering y completes", async () => {
  const { api } = await import("./api/client");
  const { useDownloadProgress } = await import("./ws/useDownloadProgress");
  const cancelSpy = vi.spyOn(api, "cancelDownload").mockResolvedValue({ ok: true });
  const pruneSpy = vi.spyOn(api, "answerPrune").mockResolvedValue({ ok: true });
  vi.mocked(useDownloadProgress).mockReturnValue([]);

  const view = render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  fireEvent.click(within(screen.getByText("vllm:").closest("span")!).getByText("Download"));
  expect(await screen.findByRole("button", { name: /cancel/i })).toBeInTheDocument();

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "download_started", server_id: "vllm", repo_id: "org/model", command: "hf download org/model" },
    { type: "download_log", server_id: "vllm", repo_id: "org/model", line: "Fetching..." },
  ]);
  view.rerender(<MemoryRouter><App /></MemoryRouter>);

  fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
  expect(cancelSpy).toHaveBeenCalled();

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "download_cancelled", server_id: "vllm", repo_id: "org/model" },
    { type: "prune_started", server_id: "vllm", repo_id: "org/model", command: "hf cache prune --format human" },
    { type: "prune_log", server_id: "vllm", repo_id: "org/model", line: "About to delete 1 incomplete download(s)." },
    { type: "prune_prompt", server_id: "vllm", repo_id: "org/model" },
  ]);
  view.rerender(<MemoryRouter><App /></MemoryRouter>);

  const yBtn = screen.getByRole("button", { name: "y" });
  fireEvent.click(yBtn);
  expect(pruneSpy).toHaveBeenCalledWith("y");

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "prune_done", server_id: "vllm", repo_id: "org/model", accepted: true },
  ]);
  view.rerender(<MemoryRouter><App /></MemoryRouter>);

  expect(await screen.findByText(/cache pruned/i)).toBeInTheDocument();
  const span = within(screen.getByText("vllm:").closest("span")!);
  expect(span.getByRole("button", { name: /^download$/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/App.test.tsx -t "cancel flow"`
Expected: FAIL — `api.cancelDownload` is not a function.

- [ ] **Step 3: Add API methods**

In `frontend/src/api/client.ts`, add after `downloadModel`:

```ts
  downloadModel: (body: { repo_id: string; server_id: string; gguf_filename?: string }) =>
    request<{ ok: boolean }>("/models/download", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  cancelDownload: () => request<{ ok: boolean }>("/models/download/cancel", { method: "POST" }),
  answerPrune: (answer: "y" | "n") =>
    request<{ ok: boolean }>("/models/download/prune-answer", {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),
```

- [ ] **Step 4: Wire the App**

Rewrite the download state/handlers in `frontend/src/App.tsx`:

Imports — add the reducer + console:

```tsx
import { DownloadConsole } from "./components/DownloadConsole";
import {
  downloadActive,
  downloadReducer,
  DownloadState,
} from "./ws/downloadReducer";
```

Replace the `DownloadStatus` interface, `downloads` state, and the
`downloadActive` derivation (lines ~73-81) with:

```tsx
  const [downloads, setDownloads] = useState<DownloadState>({});
  const [downloadKey, setDownloadKey] = useState<string | null>(null);
  const downloadActiveNow = downloadActive(downloads);
  const downloadEvents = useDownloadProgress(downloadActiveNow);
```

Replace the `downloadEvents` effect (lines ~83-104) with:

```tsx
  useEffect(() => {
    for (const ev of downloadEvents) {
      setDownloads((prev) => downloadReducer(prev, ev));
      if (ev.type === "download_done") {
        api.listModels().then((d) => setDownloaded(d.models));
      }
    }
  }, [downloadEvents]);
```

Replace `onDownload` (lines ~106-122) with:

```tsx
  const onDownload = useCallback(
    async (serverId: string) => {
      if (!analysis?.repo_id) return;
      const k = `${serverId}::${analysis.repo_id}`;
      setDownloadKey(k);
      setDownloads((prev) => ({
        ...prev,
        [k]: { status: "downloading", command: "", lines: [], waitingInput: false, pruneAccepted: null },
      }));
      try {
        const gguf = analysis.gguf_files?.length === 1 ? analysis.gguf_files[0].path : undefined;
        await api.downloadModel({ repo_id: analysis.repo_id, server_id: serverId, gguf_filename: gguf });
      } catch (err) {
        setDownloads((prev) => ({
          ...prev,
          [k]: { ...prev[k], status: "error", message: err instanceof Error ? err.message : String(err) },
        }));
      }
    },
    [analysis],
  );

  const onCancel = useCallback(async () => {
    try {
      await api.cancelDownload();
    } catch (err) {
      if (!downloadKey) return;
      setDownloads((prev) => ({
        ...prev,
        [downloadKey]: {
          ...prev[downloadKey],
          status: "error",
          message: err instanceof Error ? err.message : String(err),
        },
      }));
    }
  }, [downloadKey]);

  const onPruneAnswer = useCallback(
    async (answer: "y" | "n") => {
      try {
        await api.answerPrune(answer);
      } catch (err) {
        if (!downloadKey) return;
        setDownloads((prev) => ({
          ...prev,
          [downloadKey]: {
            ...prev[downloadKey],
            status: "error",
            message: err instanceof Error ? err.message : String(err),
          },
        }));
      }
    },
    [downloadKey],
  );
```

In `onAnalyze`, reset the download state:

```tsx
  const onAnalyze = useCallback(async (input: string) => {
    const data = await api.analyze(input);
    setAnalysis(data);
    setConfigs([]);
    setDownloads({});
    setDownloadKey(null);
  }, []);
```

Replace the per-server download row block and add the console beneath it
(lines ~210-234). Replace:

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

with:

```tsx
                {analysis?.repo_id && (
                  <div className="row" style={{ gap: 12, marginTop: 8, flexWrap: "wrap" }}>
                    {KNOWN_SERVERS.map((sid) => {
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
                {downloadKey && downloads[downloadKey] && (
                  <DownloadConsole
                    status={downloads[downloadKey]}
                    onCancel={onCancel}
                    onPruneAnswer={onPruneAnswer}
                  />
                )}
```

- [ ] **Step 5: Run the App tests**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS — the new cancel-flow test plus the existing download-flow test
(the "download flow: click Download, shows downloading then downloaded" test
still works because the reducer maps `download_log`+`download_done`).

- [ ] **Step 6: Run the full frontend unit suite + typecheck**

Run: `cd frontend && npx vitest run && npx tsc -b`
Expected: PASS — all unit tests and TypeScript build.

- [ ] **Step 7: Commit**

```bash
cd /home/ruben/test/llmbench && git add frontend/src/api/client.ts frontend/src/App.tsx frontend/src/App.test.tsx && git commit -m "feat: wire download console, cancel, and prune prompt into model input panel"
```

---

## Part H — Frontend: e2e mock server + flow

### Task 8: e2e mock-server branches and flow assertions

**Files:**
- Modify: `frontend/e2e/mock-server.ts`
- Modify: `frontend/e2e/flow.spec.ts`

- [ ] **Step 1: Update the mock server**

In `frontend/e2e/mock-server.ts`, insert cancel/prune-answer branches **before**
the `/api/models/download` branch (order matters — it matches by `startsWith`):

```ts
  } else if (req.url?.startsWith("/api/models/download/cancel")) {
    Object.assign(body, { ok: true });
  } else if (req.url?.startsWith("/api/models/download/prune-answer")) {
    Object.assign(body, { ok: true });
  } else if (req.url?.startsWith("/api/models/download")) {
    Object.assign(body, { ok: true });
```

The existing `else if (req.url?.startsWith("/api/models/download"))` branch
stays as-is below the two new branches.

- [ ] **Step 2: Add the e2e test**

Append to `frontend/e2e/flow.spec.ts`:

```ts
test("download console renders with a CANCEL action", async ({ page }) => {
  await page.goto("http://localhost:5173");
  await page.getByPlaceholder(/huggingface/i).fill("org/model");
  await page.getByRole("button", { name: /analyze/i }).click();
  await expect(page.getByText(/server vLLM/i)).toBeVisible();

  await page.getByRole("button", { name: /^download$/i }).first().click();
  await expect(page.getByText(/\$ hf download --format human org\/model/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /cancel/i })).toBeVisible();
  await page.getByRole("button", { name: /cancel/i }).click();
  await expect(page.getByRole("button", { name: /cancel/i })).toBeVisible();
});
```

Note: the mock server has no WebSocket support, so the console stays in the
"downloading" state after the HTTP `cancel` call — the test asserts the console
and CANCEL button render. The cancel→prune prompt behavior is covered by the
unit/component tests.

- [ ] **Step 3: Verify the e2e suite runs**

Run: `cd frontend && npx playwright test`
Expected: PASS (requires the app running via `./up.sh`; existing flow test must
still pass).

- [ ] **Step 4: Commit**

```bash
cd /home/ruben/test/llmbench && git add frontend/e2e/mock-server.ts frontend/e2e/flow.spec.ts && git commit -m "test: e2e coverage for download console and cancel"
```

---

## Final Verification

- [ ] **Run the full backend suite**

Run: `cd backend && python -m pytest`
Expected: PASS.

- [ ] **Run the full frontend unit suite + build**

Run: `cd frontend && npx vitest run && npx tsc -b && npm run build`
Expected: PASS.

- [ ] **Manual smoke test**

Start the app (`./up.sh`), open http://localhost:5173, analyze a real model,
click Download, confirm the scrolling console shows live progress bars, click
CANCEL, confirm the prune summary appears with `Proceed? [y/N]`, answer `y` or
`n`, and confirm the console shows the outcome and the Download button returns.
