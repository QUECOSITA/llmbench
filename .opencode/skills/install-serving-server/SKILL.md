---
name: install-serving-server
description: Use when llama.cpp (llama-bench/llama-server) is missing or not installed and the workflow needs it, or when the user asks to install/benchmark with llama.cpp. Detects what's missing truthfully, asks the user for permission, verifies the system, fetches the current install guide with ctx7, installs a CUDA llama.cpp build, re-verifies, and continues the workflow. Trigger on "llama.cpp not installed", "llama-server missing", "llama-bench missing", "install llama.cpp", "serving server".
---

# Install a Missing Serving Server

When the workflow needs llama.cpp (the app's only serving server) and it is not
installed, run this flow instead of failing silently or pretending it exists.

Readiness detection is truthful: llama.cpp is ready when `llama-bench` /
`llama-server` are resolvable (via the app's probe). If the app reports it as
ready, trust it.

## Workflow

### 1. The needed server is always `llama.cpp`
The app supports only llama.cpp (backend fully converted). The server id used
everywhere is `llama.cpp`.

### 2. Detect installation state
Run the app's probe (read-only):
```
cd backend && source .venv/bin/activate && python -m app.install llama.cpp
```
If `[detect] llama.cpp: installed ...`, llama.cpp is ready — **continue the
workflow without prompting**. Nothing to do here.

### 3. If missing: ASK the user
Explicitly ask whether they want to install it, mentioning that it installs a
CUDA build of llama.cpp into `$HOME/llama.cpp` (source build, not a pip wheel).
Do not install without explicit approval (AGENTS.md safety rules).

### 4. Verify the system
The `python -m app.install llama.cpp` output already reports OS/arch, python
version, pip, GPU, VRAM, NVIDIA driver, free disk, and a `[requirements]` list
(CPU-only build is fine; a CUDA build needs an NVIDIA GPU + driver). Review it
and surface any blockers to the user (no NVIDIA GPU, too-old driver, <3.11
python, low disk). Stop and report if a hard requirement is unmet.

### 5. Fetch the current install guide with ctx7
Do NOT hardcode versions or assume the install procedure — it changes with CUDA
and the GPU architecture. Use ctx7 (per the global context7 instructions):

```
npx ctx7@latest library llama.cpp "install CUDA build from source, current recommended"
npx ctx7@latest docs <library-id> "install ..."
```
Pick the best source (exact-name match, high/medium reputation, highest
benchmark), then fetch the install docs. Apply the fetched guidance to the base
commands below.

### 6. Present the plan, then install
Show the exact commands and the ctx7-backed rationale. After the user approves,
run them (they build from source into `$HOME/llama.cpp`; no venv involvement):
```
git clone https://github.com/ggml-org/llama.cpp $HOME/llama.cpp
cmake -B $HOME/llama.cpp/build -S $HOME/llama.cpp -DGGML_CUDA=on
cmake --build $HOME/llama.cpp/build --config Release -j
```
The app auto-discovers `$HOME/llama.cpp/build/bin` (see `up.sh`).

### 7. Re-verify
```
cd backend && source .venv/bin/activate && python -m app.install llama.cpp
```
Confirm `[detect] llama.cpp: installed ...`. If it still reports NOT installed,
debug (binaries not on PATH? build dir not at `$HOME/llama.cpp/build/bin`?
driver issue?) rather than proceeding.

### 8. Continue the workflow
Resume the benchmark/serve flow that required llama.cpp (e.g. re-run the config
generation / benchmark for the detected server).
