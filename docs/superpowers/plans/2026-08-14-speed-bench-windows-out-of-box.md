# speed-bench Windows Out-of-the-Box Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make llama.cpp `speed-bench` (llama-server + `speed_bench.py`) work out-of-the-box in the Windows release for MTP / speculative-decoding models, with parity across all launchers (`up.bat`/`up.sh`), without ever risking app startup.

**Architecture:** Three independent fixes. (1) Replace the POSIX-only `shlex.split` at the three command-splitting call sites in `servers.py` with a Windows-aware pure tokenizer that keeps backslash paths intact and preserves the existing `ValueError("No closing quotation")` malformed-command contract. (2) Install the `[speed-bench]` deps (`datasets`/`requests`/`tqdm`) in a separate, best-effort (never-aborting) step in both launchers, plus a CI matrix install to prove the wheels exist on all OSes. (3) Provision `speed_bench.py` lazily from the backend: `ensure_speed_bench_script` best-effort downloads it into `~/.llmbench/speed-bench/` (once per process, never raises) only when an MTP model is actually selected for speed-bench; `resolve_speed_bench_script` and `detect_binaries` gain a `data_dir` discovery candidate so readiness reflects a provisioned script.

**Tech Stack:** Python 3.11+/FastAPI/asyncio, `httpx` (already a dep), pytest/pytest-asyncio, PowerShell 5.1 (`scripts/up.ps1`), bash (`up.sh`), GitHub Actions (`ci.yml`).

