# Windows `up.bat` / `down.bat` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Implementation delta (from verification):** the missing-llama.cpp branch of `up.ps1`
now offers a **full source build** (`(2) install it now`) mirroring the Linux
`scripts/ensure-llama-cpp.sh`, instead of only prompting for a path / pointing at the
prebuilt releases. `scripts/up.ps1` is the source of truth.

**Implementation delta 2 (from verification):** `up.ps1` now also offers to install the
**build requirements** when they are missing, mirroring the Linux
`_check_requirements` flow: `Install-MissingRequirements` detects git, cmake, and an
MSVC C++ toolchain (via `vswhere`) and offers `winget install` (`Git.Git`,
`Kitware.CMake`, `Microsoft.VisualStudio.2022.BuildTools` with the VCTools workload)
gated by `y/n/q`; a detected NVIDIA GPU with no CUDA toolkit prompts to install
`Nvidia.CUDA` via winget. Aborts with the manual-install URLs when winget is absent or
the user declines.

**Goal:** Provide Windows equivalents of the Linux `up.sh`/`down.sh` workflow via thin `.bat` launchers + PowerShell scripts: resolve llama.cpp (source build offered when missing) → venv + deps → start uvicorn (8000) and Vite (5173) in the background → `down.bat` stops both.

**Architecture:** `up.bat`/`down.bat` call `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\up.ps1` / `scripts\down.ps1`. Mirrors `up.sh` sourcing `scripts/ensure-llama-cpp.sh`. No backend/frontend code changes.

**Tech Stack:** Batch launcher (cmd.exe) + PowerShell (Windows 10/11 native). No Linux counterpart needed.

---

## File Structure

- **Create:** `up.bat`, `down.bat`, `scripts\up.ps1`, `scripts\down.ps1`
- **Modify:** `README.md` (Windows note in Start/Stop section)
- **Docs:** `docs/superpowers/specs/2026-08-13-windows-up-down-bat-design.md` (design), this plan.

---

### Task 1: Create the launchers `up.bat` and `down.bat`

**Files:**
- Create: `up.bat`
- Create: `down.bat`

- [ ] **Step 1: Create `up.bat`**

```bat
@echo off
rem Windows counterpart of up.sh - starts backend + frontend.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\up.ps1"
```

- [ ] **Step 2: Create `down.bat`**

```bat
@echo off
rem Windows counterpart of down.sh - stops backend + frontend.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\down.ps1"
```

- [ ] **Step 3: Commit**

```bash
git add up.bat down.bat
git commit -m "feat: add Windows up.bat/down.bat launchers for the app workflow"
```

---

### Task 2: Create `scripts\up.ps1`

**Files:**
- Create: `scripts\up.ps1`

- [ ] **Step 1: Create the script**

```powershell
# up.ps1 - Windows counterpart of up.sh.
# Resolves llama.cpp (simplified), creates the backend venv, installs deps, and
# starts uvicorn + the Vite dev server in the background with hidden windows.
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root 'backend'
$frontendDir = Join-Path $root 'frontend'
$venvPython = Join-Path $backendDir '.venv\Scripts\python.exe'

function Test-BinDir([string]$dir) {
    if (-not $dir -or -not (Test-Path $dir)) { return $false }
    return (Test-Path (Join-Path $dir 'llama-bench.exe')) -and `
           (Test-Path (Join-Path $dir 'llama-server.exe'))
}

