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
                printf "%s\n" "$(brew --prefix)/bin"
            fi
            printf "%s\n" /opt/homebrew/bin /usr/local/bin "$HOME/llama.cpp/build/bin"
            ;;
        Linux)
            printf "%s\n" /usr/local/bin /usr/bin /opt/llama.cpp/build/bin "$HOME/llama.cpp/build/bin"
            ;;
        *)
            printf "%s\n" /usr/local/bin /usr/bin "$HOME/llama.cpp/build/bin"
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

    if ! _is_tty; then
        echo "[ensure-llama-cpp] llama.cpp was not found and up.sh is not running interactively."
        echo "[ensure-llama-cpp] Run './up.sh' from a terminal to resolve llama.cpp."
        _abort
    fi

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