**Branch:** work on `feature/cross-platform-pty-support` (same branch as PR #27). Do NOT commit the untracked `backend/data/llmbench.db`.

---

### Task 1: Windows-safe command tokenizer

> **Executed (2026-08-14):** commits `67150ac` + `407581d`. One controller-approved deviation: `_split_command` auto-detects Windows drive-letter paths (`_has_windows_path`, regex `[A-Za-z]:\\`) and uses the Windows tokenizer even on POSIX, so the `build_server_command` roundtrip test passes on all three CI OSes. Also hardened `_split_windows` to split on `\r\n` as well as spaces/tabs (post-review Minor fix).

**Files:**
- Modify: `backend/app/servers.py` (top imports; `parse_speed_bench_flags` at ~136-153; `build_server_command` at ~205-229; `parse_serving_command` at ~279-301)
- Test: `backend/tests/test_servers.py`

- [ ] **Step 1: Add module-level imports to `backend/app/servers.py`**

Change the top of the file (currently lines 1-4) from:

```python
import importlib.util
import shutil
import sys
from pathlib import Path
```

to:

```python
import importlib.util
import os
import shlex
import shutil
import sys
from pathlib import Path
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_servers.py`. Add `import pytest` at the top (after `import sys`) and add `_split_command` to the `app.servers` import:

Change lines 1-7 to:

```python
import sys

import pytest

from app.servers import SERVERS, detect_binaries, build_bench_command, resolve_bench_binary, README_FLAG_MAP
from app.servers import parse_serving_command, model_ref_from_flags
from app.servers import (is_spec_decoding_model, resolve_serving_binary, resolve_speed_bench_script,
                         build_server_command, build_speed_bench_command, speed_bench_deps_available,
                         parse_speed_bench_flags, validate_speed_bench_flags, speed_bench_default_flags,
                         _split_command)
```

Note: `ensure_speed_bench_script` is intentionally NOT imported yet — it is added to this import in Task 3 Step 2.

Append these tests at the end of the file:

```python
def test_split_command_windows_preserves_backslash_path():
    text = r"llama-server -m C:\Users\Ruben\.llmbench\gguf\model.gguf --spec-type draft-mtp"
    assert _split_command(text, windows=True) == [
        "llama-server", "-m", r"C:\Users\Ruben\.llmbench\gguf\model.gguf",
        "--spec-type", "draft-mtp",
    ]


def test_split_command_windows_quoted_path_with_spaces():
    text = r'llama-server -m "C:\Program Files\llama\model.gguf" -c 2048'
    assert _split_command(text, windows=True) == [
        "llama-server", "-m", r"C:\Program Files\llama\model.gguf", "-c", "2048",
    ]


def test_split_command_windows_flag_list():
    text = "--bench qualitative --category all --limit 1 --osl 528"
    assert _split_command(text, windows=True) == [
        "--bench", "qualitative", "--category", "all", "--limit", "1", "--osl", "528",
    ]


def test_split_command_windows_unclosed_quote_raises():
    with pytest.raises(ValueError) as exc:
        _split_command("llama-server --reasoning-budget-message $'\n", windows=True)
    assert "closing quotation" in str(exc.value)


def test_split_command_posix_default_matches_shlex():
    assert _split_command("llama-server -m /models/x.gguf -c 2048", windows=False) == [
        "llama-server", "-m", "/models/x.gguf", "-c", "2048",
    ]


def test_build_server_command_windows_path_roundtrip(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    tokens = build_server_command(
        r"llama-server -m C:\Users\Ruben\.llmbench\gguf\model.gguf --spec-type draft-mtp --port 9999",
        bin_dir=str(bin_dir))
    assert tokens[0] == str(bin_dir / "llama-server")
    assert r"C:\Users\Ruben\.llmbench\gguf\model.gguf" in tokens
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_servers.py -q`
Expected: FAIL with `ImportError: cannot import name '_split_command' from 'app.servers'`.

- [ ] **Step 4: Add the tokenizer functions to `backend/app/servers.py`**

Insert these functions immediately before `parse_speed_bench_flags` (after `speed_bench_default_flags`, ~line 133):

```python
def _split_windows(text: str) -> list[str]:
    """Split a command line the way Windows treats it: backslashes are literal
    (so C:\\Users\\... survives intact), double and single quotes group
    whitespace and are stripped, and an unclosed quote raises ValueError."""
    args: list[str] = []
    cur: list[str] = []
    quote: str | None = None
    for ch in text:
        if quote is not None:
            if ch == quote:
                quote = None
            else:
                cur.append(ch)
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch in " \t":
            if cur:
                args.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if quote is not None:
        raise ValueError("No closing quotation")
    if cur:
        args.append("".join(cur))
    return args


def _split_command(text: str, windows: bool | None = None) -> list[str]:
    """Tokenize a command string. With windows=True backslashes are kept literal
    and quotes group whitespace; otherwise it delegates to shlex.split (POSIX).
    Defaults to the current OS."""
    if windows is None:
        windows = os.name == "nt"
    if windows:
        return _split_windows(text)
    return shlex.split(text)
```

- [ ] **Step 5: Replace the three `shlex.split` call sites**

In `parse_speed_bench_flags` (lines ~136-153), remove the local `import shlex` line and change `tokens = shlex.split(text)` to `tokens = _split_command(text)`:

```python
def parse_speed_bench_flags(text: str) -> list[str]:
    """Split the user-edited flags string into tokens. Drop any leading bare
    tokens (so pasting the full command works) and normalize --flag=value."""
    tokens = _split_command(text)
    while tokens and not tokens[0].startswith("-"):
        tokens = tokens[1:]
    out: list[str] = []
    for tok in tokens:
        if tok.startswith("--") and "=" in tok:
            name, _, value = tok.partition("=")
            if value.startswith("-"):
                out.append(tok)
            else:
                out.extend([name, value])
        else:
            out.append(tok)
    return out
```

In `build_server_command` (lines ~205-229), remove the local `import shlex` and change `tokens = shlex.split(serving_command)` to `tokens = _split_command(serving_command)`:

```python
def build_server_command(serving_command: str, bin_dir: str | None = None) -> list[str]:
    """Turn the editable llama-server serving command into an executable token
    list: swap in the resolved binary and drop --port/--host (the runner injects
    its own). -p (--parallel) is left alone."""
    try:
        tokens = _split_command(serving_command)
    except ValueError as exc:
        raise ValueError(f"invalid serving command: {exc}") from exc
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

In `parse_serving_command` (lines ~279-301), remove the local `import shlex` and change `tokens = shlex.split(command)` to `tokens = _split_command(command)`:

```python
    try:
        tokens = _split_command(command)
    except ValueError as exc:
        raise ValueError(f"invalid serving command: {exc}") from exc
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_servers.py -q`
Expected: PASS (all tests, including the existing `test_build_server_command_malformed_raises_clear_error` and `test_parse_serving_command_malformed_raises_clear_error`).

- [ ] **Step 7: Commit**

```bash
git add backend/app/servers.py backend/tests/test_servers.py
git commit -m "fix: tokenize serving/bench commands Windows-safely"
```

---

### Task 2: Non-fatal `[speed-bench]` deps in launchers + CI

**Files:**
- Modify: `up.sh` (line 8)
- Modify: `scripts/up.ps1` (after line 132)
- Modify: `.github/workflows/ci.yml` (backend job)
- Modify: `README.md` (lines 22, 44, 46)

- [ ] **Step 1: Add best-effort install to `up.sh`**

After line 8 (`pip install -e '.[dev]'`), add:

```bash
pip install -e '.[speed-bench]' || echo "warning: speed-bench dependencies not installed; speed-bench unavailable (app still runs)."
```

- [ ] **Step 2: Add best-effort install to `scripts/up.ps1`**

After the core install block (after the `} finally { Pop-Location }` closing `}` on line 135), add:

```powershell
Write-Host '[up] installing optional speed-bench dependencies...'
& $venvPython -m pip install -e '.[speed-bench]'
if ($LASTEXITCODE -ne 0) {
    Write-Host '  warning: speed-bench deps failed to install; speed-bench will be unavailable (the app still runs).'
}
```

Note: `$ErrorActionPreference='Stop'` only affects cmdlets; native command exit codes are checked explicitly via `$LASTEXITCODE`. Because we do NOT `throw` here, startup continues on failure — this is the non-destructive guarantee.

- [ ] **Step 3: Add speed-bench deps install to CI**

In `.github/workflows/ci.yml`, after the `Install Windows deps` step (after line 30), add:

```yaml
      - name: Install speed-bench deps
        run: pip install -e ".[speed-bench]"
