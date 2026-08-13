# llama.cpp Startup Gate in `up.sh` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `up.sh` resolve llama.cpp (`llama-bench` + `llama-server`) before starting the app — from `LLMBENCH_LLAMA_CPP_BIN_DIR`, PATH, or OS-standard dirs — and, when missing, run an interactive, fully-cancellable flow that points at an existing install or triggers a fresh source build. Cancelling at any prompt aborts `up.sh`.

**Architecture:** A new sourced script `scripts/ensure-llama-cpp.sh` does detection + interactive install and `export`s `LLMBENCH_LLAMA_CPP_BIN_DIR` back into `up.sh` (sourcing is required so the export propagates to the spawned backend/frontend). `up.sh` just sources it as its first action. No backend/frontend code changes.

**Tech Stack:** Bash (Linux/macOS), cmake + git source build of llama.cpp, `backend/app/install.py` stays the runtime source of truth.

---

## File Structure

- **Create:** `scripts/ensure-llama-cpp.sh` — detection + interactive, cancellable install flow.
- **Modify:** `up.sh` — replace the ad-hoc `$HOME/llama.cpp/build/bin` check (lines 2–5) with a `source` of the new script.
- **Docs:** `docs/superpowers/specs/2026-08-13-llama-cpp-startup-gate-design.md` (design), this plan.

---

### Task 1: Create `scripts/ensure-llama-cpp.sh`

**Files:**
- Create: `scripts/ensure-llama-cpp.sh`

- [ ] **Step 1: Create the script with the full implementation below**

