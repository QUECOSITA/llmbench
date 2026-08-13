# up.ps1 - Windows counterpart of up.sh.
# Resolves llama.cpp (offers a full source build when missing), creates the
# backend venv, installs deps, and starts uvicorn + the Vite dev server in the
# background with hidden windows.
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
    Write-Host '  Startup aborted.'
    exit 1
}

# Returns $true for yes, $false for no; aborts on cancel.
function Ask-YesNo([string]$prompt) {
    while ($true) {
        $reply = Read-Host "  $prompt [y/n/q]"
        switch -Regex ($reply.Trim().ToLower()) {
            '^(y|yes)$' { return $true }
            '^(n|no|)$' { return $false }
            '^(q|quit|c|cancel)$' { Abort-LlamaCpp }
            default { Write-Host '  Please answer y (yes), n (no), or q (cancel).' }
        }
    }
}

# Run a command, offering retry or cancel if it fails.
function Invoke-RunStep([string]$desc, [scriptblock]$action) {
    while ($true) {
        Write-Host "  $desc..."
        & $action
        if ($LASTEXITCODE -eq 0) { return }
        Write-Host "  Command failed: $desc"
        if (Ask-YesNo 'Retry?') { continue }
        Abort-LlamaCpp
    }
}

# Interactive loop for a directory containing llama-bench.exe/llama-server.exe.
# Aborts on q/c/cancel; ~ expands to %USERPROFILE%; invalid dirs offer
# (r) another path, (i) install now, (q) cancel.
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
            $next = Read-Host '  What next? (r) try another path, (i) install now, (q) cancel'
            switch -Regex ($next.Trim().ToLower()) {
                '^(r|retry)$' { break outer }
                '^(i|install)$' { return Install-LlamaCpp }
                '^(q|quit|c|cancel|)$' { Abort-LlamaCpp }
                default { Write-Host '  Please choose r, i, or q.' }
            }
        }
    }
}

# Full source build of llama.cpp into %USERPROFILE%\llama.cpp (mirrors the
# Linux scripts/ensure-llama-cpp.sh _do_install). Sets LLMBENCH_LLAMA_CPP_BIN_DIR
# and returns the bin dir on success; falls back to a custom location otherwise.
function Install-LlamaCpp {
    $target = Join-Path $env:USERPROFILE 'llama.cpp'
    $buildDir = Join-Path $target 'build'
    $binDir = Join-Path $buildDir 'bin'
    $buildType = 'cpu'

    Write-Host ''
    Write-Host '  Preparing a llama.cpp source build.'
    Write-Host "    source dir : $target"
    Write-Host "    binary dir : $binDir"

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host '  git is required to build llama.cpp but was not found on PATH.'
        Write-Host '  Install Git for Windows from https://git-scm.com/download/win and re-run up.bat.'
        Abort-LlamaCpp
    }
    if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
        Write-Host '  cmake is required to build llama.cpp but was not found on PATH.'
        Write-Host '  Install CMake from https://cmake.org/download/ and re-run up.bat.'
        Abort-LlamaCpp
    }

    $nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($nvidia) {
        $gpuLine = (& nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and $gpuLine) {
            $buildType = 'cuda'
            Write-Host ''
            Write-Host "  NVIDIA GPU detected: $gpuLine"
            Write-Host '  note: the CUDA build needs the CUDA Toolkit (nvcc) and a recent NVIDIA driver.'
        }
    }
    if ($buildType -eq 'cpu') {
        Write-Host ''
        Write-Host '  No NVIDIA GPU detected - building the CPU-only build.'
    }

    Write-Host ''
    Write-Host '  Install plan:'
    Write-Host "    target dir : $target"
    Write-Host "    build type : $($buildType.ToUpper())"
    Write-Host '    commands   :'
    if (-not (Test-Path $target)) {
        Write-Host '      git clone --depth 1 https://github.com/ggml-org/llama.cpp <target>'
    }
    $cudaFlag = if ($buildType -eq 'cuda') { ' -DGGML_CUDA=ON' } else { '' }
    Write-Host "      cmake -B <build> -S <target> -DCMAKE_BUILD_TYPE=Release$cudaFlag"
    Write-Host '      cmake --build <build> --config Release'

    if (-not (Ask-YesNo 'Proceed with the install?')) { Abort-LlamaCpp }

    if (-not (Test-Path $target)) {
        Invoke-RunStep 'Cloning llama.cpp' { git clone --depth 1 https://github.com/ggml-org/llama.cpp $target }
    } elseif (Test-Path (Join-Path $target '.git')) {
        Write-Host ''
        Write-Host '  Updating existing llama.cpp checkout...'
        git -C $target pull --ff-only
        if ($LASTEXITCODE -ne 0) { Write-Host '  git pull failed; continuing with the existing source.' }
    } else {
        Write-Host ''
        Write-Host "  warning: $target exists but is not a git checkout; building from it as-is."
    }

    $cmakeArgs = @('-B', $buildDir, '-S', $target, '-DCMAKE_BUILD_TYPE=Release')
    if ($buildType -eq 'cuda') { $cmakeArgs += '-DGGML_CUDA=ON' }
    Invoke-RunStep 'Configuring build (cmake)' { cmake @cmakeArgs }
    Invoke-RunStep 'Building llama.cpp (cmake --build)' { cmake --build $buildDir --config Release }

    if (Test-BinDir $binDir) {
        $env:LLMBENCH_LLAMA_CPP_BIN_DIR = $binDir
        Write-Host ''
        Write-Host "  llama.cpp installed and verified at $binDir"
        return $binDir
    }

    Write-Host ''
    Write-Host "  The build finished but llama-bench.exe/llama-server.exe were not found in: $binDir"
    Write-Host '  This can happen if the binaries were placed elsewhere.'
    return Read-CustomLocation
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
        $reply = Read-Host '  How do you want to provide llama.cpp? (1) already installed elsewhere, (2) install it now, (q) cancel'
        switch -Regex ($reply.Trim().ToLower()) {
            '^(1)$' { $binDir = Read-CustomLocation }
            '^(2)$' { $binDir = Install-LlamaCpp }
            '^(q|quit|c|cancel|)$' { Abort-LlamaCpp }
            default { Write-Host '  Please choose 1, 2, or q (cancel).' }
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
    & $venvPython -m pip install -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
} finally {
    Pop-Location
}

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
    -ArgumentList '/c', 'npm install && npm run dev' `
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