```

This runs on all three OSes in the backend matrix, proving the `datasets`/`pyarrow` wheels exist on Windows/macOS/Ubuntu for Python 3.12.

- [ ] **Step 4: Update `README.md`**

Replace line 22 (the `- To benchmark speculative-decoding...` bullet) with:

```markdown
- To benchmark speculative-decoding / MTP llama.cpp models, the app uses `speed-bench` (llama-server + `speed_bench.py`). It auto-discovers `speed_bench.py` next to `llama-server` in the llama.cpp source tree, or honors `LLMBENCH_SPEED_BENCH_SCRIPT`. If neither is found, the app downloads it into `~/.llmbench/speed-bench/` on the first MTP benchmark (best-effort). Its Python deps (`datasets`, `requests`, `tqdm`) are installed automatically by `up.sh`/`up.bat` as an optional step that never blocks startup. The speed-bench client always runs with `--limit 1 --category all --bench qualitative --osl 528`.
```

In the Windows paragraph (line 44), after "...resolves it from `LLMBENCH_LLAMA_CPP_BIN_DIR`, PATH, or the standard locations." append:

```markdown
 It also installs the optional speed-bench deps and the app provisions `speed_bench.py` automatically, so MTP benchmarks work with prebuilt Windows builds that ship no Python tools.
```

In the macOS paragraph (line 46), append:

```markdown
 Homebrew installs only compiled binaries (no `speed_bench.py`), so the app auto-downloads it on the first MTP benchmark.
```

- [ ] **Step 5: Verify launcher syntax statically**

Run: `bash -n up.sh`
Expected: no output (bash syntax OK).

Verify `scripts/up.ps1` by reading the added block: it sits after the `finally { Pop-Location }` closing brace, uses the already-defined `$venvPython` variable, and must NOT throw on failure. If `pwsh` is available on the dev box, additionally run `pwsh -NoProfile -Command "Get-Content scripts/up.ps1 | Out-Null"` to confirm it parses; otherwise the CI Windows backend job exercises the script end-to-end.

- [ ] **Step 6: Commit**

```bash
git add up.sh scripts/up.ps1 .github/workflows/ci.yml README.md
git commit -m "feat: install speed-bench deps best-effort in all launchers"
```

---

### Task 3: Backend lazy provisioning of `speed_bench.py`

> **Executed (2026-08-14):** commits `895d797` + `c75f0e2`. Post-review hardening: provisioning failures are now logged via `logger.warning`, and `_speed_bench_error(None)` mentions the auto-provision attempt + `LLMBENCH_SPEED_BENCH_SCRIPT` escape hatch. Test deviation (approved): `FakeResp` gained a no-op `raise_for_status()`. Added `test_ensure_speed_bench_script_downloads_at_most_once`.

**Files:**
- Modify: `backend/app/servers.py` (`detect_binaries` at ~52-58; `resolve_speed_bench_script` at ~95-112)
- Modify: `backend/app/api.py` (line 119 `/servers`; line 436 `generate`; line 489 `_rebuild_bench_command`)
- Test: `backend/tests/test_servers.py`
- Test: `backend/tests/test_api.py` (four tests that monkeypatch `app.api.resolve_speed_bench_script`)
- Modify: `README.md` (already updated in Task 2 Step 4)

- [ ] **Step 1: Add imports to `backend/app/servers.py`**

Change the top imports (lines 1-4, as edited in Task 1) to also add `threading` and `httpx`:

```python
import importlib.util
import os
import shlex
import shutil
import sys
import threading
from pathlib import Path