```bash
#!/usr/bin/env bash
# ensure-llama-cpp.sh
#
# Sourced by up.sh. Resolves llama.cpp (llama-bench + llama-server) and exports
# LLMBENCH_LLAMA_CPP_BIN_DIR when it is found outside PATH. When llama.cpp is
# missing, runs an interactive, cancellable flow: point at an existing install
# or build a fresh one. Every prompt accepts q/c/cancel (or empty where noted)
# to abort up.sh.
set -u

# --- helpers ---------------------------------------------------------------

_abort() {
    echo
    echo "llama.cpp (llama-bench + llama-server) is required for benchmarks."
    echo "Startup aborted."
    exit 1
}

_is_tty() {
    [ -t 0 ] && [ -t 1 ]
}

_bin_dir_ok() { # $1 = dir path
    [ -n "${1:-}" ] && [ -d "$1" ] && [ -x "$1/llama-bench" ] && [ -x "$1/llama-server" ]
}

# Print a prompt and read one line into REPLY. EOF (Ctrl-D) becomes "q".
_read_cancelable() { # $1 = prompt
    printf "%s " "$1"
    if ! IFS= read -r REPLY; then
        REPLY="q"
    fi
}

# Returns 0 for yes, 1 for no; aborts on cancel.
_ask_yes_no() { # $1 = prompt
    while :; do
        _read_cancelable "$1 [y/n/q]"
        case "${REPLY,,}" in
            y|yes) return 0 ;;
            n|no|"") return 1 ;;
            q|quit|c|cancel|exit) _abort ;;
            *) echo "  Please answer y (yes), n (no), or q (cancel)." ;;
        esac
    done
}

# Run a command, offering retry or cancel if it fails.
_run_step() { # $1 = description, rest = command
    local desc="$1"
    shift
    while :; do
        _info "$desc..."
        if "$@"; then
            return 0
        fi
        echo "  Command failed: $*"
        if _ask_yes_no "Retry?"; then
            continue
        fi
        _abort
    done
}

_info() {
    echo "[ensure-llama-cpp] $*"
}

_standard_bin_dirs() {
    case "$(uname -s)" in
        Darwin)
            if command -v brew >/dev/null 2>&1; then
                printf "%s " "$(brew --prefix)/bin"
            fi
            printf "%s\n" "/opt/homebrew/bin /usr/local/bin $HOME/llama.cpp/build/bin"
            ;;
        Linux)
            printf "%s\n" "/usr/local/bin /usr/bin /opt/llama.cpp/build/bin $HOME/llama.cpp/build/bin"
            ;;
        *)
            printf "%s\n" "/usr/local/bin /usr/bin $HOME/llama.cpp/build/bin"
            ;;
    esac
}

# --- custom location --------------------------------------------------------

_resolve_custom_location() {
    while :; do
        _read_cancelable "Full path to the directory containing llama-bench and llama-server:"
        case "${REPLY,,}" in
            q|quit|c|cancel) _abort ;;
        esac
        local path="${REPLY/#\~/$HOME}"
        if [ -z "$path" ]; then
            echo "  No path entered."
            continue
        fi
        if _bin_dir_ok "$path"; then
            export LLMBENCH_LLAMA_CPP_BIN_DIR="$path"
            _info "llama.cpp found at $path"
            return 0
        fi
        echo "  No llama-bench/llama-server executables found in: $path"
        while :; do
            _read_cancelable "What next? (r) try another path, (i) install now, (q) cancel"
            case "${REPLY,,}" in
                r|retry) break ;;
                i|install) _do_install; return $? ;;
                q|quit|c|cancel|"") _abort ;;
                *) echo "  Please choose r, i, or q." ;;
            esac
        done
    done
}

# --- install ----------------------------------------------------------------

_check_requirements() {
    local apt_pkgs=() missing=()
    command -v git      >/dev/null 2>&1 || { missing+=(git);   apt_pkgs+=(git); }
    command -v cmake    >/dev/null 2>&1 || { missing+=(cmake); apt_pkgs+=(cmake); }
    command -v gcc      >/dev/null 2>&1 || { missing+=(gcc);   apt_pkgs+=(build-essential); }
    command -v g++      >/dev/null 2>&1 || { missing+=(g++);   apt_pkgs+=(build-essential); }
    command -v make     >/dev/null 2>&1 || { missing+=(make);  apt_pkgs+=(make); }
    command -v python3  >/dev/null 2>&1 || { missing+=(python3); apt_pkgs+=(python3 python3-venv); }

    echo "  System check:"
    for tool in git cmake make python3; do
        if command -v "$tool" >/dev/null 2>&1; then
            echo "    - $tool: $(command -v "$tool")"
        else
            echo "    - $tool: MISSING"
        fi
    done
    if command -v cc >/dev/null 2>&1; then
        echo "    - C compiler: $(command -v cc)"
    else
        echo "    - C compiler: MISSING"
    fi
    if command -v c++ >/dev/null 2>&1; then
        echo "    - C++ compiler: $(command -v c++)"
    else
        echo "    - C++ compiler: MISSING"
    fi
    echo "    - free disk on $HOME: $(df -h "$HOME" | awk 'NR==2 {print $4 " available (" $5 " used)"}')"

    if [ "${#missing[@]}" -gt 0 ]; then
        echo
        echo "  Missing build requirements: ${missing[*]}"
        echo "  These are needed to build llama.cpp from source."
        if _ask_yes_no "Install them now via 'sudo apt-get install -y ${apt_pkgs[*]}'?"; then
            _run_step "Updating apt package lists" sudo apt-get update
            _run_step "Installing build requirements" sudo apt-get install -y "${apt_pkgs[@]}"
        else
            echo "  The build requirements must be installed before compiling."
            _abort
        fi
    fi
}

_do_install() {
    local target="$HOME/llama.cpp"
    local build_dir="$target/build"
    local bin_dir="$build_dir/bin"
    local build_type="cpu"
    local nproc_jobs
    nproc_jobs="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"

    echo
    _info "Preparing a llama.cpp source build."
    _info "  source dir : $target"
    _info "  binary dir : $bin_dir"

    _check_requirements

    if command -v nvidia-smi >/dev/null 2>&1 \
        && nvidia-smi --query-gpu=name --format=csv,noheader >/dev/null 2>&1; then
        build_type="cuda"
        echo
        echo "  NVIDIA GPU detected: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -n1)"
        if ! command -v nvcc >/dev/null 2>&1 && [ -z "${CUDA_HOME:-}" ]; then
            echo "  note: CUDA toolkit (nvcc) was not detected; cmake will attempt to find one."
            echo "        If the CUDA build fails, install it (e.g. 'sudo apt install nvidia-cuda-toolkit') and retry."
        fi
    else
        echo
        echo "  No NVIDIA GPU detected — building the CPU-only build."
    fi

    echo
    echo "  Install plan:"
    echo "    target dir : $target"
    echo "    build type : ${build_type^^}"
    echo "    commands   :"
    if [ ! -e "$target" ]; then
        echo "      git clone --depth 1 https://github.com/ggml-org/llama.cpp $target"
    fi
    if [ "$build_type" = "cuda" ]; then
        echo "      cmake -B $build_dir -S $target -DGGML_CUDA=ON"
    else
        echo "      cmake -B $build_dir -S $target"
    fi
    echo "      cmake --build $build_dir --config Release -j$nproc_jobs"

    if ! _ask_yes_no "Proceed with the install?"; then
        _abort
    fi

    if [ ! -e "$target" ]; then
        _run_step "Cloning llama.cpp" git clone --depth 1 https://github.com/ggml-org/llama.cpp "$target"
    elif [ -d "$target/.git" ]; then
        echo
        echo "  Updating existing llama.cpp checkout..."
        git -C "$target" pull --ff-only || echo "  git pull failed; continuing with the existing source."
    else
        echo
        echo "  warning: $target exists but is not a git checkout; building from it as-is."
    fi

    local cmake_args=(-B "$build_dir" -S "$target" -DCMAKE_BUILD_TYPE=Release)
    if [ "$build_type" = "cuda" ]; then
        cmake_args+=(-DGGML_CUDA=ON)
    fi
    _run_step "Configuring build (cmake)" cmake "${cmake_args[@]}"

    _run_step "Building llama.cpp (cmake --build)" cmake --build "$build_dir" --config Release -j"$nproc_jobs"

    if _bin_dir_ok "$bin_dir"; then
        export LLMBENCH_LLAMA_CPP_BIN_DIR="$bin_dir"
        echo
        _info "llama.cpp installed and verified at $bin_dir"
        return 0
    fi

    echo
    echo "  The build finished but llama-bench/llama-server were not found in: $bin_dir"
    echo "  This can happen if the binaries were placed elsewhere."
    _resolve_custom_location
}

# --- main -------------------------------------------------------------------

main() {
    if ! _is_tty; then
        echo "[ensure-llama-cpp] llama.cpp was not found and up.sh is not running interactively."
        echo "[ensure-llama-cpp] Run './up.sh' from a terminal to resolve llama.cpp."
        _abort
    fi

    local bin_dir="${LLMBENCH_LLAMA_CPP_BIN_DIR:-}"
    if _bin_dir_ok "$bin_dir"; then
        _info "using LLMBENCH_LLAMA_CPP_BIN_DIR=$bin_dir"
        return 0
    fi
    if [ -n "$bin_dir" ]; then
        _info "warning: LLMBENCH_LLAMA_CPP_BIN_DIR is set but has no llama-bench/llama-server: $bin_dir"
    fi
    unset LLMBENCH_LLAMA_CPP_BIN_DIR

    if command -v llama-bench >/dev/null 2>&1 && command -v llama-server >/dev/null 2>&1; then
        _info "llama.cpp found on PATH (llama-bench: $(command -v llama-bench))"
        return 0
    fi

    local dir
    while read -r dir; do
        [ -z "$dir" ] && continue
        if _bin_dir_ok "$dir"; then
            export LLMBENCH_LLAMA_CPP_BIN_DIR="$dir"
            _info "llama.cpp found at $dir"
            return 0
        fi
    done < <(_standard_bin_dirs)

    echo
    echo "  llama.cpp provides llama-bench (benchmarking) and llama-server (serving)."
    echo "  It was not found on PATH or in the standard install locations."
    while :; do
        _read_cancelable "How do you want to provide llama.cpp? (1) already installed elsewhere, (2) install it now, (q) cancel"
        case "${REPLY,,}" in
            1) _resolve_custom_location; return $? ;;
            2) _do_install; return $? ;;
            q|quit|c|cancel|"") _abort ;;
            *) echo "  Please choose 1, 2, or q (cancel)." ;;
        esac
    done
}

main
```

