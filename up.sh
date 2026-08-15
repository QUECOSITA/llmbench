#!/bin/bash
set -u

# --- requirements: show all up-front, then gate on the hard ones ------------

_requirements_missing=0

_show_req() { # $1 = name, $2 = status, rest = hints
    local name="$1" status="$2"
    shift 2
    printf '  %-22s : %s\n' "$name" "$status"
    if [ "$status" = "MISSING" ]; then
        for hint in "$@"; do
            printf '    -> %s\n' "$hint"
        done
        _requirements_missing=1
    fi
}

_check_python() {
    local ver major minor
    if command -v python3 >/dev/null 2>&1; then
        ver="$(python3 --version 2>&1)"
    fi
    if [ -z "$ver" ]; then
        _show_req "Python 3.11+" "MISSING" \
            "python3 not found — install from https://www.python.org/downloads/"
        return
    fi
    major="$(printf '%s' "${ver#Python }" | cut -d. -f1)"
    minor="$(printf '%s' "${ver#Python }" | cut -d. -f2)"
    if [ "$major" -lt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -lt 11 ]; }; then
        _show_req "Python 3.11+" "MISSING" \
            "found $ver — install 3.11+ from https://www.python.org/downloads/"
        return
    fi
    _show_req "Python 3.11+" "OK ($ver)"
}

_check_node() {
    local ver major
    if command -v node >/dev/null 2>&1; then
        ver="$(node --version 2>&1)"
    fi
    if [ -z "$ver" ]; then
        _show_req "Node.js 20+" "MISSING" \
            "node not found — install from https://nodejs.org/"
        return
    fi
    major="$(printf '%s' "${ver#v}" | cut -d. -f1)"
    if [ "$major" -lt 20 ]; then
        _show_req "Node.js 20+" "MISSING" \
            "found $ver — install 20+ from https://nodejs.org/"
        return
    fi
    _show_req "Node.js 20+" "OK ($ver)"
}

_check_hf_cli_pre() {
    # Announced up-front; actually verified inside the venv after deps install.
    if command -v hf >/dev/null 2>&1 || command -v huggingface-cli >/dev/null 2>&1; then
        _show_req "HF CLI (hf)" "OK (on PATH)"
    else
        _show_req "HF CLI (hf)" "CHECK AFTER DEPS" \
            "installed into the backend venv via huggingface-hub"
    fi
}

_check_requirements() {
    echo
    echo "  ============================================="
    echo "  llmbench — requirements check"
    echo "  ============================================="
    _check_python
    _check_node
    _check_hf_cli_pre
    _show_req "llama.cpp" "RESOLVED NEXT" "(interactive flow)"
    _show_req "NVIDIA GPU" "informational" "(CPU-only build is fine)"
    _show_req "speed-bench" "informational" "(optional, auto-installed)"
    echo "  ============================================="
    if [ "$_requirements_missing" -eq 1 ]; then
        echo
        echo "  llmbench requirements not met. Startup aborted."
        exit 1
    fi
}

_check_requirements

# Resolve llama.cpp (llama-bench + llama-server) before starting the app; the
# sourced helper exports LLMBENCH_LLAMA_CPP_BIN_DIR and aborts if cancelled.
source "$(dirname "$0")/scripts/ensure-llama-cpp.sh"
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pip install -e '.[speed-bench]' || echo "warning: speed-bench dependencies not installed; speed-bench unavailable (app still runs)."
_hf_cmd="$(command -v hf || command -v huggingface-cli || true)"
if [ -z "$_hf_cmd" ]; then
    echo
    echo "  HF CLI (hf) is required but was not found in the backend venv."
    echo "  Install it with: pip install 'huggingface-hub>=1.0'"
    echo "  Startup aborted."
    exit 1
fi
if ! "$_hf_cmd" --version >/dev/null 2>&1; then
    echo
    echo "  HF CLI (hf) is installed but cannot start ($_hf_cmd)."
    echo "  A stale 'hf' shim usually points at a removed Python install."
    echo "  Check your Python installation, then re-run up.sh."
    echo "  Startup aborted."
    exit 1
fi
nohup uvicorn app.main:app --port 8000 &
cd ..
cd frontend 
nohup npm install && npm run dev &
sleep 2

clear

echo "Backend and Frontend running..."
echo "Open http://localhost:5173."