import httpx
```

- [ ] **Step 2: Add imports and the failing tests**

Append to `backend/tests/test_servers.py`. Add `import httpx` at the top (after `import pytest`) and add `ensure_speed_bench_script` to the `app.servers` import from Task 1:

Change lines 1-8 to:

```python
import sys

import httpx
import pytest

from app.servers import SERVERS, detect_binaries, build_bench_command, resolve_bench_binary, README_FLAG_MAP
from app.servers import parse_serving_command, model_ref_from_flags
from app.servers import (is_spec_decoding_model, resolve_serving_binary, resolve_speed_bench_script,
                         build_server_command, build_speed_bench_command, speed_bench_deps_available,
                         parse_speed_bench_flags, validate_speed_bench_flags, speed_bench_default_flags,
                         ensure_speed_bench_script, _split_command)
```

Append these tests at the end of the file:

```python
def test_detect_binaries_data_dir_discovery(tmp_path):
    provisioned = tmp_path / "data" / "speed-bench" / "speed_bench.py"
    provisioned.parent.mkdir(parents=True)
    provisioned.write_text("x")
    assert resolve_speed_bench_script(data_dir=str(tmp_path / "data")) == str(provisioned)


def test_ensure_speed_bench_script_downloads_into_data_dir(tmp_path, monkeypatch):
    class FakeResp:
        text = "#!/usr/bin/env python3\n"

    monkeypatch.setattr("app.servers.httpx.get", lambda *a, **k: FakeResp())
    data_dir = tmp_path / "data"
    script = ensure_speed_bench_script(data_dir=str(data_dir))
    assert script == str(data_dir / "speed-bench" / "speed_bench.py")
    assert (data_dir / "speed-bench" / "speed_bench.py").read_text() == "#!/usr/bin/env python3\n"


def test_ensure_speed_bench_script_download_failure_returns_none(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise httpx.HTTPError("offline")

    monkeypatch.setattr("app.servers.httpx.get", boom)
    assert ensure_speed_bench_script(data_dir=str(tmp_path / "data")) is None


def test_ensure_speed_bench_script_does_not_override_configured(tmp_path, monkeypatch):
    configured = tmp_path / "speed_bench.py"
    configured.write_text("x")
    monkeypatch.setattr(
        "app.servers.httpx.get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not download")),
    )
    assert ensure_speed_bench_script(configured=configured) == str(configured)


def test_ensure_speed_bench_script_finds_existing_script(tmp_path, monkeypatch):
    bin_dir = tmp_path / "build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    script = tmp_path / "tools" / "server" / "bench" / "speed-bench" / "speed_bench.py"
    script.parent.mkdir(parents=True)
    script.write_text("x")
    monkeypatch.setattr(
        "app.servers.httpx.get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not download")),
    )
    assert ensure_speed_bench_script(bin_dir=str(bin_dir)) == str(script)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_servers.py -q`
Expected: FAIL with `ImportError: cannot import name 'ensure_speed_bench_script' from 'app.servers'`.

- [ ] **Step 4: Extend `resolve_speed_bench_script` with a `data_dir` candidate**

Replace the current `resolve_speed_bench_script` (lines ~95-112) with:

```python
def resolve_speed_bench_script(bin_dir: str | None = None,
                               configured: str | Path | None = None,
                               data_dir: str | Path | None = None) -> str | None:
    """Locate speed_bench.py. Honors an explicitly configured path, otherwise
    auto-discovers it in the llama.cpp source tree that contains the resolved
    llama-server binary, then falls back to a copy previously provisioned into
    data_dir/speed-bench/."""
    if configured:
        p = Path(configured)
        if p.is_file():
            return str(p)
    server = resolve_serving_binary("llama.cpp", bin_dir)
    if server:
        bin_path = Path(server).parent
        for parent in [bin_path, *bin_path.parents[:3]]:
            candidate = parent / "tools" / "server" / "bench" / "speed-bench" / "speed_bench.py"
            if candidate.is_file():
                return str(candidate)
    if data_dir:
        provisioned = Path(data_dir) / "speed-bench" / "speed_bench.py"
        if provisioned.is_file():
            return str(provisioned)
    return None