- [ ] **Step 2: Syntax check**

Run: `bash -n scripts/ensure-llama-cpp.sh`
Expected: no output (exit 0).

- [ ] **Step 3: Commit**

```bash
git add scripts/ensure-llama-cpp.sh
git commit -m "feat: add cancellable llama.cpp detection/install flow for up.sh"
```

---

### Task 2: Source the helper from `up.sh`

**Files:**
- Modify: `up.sh`

- [ ] **Step 1: Replace the ad-hoc discovery block**

Replace lines 2–5 of `up.sh` (currently the `LLMBENCH_LLAMA_CPP_BIN_DIR` default block) with a single source line:

```bash
#!/bin/bash
# Resolve llama.cpp (llama-bench + llama-server) before starting the app; the
# sourced helper exports LLMBENCH_LLAMA_CPP_BIN_DIR and aborts if cancelled.
source "$(dirname "$0")/scripts/ensure-llama-cpp.sh"
cd backend
```

The rest of `up.sh` (venv, uvicorn, frontend) stays unchanged.

- [ ] **Step 2: Syntax check**

Run: `bash -n up.sh`
Expected: no output (exit 0).

- [ ] **Step 3: Commit**

```bash
git add up.sh
git commit -m "feat: gate up.sh startup on llama.cpp presence"
```

