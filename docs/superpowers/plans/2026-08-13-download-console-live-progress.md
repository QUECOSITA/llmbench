# Download Console Live Progress — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the DOWNLOAD console stream live `hf download` progress bars again by preventing the hf CLI from detecting agent mode (which globally disables progress bars).

**Architecture:** The backend's `spawn_env()` copies `os.environ` verbatim, leaking agent-detection vars (`AGENT=1`) into the `hf download` subprocess. The hf CLI 1.26.0 auto-detects agent mode at import and globally disables tqdm progress bars — `--format human` no longer re-enables them. Stripping the universal agent vars (`AGENT`, `AI_AGENT`) from `spawn_env()` restores human-mode progress output, which the existing `TtyStream` → WS `download_log`/`download_progress` pipeline streams to the console. llama.cpp / speed-bench subprocesses don't read these vars, so the change is safe.

**Tech Stack:** Python/FastAPI/asyncio (backend only change; frontend unchanged).

---

## File Structure

- Modify: `backend/app/spawn.py` — strip agent-detection env vars from `spawn_env()`.
- Modify: `backend/tests/test_spawn.py` — assert `AGENT`/`AI_AGENT` are removed, other vars preserved.

No other files change. The frontend already renders `download_log`/`download_progress` WS events correctly; it just wasn't receiving them because the CLI emitted no progress.

---

### Task 1: Strip agent-detection env vars in spawn_env

**Files:**
- Modify: `backend/app/spawn.py`
- Modify: `backend/tests/test_spawn.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_spawn.py`:

```python
def test_spawn_env_strips_agent_detection_vars(monkeypatch):
    monkeypatch.setenv("AGENT", "1")
    monkeypatch.setenv("AI_AGENT", "claude")
    monkeypatch.setenv("HOME", "/home/test")
    env = spawn_env()
    assert "AGENT" not in env
    assert "AI_AGENT" not in env
    assert env["HOME"] == "/home/test"


def test_spawn_env_keeps_unrelated_vars(monkeypatch):
    monkeypatch.setenv("AGENT", "1")
    monkeypatch.setenv("LLMBENCH_SOMETHING", "kept")
    env = spawn_env()
    assert env["LLMBENCH_SOMETHING"] == "kept"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_spawn.py -q`
Expected: FAIL — `"AGENT" not in env` assertion fails (AGENT is still present).

- [ ] **Step 3: Implement the fix**

Replace the body of `spawn_env()` in `backend/app/spawn.py`:

```python
import os

# The hf CLI auto-detects agent mode from these universal env vars at import
# time and then globally disables tqdm progress bars, so `hf download` emits
# no streaming output. Strip them so spawned subprocesses (download, prune,
# serving, bench) always run in human mode with progress bars.
_AGENT_DETECTION_ENV_VARS = ("AGENT", "AI_AGENT")


def spawn_env() -> dict[str, str]:
    """Environment for spawned server/bench subprocesses."""
    env = dict(os.environ)
    for var in _AGENT_DETECTION_ENV_VARS:
        env.pop(var, None)
    return env
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_spawn.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && source .venv/bin/activate && python -m pytest -q`
Expected: PASS (existing download/api/tty_stream tests unchanged).

- [ ] **Step 6: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/spawn.py backend/tests/test_spawn.py && git commit -m "fix: strip agent env vars from spawned subprocesses so hf download streams live progress"
```

---

## Final Verification

- [ ] **Run the frontend suite + typecheck**

Run: `cd frontend && npx tsc -b && npm test`
Expected: PASS (frontend unchanged).

- [ ] **Run Playwright e2e**

Stop dev servers with `./down.sh`, run `cd frontend && npx playwright test`, then restore with `./up.sh`.
Expected: PASS.

- [ ] **Live browser smoke test**

Start the app (`./up.sh`), open http://localhost:5173, analyze a repo, click DOWNLOAD, and confirm:
- the console header shows `$ hf download --format human ...`;
- the console body streams real-time progress lines during the download;
- the row shows `downloaded` and the console shows the path on completion.

- [ ] **Manual pty check (optional)**

With `AGENT=1` in env, run the download command in a pty and confirm tqdm bars (with `%` and `\r`) appear.
