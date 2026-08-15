# up.ps1 - Windows counterpart of up.sh.
# Resolves an existing llama.cpp install (installing llama.cpp is the user's
# responsibility), creates the backend venv, installs deps, and starts uvicorn +
# the Vite dev server in the background with hidden windows.
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

function Abort-LlamaCpp {
    Write-Host ''
    Write-Host '  llama.cpp (llama-bench + llama-server) is required for benchmarks.'
    Write-Host '  Installing llama.cpp is your responsibility (this app does not install it).'
    Write-Host '  Download a prebuilt Windows build from: https://github.com/ggml-org/llama.cpp/releases'
    Write-Host '  Then point up.bat at it (LLMBENCH_LLAMA_CPP_BIN_DIR, PATH, or the path prompt).'
    Write-Host '  Startup aborted.'
    exit 1
}

# Interactive loop for a directory containing llama-bench.exe/llama-server.exe.
# Aborts on q/c/cancel; ~ expands to %USERPROFILE%; invalid dirs offer
# (r) another path, (q) cancel.
function Read-CustomLocation {
    :outer while ($true) {
        $input = Read-Host '  Full path to the directory containing llama-bench.exe and llama-server.exe (q to cancel)'
        if ($input -match '^(q|quit|c|cancel)$') { Abort-LlamaCpp }
        if (-not $input) {
            Write-Host '  No path entered.'
            continue
        }
        $expanded = $input -replace '^~', $env:USERPROFILE
        if (Test-BinDir $expanded) {
            Write-Host "  llama.cpp found at $expanded"
            return $expanded
        }
        Write-Host "  No llama-bench.exe/llama-server.exe executables found in: $expanded"
        while ($true) {
            $next = Read-Host '  What next? (r) try another path, (q) cancel'
            switch -Regex ($next.Trim().ToLower()) {
                '^(r|retry)$' { break outer }
                '^(q|quit|c|cancel|)$' { Abort-LlamaCpp }
                default { Write-Host '  Please choose r or q.' }
            }
        }
    }
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
    $env:LLMBENCH_LLAMA_CPP_BIN_DIR = $null

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
        $reply = Read-Host '  How do you want to provide llama.cpp? (1) already installed elsewhere, (q) cancel'
        switch -Regex ($reply.Trim().ToLower()) {
            '^(1)$' { $binDir = Read-CustomLocation }
            '^(q|quit|c|cancel|)$' { Abort-LlamaCpp }
            default { Write-Host '  Please choose 1 or q (cancel).' }
        }
    }
    return $binDir
}

# --- main ----------------------------------------------------------------

$binDir = Resolve-LlamaCpp
if ($binDir) { $env:LLMBENCH_LLAMA_CPP_BIN_DIR = $binDir }

$pyCmd = Get-Command py -ErrorAction SilentlyContinue
$pythonArgs = @()
if ($pyCmd) {
    $pyExe = $pyCmd.Source
    $pythonArgs = @('-3')
} else {
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pyCmd) {
        Write-Host '  Python 3 was not found (py/python). Install it from https://www.python.org/downloads/'
        exit 1
    }
    $pyExe = $pyCmd.Source
}

Push-Location $backendDir
try {
    if (-not (Test-Path $venvPython)) {
        Write-Host '[up] creating backend virtualenv...'
        & $pyExe @pythonArgs -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'venv creation failed' }
    }

    Write-Host '[up] installing backend dependencies...'
    & $venvPython -m pip install -e '.[dev,win]'
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
} finally {
    Pop-Location
}

Write-Host '[up] installing optional speed-bench dependencies...'
& $venvPython -m pip install -e '.[speed-bench]'
if ($LASTEXITCODE -ne 0) {
    Write-Host '  warning: speed-bench deps failed to install; speed-bench will be unavailable (the app still runs).'
}

Write-Host '[up] starting backend (uvicorn on :8000)...'
$backendLog = Join-Path $backendDir 'uvicorn.log'
$backendErr = Join-Path $backendDir 'uvicorn.log.err'
$backend = Start-Process -FilePath $venvPython `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--port', '8000' `
    -WorkingDirectory $backendDir -WindowStyle Hidden `
    -RedirectStandardOutput $backendLog -RedirectStandardError $backendErr -PassThru

Write-Host '[up] resolving npm for the frontend...'
$npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCmd) {
    Write-Host ''
    Write-Host '  npm was not found. Node.js is required for the frontend.'
    Write-Host '  Install Node.js LTS from https://nodejs.org/, then restart the'
    Write-Host '  terminal (or run "nvm use" if you use nvm-windows).'
    Write-Host '  Startup aborted.'
    exit 1
}
Write-Host "[up] npm found at $($npmCmd.Source)"

Write-Host '[up] starting frontend (vite on :5173)...'
$frontendLog = Join-Path $frontendDir 'vite.log'
$frontendErr = Join-Path $frontendDir 'vite.log.err'
$npmArgs = '""{0}" install && "{0}" run dev"' -f $npmCmd.Source
$frontend = Start-Process -FilePath 'cmd.exe' `
    -ArgumentList '/c', $npmArgs `
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