---

### Task 3: Functional tests of the helper

**Files:**
- Test (manual): temp fixtures under `/tmp/opencode/llmbench-test-*`

Use a fake `$HOME` so the tests never touch the real `~/.llmbench`, `~/llama.cpp`, or a real install.

- [ ] **Step 1: "Override valid" path (no TTY needed)**

```bash
TMP=$(mktemp -d /tmp/opencode/llmbench-test-XXXX)
mkdir -p "$TMP/bin"
printf '#!/bin/sh\n' > "$TMP/bin/llama-bench"; chmod +x "$TMP/bin/llama-bench"
printf '#!/bin/sh\n' > "$TMP/bin/llama-server"; chmod +x "$TMP/bin/llama-server"
HOME="$TMP" LLMBENCH_LLAMA_CPP_BIN_DIR="$TMP/bin" bash -c \
  'source scripts/ensure-llama-cpp.sh && echo "RESULT=$LLMBENCH_LLAMA_CPP_BIN_DIR"'
```
Expected: `[ensure-llama-cpp] using LLMBENCH_LLAMA_CPP_BIN_DIR=$TMP/bin` then `RESULT=$TMP/bin`.

- [ ] **Step 2: "Standard dir found" path**

```bash
mkdir -p "$TMP/llama.cpp/build/bin"
cp "$TMP/bin/llama-bench" "$TMP/bin/llama-server" "$TMP/llama.cpp/build/bin/"
HOME="$TMP" bash -c 'source scripts/ensure-llama-cpp.sh && echo "RESULT=$LLMBENCH_LLAMA_CPP_BIN_DIR"'
```
Expected: `[ensure-llama-cpp] llama.cpp found at $TMP/llama.cpp/build/bin` and `RESULT=$TMP/llama.cpp/build/bin`.

- [ ] **Step 3: "PATH present" path**

```bash
PATH="$TMP/bin:$PATH" HOME="$TMP/empty-home" bash -c \
  'source scripts/ensure-llama-cpp.sh && echo "RESULT=${LLMBENCH_LLAMA_CPP_BIN_DIR:-unset}"'
```
Expected: `llama.cpp found on PATH` and `RESULT=unset` (backend will use PATH).

- [ ] **Step 4: Menu cancel (interactive, via pseudo-TTY)**

```bash
rm -rf "$TMP/empty-home"; mkdir -p "$TMP/empty-home"
printf 'q\n' | HOME="$TMP/empty-home" script -qec 'bash -c "source scripts/ensure-llama-cpp.sh"' /dev/null; echo "EXIT=$?"
```
Expected: shows the "How do you want to provide llama.cpp?" prompt, then `llama.cpp (llama-bench + llama-server) is required for benchmarks.` + `Startup aborted.`, and `EXIT=1`.

- [ ] **Step 5: Custom location valid**

```bash
printf '1\n%s\n' "$TMP/bin" | HOME="$TMP/empty-home" script -qec \
  'bash -c "source scripts/ensure-llama-cpp.sh && echo RESULT=\$LLMBENCH_LLAMA_CPP_BIN_DIR"' /dev/null
```
Expected: `llama.cpp found at $TMP/bin` and `RESULT=$TMP/bin`.

- [ ] **Step 6: Custom location invalid → offer install → cancel**

```bash
printf '1\n%s\nq\n' "$TMP/no-such-dir" | HOME="$TMP/empty-home" script -qec \
  'bash -c "source scripts/ensure-llama-cpp.sh"' /dev/null; echo "EXIT=$?"
```
Expected: `No llama-bench/llama-server executables found in: $TMP/no-such-dir`, then `(r) try another path, (i) install now, (q) cancel` prompt; `q` → `Startup aborted.`, `EXIT=1`.

