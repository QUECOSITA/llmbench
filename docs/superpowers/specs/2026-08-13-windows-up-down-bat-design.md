# Windows `up.bat` / `down.bat` — Design

**Date:** 2026-08-13
**Status:** Approved by user (via plan approval)

## Problem

The Linux workflow is driven by `up.sh` (starts backend + frontend after resolving
llama.cpp) and `down.sh` (stops uvicorn + vite). On Windows there is no equivalent,
so the same workflow is not available without manual, OS-specific steps.

## Goal

Provide Windows equivalents named `up.bat` / `down.bat` that run the **same workflow**
on Windows: resolve llama.cpp → create/activate the backend venv → install deps →
start `uvicorn app.main:app --port 8000` and the Vite frontend (`npm install && npm
run dev`, port 5173) in the background → on `down.bat`, stop both processes.

## Decisions (confirmed with user)

- **File format:** thin `.bat` launchers that call PowerShell scripts
  (`scripts\up.ps1`, `scripts\down.ps1`) via `powershell -NoProfile -ExecutionPolicy
  Bypass -File`. Chosen over pure batch and over embedded-PowerShell-in-batch because
  PowerShell is native on Windows 10/11 and is far more readable/maintainable for the
  resolver, background processes, and process killing. Mirrors how `up.sh` sources
  `scripts/ensure-llama-cpp.sh`.
- **llama.cpp resolution:** *existing-install resolver only, no auto-install* — check
  `LLMBENCH_LLAMA_CPP_BIN_DIR`, then PATH, then standard dirs, then interactive prompt
  for the path to an existing install. Installing llama.cpp is the **user's
  responsibility** (prebuilt Windows builds from the ggml-org releases). When missing,
  the interactive flow offers **(1) already installed elsewhere** (custom path) or
  **(q) cancel**. Non-interactive runs point the user at the ggml-org prebuilt releases
  and abort. No source build, no build-requirement install.
- **Background processes:** `Start-Process` with hidden windows and logs to
  `backend\uvicorn.log` (+ `.err`) and `frontend\vite.log` (+ `.err`), matching the
  nohup-style detached behavior of `up.sh`.
- **Non-interactive safety:** if stdin is redirected, skip prompts and abort with the
  release-page message (mirrors `up.sh`'s TTY guard).
- **Process kill:** `down.bat` matches processes by command line (`uvicorn` /
  `vite`) via `Get-CimInstance Win32_Process` — the `pkill -f` equivalent. No blanket
  `taskkill /IM node.exe`.
- **Out of scope:** `show.sh` (`fg %2` is bash job control, no Windows equivalent).

## llama.cpp resolution flow (`up.ps1`)

A directory "contains llama.cpp" iff both `llama-bench.exe` and `llama-server.exe`
exist there. Resolution order:

1. `$env:LLMBENCH_LLAMA_CPP_BIN_DIR` if valid → use it.
2. PATH: both binaries resolve via `Get-Command` → leave env var unset (the backend
   falls back to PATH, same as the Linux script).
3. Standard dirs: `%USERPROFILE%\llama.cpp\build\bin`, `C:\llama.cpp\build\bin` →
   first valid wins → export.
4. Missing (installing llama.cpp is the user's responsibility):
   - stdin redirected → print message + prebuilt release URL, `exit 1`.
   - else interactive menu: `(1) already installed elsewhere, (q) cancel`.
     - `1` → `Read-Host` loop for a full path (accepts `q`/`c`/`cancel` to abort,
       leading `~` expands to `%USERPROFILE%`); invalid dir offers `(r) try another
       path, (q) cancel`.
     - `q` → abort message telling the user to install llama.cpp themselves (prebuilt
       releases URL) and point `up.bat` at it.
   - found → `$env:LLMBENCH_LLAMA_CPP_BIN_DIR = $dir` (inherited by child processes).

## Startup flow (`up.ps1`)

1. Resolve llama.cpp (above).
2. Python: prefer `py -3`, fall back to `python`; if neither, message + `exit 1`.
3. In `backend\`: `py -m venv .venv`, then
   `.venv\Scripts\python.exe -m pip install -e ".[dev]"` (venv python so child
   processes don't need an activated environment). Non-zero exit → abort.
4. Backend: `Start-Process` `.venv\Scripts\uvicorn.exe app.main:app --port 8000`
   with `-WorkingDirectory backend`, `-WindowStyle Hidden`, logs →
   `backend\uvicorn.log` / `backend\uvicorn.log.err`.
5. Frontend: `Start-Process cmd.exe` `/c "npm install && npm run dev"` with
   `-WorkingDirectory frontend`, `-WindowStyle Hidden`, logs →
   `frontend\vite.log` / `frontend\vite.log.err`.
6. `Start-Sleep 2`, then print `Backend and Frontend running...` and
   `Open http://localhost:5173.`

## Stop flow (`down.ps1`)

- `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn|vite' }`
  → `Stop-Process -Force`. Targeted; mirrors `pkill -f uvicorn` / `pkill -f vite`.
- Print the `deactivate` reminder for any manually-activated venv consoles (keeps
  `down.sh` parity).

## Error handling

- llama.cpp missing → clear message + abort (`exit 1`); servers never start.
- `pip install` non-zero → abort before starting servers.
- `$ErrorActionPreference = 'Stop'` with a `finally` block so a mid-start failure
  best-effort stops any already-started backend/frontend before exiting non-zero.

## Files

- **Create:** `up.bat`, `down.bat`, `scripts\up.ps1`, `scripts\down.ps1`.
- **Modify:** `README.md` — Windows note in the Start/Stop section.

## Testing

- No PowerShell on the Linux dev box (`pwsh`/`powershell` not available), so no local
  syntax/execution check; verification is careful review plus a manual Windows
  checklist (first run with missing llama.cpp → path prompt + release URL, no install
  option; run with llama.cpp present; verify logs; `down.bat` stops both processes,
  ports 8000/5173 free).
- Full local suite (backend `pytest`, frontend `tsc -b` + `vitest run`, Playwright
  `e2e`) must stay green — none of the touched files are part of it.