```

- [ ] **Step 5: Add `ensure_speed_bench_script`**

Insert this right after `resolve_speed_bench_script`:

```python
SPEED_BENCH_SCRIPT_URL = (
    "https://raw.githubusercontent.com/ggml-org/llama.cpp/master/"
    "tools/server/bench/speed-bench/speed_bench.py"
)

_provision_lock = threading.Lock()
_provision_attempted: set[str] = set()


def ensure_speed_bench_script(bin_dir: str | None = None,
                              configured: str | Path | None = None,
                              data_dir: str | Path | None = None) -> str | None:
    """Like resolve_speed_bench_script, but if the script is missing (and no
    explicit configured path is set) it best-effort downloads the client from
    the llama.cpp repo into data_dir/speed-bench/ once per process. Never
    raises; returns the script path or None."""
    script = resolve_speed_bench_script(bin_dir, configured, data_dir)
    if script:
        return script
    if configured:
        return None
    if not data_dir:
        return None
    target = Path(data_dir) / "speed-bench" / "speed_bench.py"
    key = str(target)
    with _provision_lock:
        if key in _provision_attempted:
            return None
        _provision_attempted.add(key)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        resp = httpx.get(SPEED_BENCH_SCRIPT_URL, timeout=20)
        resp.raise_for_status()
        target.write_text(resp.text, encoding="utf-8")
    except Exception:
        return None
    return str(target) if target.is_file() else None
```

- [ ] **Step 6: Thread `data_dir` through `detect_binaries`**

Change `detect_binaries` (lines ~52-58) from:

```python
def detect_binaries(bin_dir: str | None = None) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for server_id in SERVERS:
        out[server_id] = resolve_bench_binary(server_id, bin_dir) is not None
    out["speed-bench"] = (resolve_speed_bench_script(bin_dir) is not None
                          and speed_bench_deps_available())
    return out
```

to:

```python
def detect_binaries(bin_dir: str | None = None,
                    data_dir: str | None = None) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for server_id in SERVERS:
        out[server_id] = resolve_bench_binary(server_id, bin_dir) is not None
    out["speed-bench"] = (resolve_speed_bench_script(bin_dir, data_dir=data_dir) is not None
                          and speed_bench_deps_available())
    return out
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_servers.py -q`
Expected: PASS. The existing `test_detect_missing` and `test_servers_endpoint` assertions are unaffected because they call `detect_binaries()` with no `data_dir` (defaults to `None`) and use set/dict equality that does not depend on `data_dir`.

- [ ] **Step 8: Wire `data_dir` and provisioning into `backend/app/api.py`**

Update the import (line 22-27) to include `ensure_speed_bench_script`:

```python
from app.servers import (build_bench_command, build_server_command, build_speed_bench_command,
                         detect_binaries, ensure_speed_bench_script, is_spec_decoding_model,
                         model_ref_from_flags, parse_serving_command, resolve_speed_bench_script,
                         speed_bench_deps_available, parse_speed_bench_flags,
                         speed_bench_default_flags, validate_speed_bench_flags,
                         SPEED_BENCH_BENCHES, SPEED_BENCH_CATEGORIES)
```

In `/servers` (line 115-119), change the `detect_binaries` call to pass `data_dir`:

```python
@router.get("/servers")
async def servers():
    s = _require_state()
    bin_dir = str(s.settings.llama_cpp_bin_dir) if s.settings.llama_cpp_bin_dir else None
    return {"readiness": detect_binaries(bin_dir, data_dir=str(s.settings.data_dir)),
            "hardware": detect_hardware()}
