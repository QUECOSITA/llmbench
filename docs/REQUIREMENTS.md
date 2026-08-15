# Requirements & Failure Workflows

All requirements for running llmbench and the workflow when each one is not met.
Sources: `README.md`, `up.sh`, `scripts/ensure-llama-cpp.sh`,
`backend/pyproject.toml`, `backend/app/install.py`, `backend/app/api.py`,
`.opencode/skills/install-serving-server/SKILL.md`.

| # | Requirement | Where enforced | When not met → workflow |
|---|-------------|----------------|--------------------------|
| 1 | **Python 3.11+** | `backend/pyproject.toml` (`requires-python >=3.11`); `install.py` `verify_system()` (`python_ok`) | `up.sh` creates a venv and installs deps; if Python < 3.11 the agent/`install.py` reports `python_ok: false` as a **hard blocker** — stop and report (install-serving-server skill step 4). |
| 2 | **Node 20+** | README; `up.bat` / `scripts/up.ps1` | `up.bat` resolves `npm.cmd` and **aborts with an actionable message** if Node is missing. |
| 3 | **HF CLI (`hf`/`huggingface-cli`)** | `backend/app/api.py` (`/models/download`) | Download returns **400 "HF CLI not found. Run: `hf download …`"** — user is told the exact command to run. Readiness is shown in the UI. |
| 4 | **llama.cpp `llama-bench` + `llama-server`** (only serving server) | `up.sh` → `scripts/ensure-llama-cpp.sh`; `servers.py` `resolve_bench_binary()`; UI readiness | `up.sh` **blocks startup** with an interactive, cancellable flow: (1) point at existing install (LLMBENCH_LLAMA_CPP_BIN_DIR / PATH / standard dirs), (2) install now (source build), (q) cancel → abort. Non-TTY: aborts with message to run `./up.sh` from a terminal. Agent-side: `install-serving-server` skill → detect, ask permission, verify system, fetch guide with ctx7, build CUDA into `$HOME/llama.cpp`, re-verify. |
| 5 | **Build toolchain** (git, cmake, gcc, g++, make, python3) | `ensure-llama-cpp.sh` `_check_requirements()` | Only needed for the source-build path: prompts `sudo apt-get install -y git cmake build-essential make python3 python3-venv`; user declines → **abort**. CUDA build additionally wants `nvcc`/CUDA toolkit + NVIDIA GPU + driver. |
| 6 | **NVIDIA GPU** | README; `install.py` `requirements_for()` | CPU-only build is fine; CUDA build requires GPU + driver. No GPU/driver → noted as `[requirements]`, agent surfaces blocker. App still boots/serves. |
| 7 | **speed-bench Python deps** (datasets, requests, tqdm) | `backend/pyproject.toml` `[speed-bench]`; `servers.py` `speed_bench_deps_available()` | `up.sh`/`up.bat` install as an **optional, non-blocking** step (warning only). Missing → speed-bench unavailable, configs get a `bench_error` ("requires requests/datasets/tqdm"); llama-bench path unaffected. |
| 8 | **`speed_bench.py` script** | `servers.py` `ensure_speed_bench_script()` (auto-discovers next to llama-server, honors `LLMBENCH_SPEED_BENCH_SCRIPT`) | Auto-**provisioned into `~/.llmbench/speed-bench/`** on first MTP benchmark (best-effort); failure → clear `bench_error`. |
| 9 | **pywinpty (Windows ConPTY)** | `backend/pyproject.toml` `[win]` extra | Installed only via `up.bat`/`down.bat`; absent only degrades download progress-bar rendering on Windows. |

**Key non-negotiables:** #1 (Python 3.11+), #2 (Node 20+), #4 (llama.cpp) — these
gate startup/run. Everything else is conditional or degradable.