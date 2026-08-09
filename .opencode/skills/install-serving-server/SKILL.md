---
name: install-serving-server
description: Use when a serving server (vLLM, sglang, llama.cpp) is missing or not installed and the workflow needs it, or when the user asks to install/benchmark with a serving server. Detects what's missing truthfully, asks the user for permission, verifies the system, fetches the current install guide with ctx7, installs into the backend venv, re-verifies, and continues the workflow. Trigger on "vllm not installed", "install sglang", "llama-server missing", "serving server".
---

# Install a Missing Serving Server

When the workflow needs a serving server (vLLM, sglang, llama.cpp) that is not
installed, run this flow instead of failing silently or pretending it exists.

Readiness detection is truthful: vLLM/sglang are ready only when their module is
importable in the backend interpreter; llama.cpp is ready when `llama-bench` /
`llama-server` are resolvable. If the app reports a server as ready, trust it.

## Workflow

### 1. Determine which server the current task needs
- Usually the `detected_server` from `/models/analyze`, the user's request, or the
  readiness report from `/api/servers`.

### 2. Detect installation state
Run the app's probe (read-only):
```
cd backend && source .venv/bin/activate && python -m app.install <server_id>
```
If `[detect] <server>: installed ...`, the server is ready — **continue the workflow
without prompting**. Nothing to do here.

### 3. If missing: ASK the user
Explicitly ask whether they want to install it, including what it pulls in (e.g. a
multi-GB torch wheel for vLLM/sglang) and that it will be installed into
`backend/.venv`. Do not install without explicit approval (AGENTS.md safety rules).

### 4. Verify the system
The `python -m app.install <server_id>` output already reports OS/arch, python
version, pip, GPU, VRAM, NVIDIA driver, free disk, and a `[requirements]` list.
Review it and surface any blockers to the user (no NVIDIA GPU, too-old driver,
<3.11 python, low disk). Stop and report if a hard requirement is unmet.

### 5. Fetch the current install guide with ctx7
Do NOT hardcode versions or assume the install procedure — it changes with torch,
CUDA, and the GPU architecture. Use ctx7 (per the global context7 instructions):

```
npx ctx7@latest library vllm "install on RTX 5080 / Blackwell sm_120, current recommended"
npx ctx7@latest docs <library-id> "install ..."
```
Pick the best source (exact-name match, high/medium reputation, highest benchmark),
then fetch the install docs. Apply the fetched guidance to the base commands:
- **vLLM** — `python -m pip install vllm` (a Blackwell/`sm_120` GPU like an RTX
  50-series needs a recent torch + vLLM release; ctx7 will confirm which).
- **sglang** — `python -m pip install "sglang[all]"` (plus any current extras ctx7
  calls out, e.g. flashinfer).
- **llama.cpp** — CUDA build from source:
  `cmake -B $HOME/llama.cpp/build -S $HOME/llama.cpp -DGGML_CUDA=on && cmake --build $HOME/llama.cpp/build -j`.
  The app auto-discovers `$HOME/llama.cpp/build/bin` (see `up.sh`).

### 6. Present the plan, then install
Show the exact commands and the ctx7-backed rationale. After the user approves, run
them **inside `backend/.venv`** (`source .venv/bin/activate`) so the backend
interpreter (`sys.executable`) that spawns the benches can see the module.

### 7. Re-verify
```
python -m app.install <server_id>
```
Confirm `[detect] <server>: installed ...`. If it still reports NOT installed, debug
(module not in the venv? wrong python? driver issue) rather than proceeding.

### 8. Continue the workflow
Resume the benchmark/serve flow that required the server (e.g. re-run the config
generation / benchmark for the detected server).