- [ ] **Step 7: Install happy path with shim `git`/`cmake` (no real build)**

```bash
SHIM=$(mktemp -d /tmp/opencode/llmbench-shim-XXXX)
cat > "$SHIM/git" <<'EOF'
#!/bin/sh
if [ "$1" = "clone" ]; then
  mkdir -p "${@: -1}/.git"
  printf 'cmake_minimum_required(VERSION 3.14)\nproject(x)\n' > "${@: -1}/CMakeLists.txt"
  exit 0
fi
exit 0
EOF
chmod +x "$SHIM/git"
cat > "$SHIM/cmake" <<'EOF'
#!/bin/sh
# Configure phase: create the build dir. Build phase: emit the binaries.
if [ "$1" = "--build" ]; then
  BIN="$HOME/llama.cpp/build/bin"
  mkdir -p "$BIN"
  printf '#!/bin/sh\n' > "$BIN/llama-bench"; chmod +x "$BIN/llama-bench"
  printf '#!/bin/sh\n' > "$BIN/llama-server"; chmod +x "$BIN/llama-server"
else
  mkdir -p "$HOME/llama.cpp/build"
fi
exit 0
EOF
chmod +x "$SHIM/cmake"
printf '2\ny\ny\n' | HOME="$TMP/empty-home" PATH="$SHIM:$PATH" script -qec \
  'bash -c "source scripts/ensure-llama-cpp.sh && echo RESULT=\$LLMBENCH_LLAMA_CPP_BIN_DIR"' /dev/null
```
Expected: install plan printed (CPU build, no `-DGGML_CUDA=ON`), `Proceed with the install?` accepted, then `llama.cpp installed and verified at $TMP/empty-home/llama.cpp/build/bin` and `RESULT=$TMP/empty-home/llama.cpp/build/bin`.

- [ ] **Step 8: Cancel at the install-plan approval**

```bash
printf '2\nq\n' | HOME="$TMP/empty-home" PATH="$SHIM:$PATH" script -qec \
  'bash -c "source scripts/ensure-llama-cpp.sh"' /dev/null; echo "EXIT=$?"
```
Expected: install plan printed, `q` → `Startup aborted.`, `EXIT=1`.

- [ ] **Step 9: Clean up fixtures**

```bash
rm -rf "$TMP" "$SHIM" /tmp/opencode/llmbench-test-* /tmp/opencode/llmbench-shim-*
```

---

### Task 4: Full local suite (must stay green)

**Files:** none changed here — verification only.

- [ ] **Step 1: Backend tests**

Run: `cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/python -m pytest`
Expected: all pass (the repo was already green on `main`; the feature branch only touches `up.sh` + a new shell script).

- [ ] **Step 2: Frontend typecheck + unit tests**

Run: `cd frontend && npx tsc -b && npx vitest run`
Expected: typecheck clean, all tests pass.

- [ ] **Step 3: Playwright e2e**

Run: `cd frontend && npx playwright test` (uses `webServer` + mock-server per AGENTS.md; no real backend/HF needed)
Expected: all pass.

- [ ] **Step 4: Commit any stragglers**

```bash
git status
```

---

### Task 5: Optional live end-to-end install

- [ ] **Step 1: (Optional, confirm with user first) Run the real flow**

Run: `./up.sh`, choose `(2) install it now`, approve. This builds llama.cpp into `~/llama.cpp` on this machine (CPU build unless an NVIDIA GPU + driver are detected). Verify afterwards:
```bash
ls -la ~/llama.cpp/build/bin/llama-bench ~/llama.cpp/build/bin/llama-server
cd backend && source .venv/bin/activate && python -m app.install llama.cpp
```
Expected: `[detect] llama.cpp: installed (version ...)`.

> This step is heavy (cmake build) and mutates the real `~/llama.cpp`; it is only run with the user's explicit go-ahead.

---

## Post-implementation

- [ ] **Step 1: PR**

Per AGENTS.md: `git push origin feature/up-sh-llama-cpp-gate`, open a PR against `main`, wait for CI + security scans before merge.

- [ ] **Step 2: Cleanup** — delete the branch after merge.
