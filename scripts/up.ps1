# up.ps1 - Windows counterpart of up.sh.
# Resolves llama.cpp (offers a full source build when missing, including its build
# requirements via winget), creates the backend venv, installs deps, and starts
# uvicorn + the Vite dev server in the background with hidden windows.
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

# True when an MSVC C++ toolchain (Visual Studio / Build Tools with the VC Tools
# workload) is installed, detected via vswhere. cl.exe is only on PATH inside a
# Developer Command Prompt, so it is not a reliable check.
function Test-Msvc {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path $vswhere)) { return $false }
    $install = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath 2>$null
    return [bool]$install
}

# Re-read the Machine and User PATH entries so winget-installed tools (git,
# cmake) are visible to the rest of this script without opening a new shell.
function Refresh-Path {
    $machine = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $env:PATH = (@($machine, $user) | Where-Object { $_ }) -join ';'
}

function Test-Winget {
    return [bool](Get-Command winget -ErrorAction SilentlyContinue)
}

# Detect missing build requirements for the llama.cpp source build (git, cmake,
# MSVC C++ toolchain) and offer to install them via winget. Mirrors the Linux
# scripts/ensure-llama-cpp.sh _check_requirements flow. Aborts when the user
# declines or a requirement is still missing after the install.
function Install-MissingRequirements {
    $git = Get-Command git -ErrorAction SilentlyContinue
    $cmake = Get-Command cmake -ErrorAction SilentlyContinue
    $msvc = Test-Msvc

    $missing = @()
    if (-not $git) { $missing += 'git' }
    if (-not $cmake) { $missing += 'cmake' }
    if (-not $msvc) { $missing += 'MSVC Build Tools (C++)' }

    Write-Host ''
    Write-Host '  System check:'
    if ($git) { Write-Host "    - git: $($git.Source)" } else { Write-Host '    - git: MISSING' }
    if ($cmake) { Write-Host "    - cmake: $($cmake.Source)" } else { Write-Host '    - cmake: MISSING' }
    if ($msvc) { Write-Host '    - C++ compiler (MSVC): found' } else { Write-Host '    - C++ compiler (MSVC): MISSING' }

    if ($missing.Count -eq 0) { return }

    Write-Host ''
    Write-Host "  Missing build requirements: $($missing -join ', ')"
    Write-Host '  These are needed to build llama.cpp from source.'

    if (-not (Test-Winget)) {
        Write-Host '  winget (Windows Package Manager) was not found; install the requirements manually and re-run up.bat:'
        Write-Host '    git   - https://git-scm.com/download/win'
        Write-Host '    cmake - https://cmake.org/download/'
        Write-Host '    MSVC  - https://visualstudio.microsoft.com/visual-cpp-build-tools/ (install the "Desktop development with C++" workload)'
        Abort-LlamaCpp
    }

    if (-not (Ask-YesNo 'Install them now via winget?')) {
        Write-Host '  The build requirements must be installed before compiling.'
        Abort-LlamaCpp
    }

    Refresh-Path

    if (-not $git) {
        Invoke-RunStep 'Installing git (winget)' {
            winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
        }
    }
    if (-not $cmake) {
        Invoke-RunStep 'Installing cmake (winget)' {
            winget install --id Kitware.CMake -e --accept-source-agreements --accept-package-agreements
        }
    }
    if (-not $msvc) {
        Invoke-RunStep 'Installing MSVC Build Tools (winget)' {
            winget install --id Microsoft.VisualStudio.2022.BuildTools -e --accept-source-agreements --accept-package-agreements `
                --override '--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --passive --norestart'
        }
    }

    Refresh-Path

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host '  git is still not on PATH after install; open a new terminal and re-run up.bat.'
        Abort-LlamaCpp
    }
    if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
        Write-Host '  cmake is still not on PATH after install; open a new terminal and re-run up.bat.'
        Abort-LlamaCpp
    }
    if (-not (Test-Msvc)) {
        Write-Host '  MSVC Build Tools are still not detected after install; re-run up.bat in a new terminal.'
        Abort-LlamaCpp
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

    Install-MissingRequirements

    $nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($nvidia) {
        $gpuLine = (& nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and $gpuLine) {
            $buildType = 'cuda'
            Write-Host ''
            Write-Host "  NVIDIA GPU detected: $gpuLine"
            $nvcc = Get-Command nvcc -ErrorAction SilentlyContinue
            if ($nvcc) {
                Write-Host "  CUDA Toolkit found: $($nvcc.Source)"
            } else {
                Write-Host '  note: the CUDA build needs the CUDA Toolkit (nvcc) and a recent NVIDIA driver.'
                if (Test-Winget) {
                    if (Ask-YesNo 'Install the CUDA Toolkit now via winget (Nvidia.CUDA)?') {
                        Invoke-RunStep 'Installing CUDA Toolkit (winget)' {
                            winget install --id Nvidia.CUDA -e --accept-source-agreements --accept-package-agreements
                        }
                    } else {
                        Write-Host '  Continuing without the CUDA Toolkit; cmake will attempt to find one.'
                        Write-Host '  If the CUDA build fails, install it from https://developer.nvidia.com/cuda-downloads and re-run up.bat.'
                    }
                } else {
                    Write-Host '  Install the CUDA Toolkit from https://developer.nvidia.com/cuda-downloads and re-run up.bat'
                    Write-Host '  if the build fails to find it.'
                }
            }
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