```

In `generate` (lines ~435-445), replace the `resolve_speed_bench_script` call with `ensure_speed_bench_script` run off the event loop (provisioning only happens when an MTP model is actually selected):

```python
        if uses_speed_bench:
            script = await asyncio.to_thread(
                ensure_speed_bench_script,
                bin_dir,
                configured=s.settings.speed_bench_script,
                data_dir=str(s.settings.data_dir),
            )
            if script and speed_bench_deps_available():
                flags_text = speed_bench_default_flags(s.settings.speed_bench_osl)
                cfg["bench_flags"] = flags_text
                cfg["bench_command"] = build_speed_bench_command(
                    script, parse_speed_bench_flags(flags_text),
                    output=str(s.settings.data_dir / "speed-bench.json"))
            else:
                cfg["bench_command"] = []
                cfg["bench_error"] = _speed_bench_error(script)
```

In `_rebuild_bench_command` (line 489), replace the `resolve_speed_bench_script` call:

```python
        script = ensure_speed_bench_script(
            bin_dir,
            configured=s.settings.speed_bench_script,
            data_dir=str(s.settings.data_dir),
        )
```

- [ ] **Step 9: Update the four api tests that monkeypatch the resolver**

In `backend/tests/test_api.py`, change every `monkeypatch.setattr("app.api.resolve_speed_bench_script", ...)` to `monkeypatch.setattr("app.api.ensure_speed_bench_script", ...)`. There are exactly four occurrences, at lines ~1304, ~1322, ~1350, ~1368:

```python
    monkeypatch.setattr("app.api.ensure_speed_bench_script", lambda *a, **k: "/tmp/speed_bench.py")
    ...
    monkeypatch.setattr("app.api.ensure_speed_bench_script", lambda *a, **k: None)
    ...
    monkeypatch.setattr("app.api.ensure_speed_bench_script", lambda *a, **k: str(script))
    ...
    monkeypatch.setattr("app.api.ensure_speed_bench_script", lambda *a, **k: "/tmp/speed_bench.py")
```

The tests that exercise real discovery (`test_generate_configs_llama_spec_readme_uses_speed_bench`, `test_generate_speed_bench_uses_configured_osl`) keep working because `ensure_speed_bench_script` resolves the on-disk source-tree script via `resolve_speed_bench_script` without any download.

- [ ] **Step 10: Run the full backend suite**

Run: `cd backend && python -m pytest tests/ -q`
Expected: PASS (all api, servers, flags, benchmark tests).

- [ ] **Step 11: Commit**

```bash
git add backend/app/servers.py backend/app/api.py backend/tests/test_servers.py backend/tests/test_api.py
git commit -m "feat: auto-provision speed_bench.py into data dir on MTP benchmarks"
```

---

### Task 4: Full verification

- [ ] **Step 1: Frontend typecheck + unit tests**

Run: `cd frontend && npx tsc -b && npm test`
Expected: PASS (no frontend code changed; confirms nothing regressed).

- [ ] **Step 2: Playwright e2e**

Run: `cd frontend && npm run e2e`
Expected: PASS (uses its own mock-server via `webServer`; no real backend needed).

- [ ] **Step 3: Backend suite (already covered in Task 3 Step 10)**

Run: `cd backend && python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 4: Push the branch and confirm CI**

```bash
git push origin feature/cross-platform-pty-support
```

Expected: CI runs all 5 jobs (backend on ubuntu/windows/macos + frontend + e2e) and all pass, including the new `Install speed-bench deps` step proving the wheels exist on all OSes.

- [ ] **Step 5: Manual Windows verification (by user)**

On the Windows machine (Python 3.14): run `down.bat` first (clears the stale port-8000 uvicorn), then `up.bat`. Confirm:
1. The `[up] installing optional speed-bench dependencies...` line prints and does not abort on any failure.
2. Benchmark an MTP model (e.g. `Qwen3.6-27B-MTP-...`): the generated config shows the SPEED-BENCH badge, the flags textarea is editable, and the run completes through `speed_bench.py`.
3. `~/.llmbench/speed-bench/speed_bench.py` exists after the first MTP benchmark (auto-provisioned).
4. If the user already has the llama.cpp source tree next to `llama-server`, discovery finds it there instead of downloading.