function Resolve-LlamaCpp {
    $binDir = $env:LLMBENCH_LLAMA_CPP_BIN_DIR
    if (Test-BinDir $binDir) {
        Write-Host "[up] using LLMBENCH_LLAMA_CPP_BIN_DIR=$binDir"
        return $binDir
    }
    if ($binDir) {
        Write-Host "[up] warning: LLMBENCH_LLAMA_CPP_BIN_DIR is set but has no llama-bench.exe/llama-server.exe: $binDir"
    }

    $onPath = (Get-Command llama-bench -ErrorAction SilentlyContinue) -and `
              (Get-Command llama-server -ErrorAction SilentlyContinue)
    if ($onPath) {
        Write-Host '[up] llama.cpp found on PATH'
        return $null
    }

    foreach ($candidate in @("$env:USERPROFILE\llama.cpp\build\bin", 'C:\llama.cpp\build\bin')) {
        if (Test-BinDir $candidate) {
            Write-Host "[up] llama.cpp found at $candidate"
            return $candidate
        }
    }

    Write-Host ''
    Write-Host '  llama.cpp provides llama-bench (benchmarking) and llama-server (serving).'
    Write-Host '  It was not found on PATH or in the standard install locations.'
    if ([Console]::IsInputRedirected) {
        Write-Host ''
        Write-Host '  llama.cpp was not found and up.bat is not running interactively.'
        Write-Host '  Download prebuilt Windows builds from: https://github.com/ggml-org/llama.cpp/releases'
        Write-Host '  Then re-run up.bat from a terminal.'
        exit 1
    }

    while (-not $binDir) {
        $input = Read-Host '  Full path to the directory containing llama-bench.exe and llama-server.exe (q to cancel)'
        if ($input -match '^(q|quit|c|cancel)$') {
            Write-Host ''
            Write-Host '  llama.cpp (llama-bench + llama-server) is required for benchmarks.'
            Write-Host '  Startup aborted.'
            exit 1
        }
        if ($input) {
            $expanded = $input -replace '^~', $env:USERPROFILE
            if (Test-BinDir $expanded) {
                $binDir = $expanded
                Write-Host "  llama.cpp found at $binDir"
            } else {
                Write-Host "  No llama-bench.exe/llama-server.exe executables found in: $expanded"
                Write-Host '  Download prebuilt Windows builds from: https://github.com/ggml-org/llama.cpp/releases'
            }
        }
    }
    return $binDir
}

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) { return 'py -3' }
    if (Get-Command python -ErrorAction SilentlyContinue) { return 'python' }
    Write-Host '  Python 3 was not found (py/python). Install it from https://www.python.org/downloads/'
    exit 1
}

# --- main ----------------------------------------------------------------

$binDir = Resolve-LlamaCpp
if ($binDir) { $env:LLMBENCH_LLAMA_CPP_BIN_DIR = $binDir }

$py = Find-Python

Write-Host '[up] creating backend virtualenv...'
if (-not (Test-Path $venvPython)) {
    Push-Location $backendDir
    try {
        Invoke-Expression "$py -m venv .venv"
        if ($LASTEXITCODE -ne 0) { throw 'venv creation failed' }
    } finally {
        Pop-Location
    }
}

Write-Host '[up] installing backend dependencies...'
& $venvPython -m pip install -e "$root\backend[dev]"
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

Write-Host '[up] starting backend (uvicorn on :8000)...'
$backendLog = Join-Path $backendDir 'uvicorn.log'
$backendErr = Join-Path $backendDir 'uvicorn.log.err'
$backend = Start-Process -FilePath $venvPython `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--port', '8000' `
    -WorkingDirectory $backendDir -WindowStyle Hidden `
    -RedirectStandardOutput $backendLog -RedirectStandardError $backendErr -PassThru

Write-Host '[up] starting frontend (vite on :5173)...'
$frontendLog = Join-Path $frontendDir 'vite.log'
$frontendErr = Join-Path $frontendDir 'vite.log.err'
$frontend = Start-Process -FilePath 'cmd.exe' `
    -ArgumentList '/c', '"npm install && npm run dev"' `
    -WorkingDirectory $frontendDir -WindowStyle Hidden `
    -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErr -PassThru

Start-Sleep -Seconds 2

if ($backend.HasExited) {
    Write-Host "  backend exited early; see $backendErr"
}
if ($frontend.HasExited) {
    Write-Host "  frontend exited early; see $frontendErr"
}

Write-Host ''
Write-Host 'Backend and Frontend running...'
Write-Host 'Open http://localhost:5173.'
```

- [ ] **Step 2: Commit**

```bash
git add scripts/up.ps1
git commit -m "feat: add PowerShell startup workflow for Windows (up.ps1)"
```

---

### Task 3: Create `scripts\down.ps1`

**Files:**
- Create: `scripts\down.ps1`

- [ ] **Step 1: Create the script**

```powershell
# down.ps1 - Windows counterpart of down.sh.
# Stops the uvicorn backend and the Vite frontend started by up.bat.
$ErrorActionPreference = 'Stop'

$targets = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match 'uvicorn|vite'
}

foreach ($proc in $targets) {
    try {
        Stop-Process -Id $proc.ProcessId -Force
        Write-Host "Stopped $($proc.Name) (PID $($proc.ProcessId))"
    } catch {
        Write-Host "Could not stop $($proc.Name) (PID $($proc.ProcessId)): $($_.Exception.Message)"
    }
}

if (-not $targets) {
    Write-Host 'No uvicorn/vite processes found.'
}

Write-Host ''
Write-Host 'Remember to execute:'
Write-Host 'deactivate'
```

- [ ] **Step 2: Commit**

```bash
git add scripts/down.ps1
git commit -m "feat: add PowerShell shutdown workflow for Windows (down.ps1)"
```

---

### Task 4: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a Windows note to the Start/Stop section**

After the existing `./down.sh` paragraph (around line 42), add:

```markdown
**Windows:** use `up.bat` and `down.bat` instead of `up.sh`/`down.sh`. They run the
same workflow via PowerShell (`scripts\up.ps1` / `scripts\down.ps1`): llama.cpp is
resolved from `LLMBENCH_LLAMA_CPP_BIN_DIR`, PATH, or the standard locations; if it
is missing, `up.bat` prompts for a path or points at the prebuilt
[llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases). `down.bat`
stops the uvicorn and vite processes.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document Windows up.bat/down.bat workflow"
```

---

### Task 5: Verify

**Files:** none changed here — verification only.

- [ ] **Step 1: Line-by-line review**

Review all four new files for: `%~dp0` quoting in launchers, PowerShell quoting of
`.[dev]` / `cmd /c` argument, redirect file names, and the `Where-Object` filter
semantics. No local PowerShell on the Linux dev box, so execution cannot be tested
here.

- [ ] **Step 2: Full local suite (unchanged app code must stay green)**

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/python -m pytest
cd frontend && npx tsc -b && npx vitest run
cd frontend && npx playwright test
```

Expected: all pass (the branch only adds `.bat`/`.ps1` files and a README paragraph).

- [ ] **Step 3: Manual Windows checklist (user, on a Windows machine)**

1. Fresh checkout, run `up.bat` with no llama.cpp → expect path prompt + release URL.
2. Set `LLMBENCH_LLAMA_CPP_BIN_DIR` to a valid dir (or add llama.cpp to PATH) → run
   `up.bat` → expect venv creation, deps install, both servers starting.
3. Verify `backend\uvicorn.log` and `frontend\vite.log`; open http://localhost:5173.
4. Run `down.bat` → expect both processes stopped; ports 8000/5173 free.
5. Run `down.bat` again → expect "No uvicorn/vite processes found."

---

## Post-implementation

- [ ] **Step 1: PR** — per AGENTS.md: `git push origin feature/windows-up-down-bat`, open a PR against `main`, wait for CI + security scans before merge.
- [ ] **Step 2: Cleanup** — delete the branch after merge.