# Cross-Platform Support (Windows + macOS) — Design

**Date:** 2026-08-14
**Status:** Approved by user (via plan approval)

## Problem

The app runs on Linux but fails on Windows and partially degrades on macOS.

Confirmed failures from the Windows logs:

- `backend/uvicorn.log.err`:
  `ModuleNotFoundError: No module named 'fcntl'` at `backend/app/api.py:2`.
  `api.py` imports `fcntl` and `termios` at module top level and uses
  `os.openpty()`. All three are POSIX-only: they exist on Linux and macOS but
  not on Windows, so the backend dies at import time on Windows.
- `frontend/vite.log.err`:
  `'npm' is not recognized as an internal or external command`. The frontend
  itself is standard Vite/React and fully cross-platform; the failure is in
  `scripts/up.ps1`, which spawns `cmd.exe /c "npm install && npm run dev"`
  with a PATH that lacks `npm.cmd`.

Known macOS degradations (non-crashing):

- `backend/app/hardware.py:36` reads `/proc/meminfo` — Linux-only file; on
  macOS/Windows the fallback returns RAM = 0.0, so hardware-fit verdicts are
  wrong.
- `nvidia-smi` is absent on Apple Silicon (product premise is NVIDIA/CUDA, so
  macOS GPU benchmarking is out of scope; the app must still boot and serve).

## Goal

Make the app boot and function on Linux, Windows, and macOS:

- Backend starts and the download console works on Windows.
- RAM detection is cross-platform.
- llama.cpp binary resolution works on Windows (`.exe`).
- `up.ps1` starts the frontend reliably on Windows.
- CI guards against regressions with `windows-latest` / `macos-latest`.
- **Linux behavior is preserved byte-for-byte on the POSIX pty path.**

## Decisions (confirmed with user)

- **Windows download console:** use **ConPTY via `pywinpty`** so tqdm progress
  bars render like Linux. Verified `pywinpty 3.0.5` ships `cp314` Windows
  wheels (the user's Windows install is Python 3.14).
- **pywinpty packaging:** **Windows-only pip extra** — `[project.optional-dependencies] win = ["pywinpty>=3.0.5"]`, installed by `up.ps1`. Linux/macOS never install it.
- **RAM detection:** add `psutil` to main `dependencies` and use
  `psutil.virtual_memory().total`. Verified byte-exact vs `/proc/meminfo`
  MemTotal on this Linux box (`25023336448` bytes both). psutil is already a
  transitive dep in the venv (7.2.2) but was undeclared; declaring it makes the
  contract explicit for Windows/macOS installs.
- **Frontend launcher:** resolve `npm.cmd` explicitly in `up.ps1` and fail with
  an actionable message when missing.

## Design

### 1. New `backend/app/pty_stream.py` — platform abstraction (core fix)

Introduce a `DownloadPty` class that hides the POSIX-pty vs Windows-ConPTY
difference behind a small async interface. This is the only place that touches
terminal plumbing; `api.py`'s raw-fd helpers collapse into it.

Interface:

- `spawn(cmd: list[str], env: dict[str, str]) -> None`
- `async read_events() -> AsyncIterator[tuple[str, str]]` — yields
  `(kind, text)` from `TtyStream` (reuses existing parser, unchanged).
- `cancel() -> None` — best-effort interrupt of the child.
- `async wait() -> int` — child exit code.
- `close() -> None` — release the terminal.

**`PosixPtyStream`** (Linux/macOS): *verbatim move* of the current `api.py`
logic — `os.openpty()`, lazy `fcntl.ioctl(..., termios.TIOCSWINSZ, ...)`,
`asyncio.create_subprocess_exec(..., start_new_session=True)`, master read on a
background thread into an asyncio queue. No top-level `fcntl`/`termios`
imports; they are imported inside the POSIX branch. **Linux/macOS behavior is
unchanged.**

**`ConPtyStream`** (Windows 10+): `pywinpty` `PtyProcess.spawn(cmd,
backend=Backend.ConPTY)`. `proc.read()` returns a decoded UTF-8 `str` and is
blocking, so it runs on the same thread → asyncio queue bridge; the text is
encoded back to bytes (`text.encode("utf-8", errors="replace")`) before feeding
`TtyStream.feed()` so the shared parser stays byte-based. `cancel()` uses
`proc.terminate()` (no SIGINT on Windows). Requires the `win` extra.

A factory `open_download_pty(cmd, env)` selects `ConPtyStream` on `sys.platform
== "win32"`, else `PosixPtyStream`.

### 2. `backend/pyproject.toml`

- Add `psutil` to `dependencies`.
- Add `[project.optional-dependencies] win = ["pywinpty>=3.0.5"]`.

### 3. `backend/app/hardware.py`

- `_ram_total_gb()` uses `psutil.virtual_memory().total`. Drop the
  `/proc/meminfo` fast path (psutil is byte-identical on Linux and cross-
  platform). `test_detect_hardware_shape` stays green.

### 4. `backend/app/servers.py`

- `resolve_bench_binary` / `resolve_serving_binary`: when `bin_dir` is set,
  also accept `llama-bench.exe` / `llama-server.exe` (Windows). Checking both
  names is harmless on POSIX.

### 5. `backend/app/api.py`

- Replace the `_open_pty` / `_spawn_pty` / `_read_master` /
  `_stream_download_output` helpers with `open_download_pty` usage in
  `_download_job`.
- Remove top-level `import fcntl` / `import termios` (moved into
  `pty_stream.py`).
- Cancel path: POSIX keeps `send_signal(SIGINT)` + 5s force-kill fallback;
  Windows uses ConPTY `terminate()` + force-kill fallback.

### 6. `scripts/up.ps1`

- Install backend deps with the `win` extra: `.venv\Scripts\python.exe -m pip
  install -e ".[win]"`.
- Before spawning the frontend, resolve `npm.cmd` via `Get-Command npm`; if
  missing, abort with an actionable message (install Node / restart terminal /
  `nvm use`) and do not start a broken `cmd.exe`. Spawn using the resolved
  `npm.cmd` full path.

### 7. Tests + CI

- `backend/tests/test_api.py` `test_open_pty_sets_a_terminal_window_size` →
  `@pytest.mark.skipif(sys.platform == "win32")`.
- Audit `test_api.py` / `test_spawn.py` for other pty-coupled tests that need
  the same guard.
- Add `windows-latest` and `macos-latest` to the backend pytest CI job
  (`.github/workflows/ci.yml`). Frontend CI already runs on Node/Vite which is
  cross-platform; e2e stays `ubuntu-latest`.

## Files

- **Create:** `backend/app/pty_stream.py`.
- **Modify:** `backend/pyproject.toml`, `backend/app/hardware.py`,
  `backend/app/servers.py`, `backend/app/api.py`, `scripts/up.ps1`,
  `backend/tests/test_api.py`, `.github/workflows/ci.yml`, `README.md`
  (Windows/macOS run notes).

## Testing

- Local Linux suite must stay green: backend `pytest`, frontend `tsc -b` +
  `vitest run`, Playwright `e2e`.
- CI: add backend pytest jobs on `windows-latest` and `macos-latest`.
- Manual Windows/macOS checklist per the existing `up.bat`/`down.bat` spec:
  boot backend + frontend, run a download (progress bars on Windows via
  ConPTY), run a benchmark, verify `down.bat` stops both processes.

## Out of scope

- macOS GPU benchmarking (Apple Silicon / Metal) — the product targets NVIDIA
  CUDA. The app must boot and serve there, but GPU-fit semantics are unchanged.
- ConPTY on Windows versions before Windows 10.
