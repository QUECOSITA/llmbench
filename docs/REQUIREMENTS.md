# Requirements & Failure Workflows

All requirements for running llmbench and the workflow when each one is not met.
Sources: `README.md`, `up.sh`, `scripts/up.ps1`, `scripts/ensure-llama-cpp.sh`,
`backend/pyproject.toml`, `backend/app/install.py`, `backend/app/api.py`,
`.opencode/skills/install-serving-server/SKILL.md`.

`up.sh` (Linux/macOS) and `up.bat` (Windows) run a **requirements gate** before
starting anything: all requirements are shown up-front with status, then verified.
If a hard requirement is missing, the user is informed and startup exits. Soft
requirements (GPU, speed-bench) are informational only.

| # | Requirement | Gate | Where enforced | When not met → workflow |
|---|-------------|------|----------------|--------------------------|
| 1 | **Python 3.11+** | hard | `up.sh`/`up.ps1` banner; `backend/pyproject.toml` (`requires-python >=3.11`); `install.py` `verify_system()` (`python_ok`) | `up.sh`/`up.ps1` prints the version and **exits** with an install link if `python3`/`py`/`python` is missing or < 3.11. |
| 2 | **Node.js 20+** | hard | `up.sh`/`up.ps1` banner (Node version, new) | `up.sh`/`up.ps1` prints the version and **exits** with an install link if `node` is missing or < 20. `up.ps1` also resolves `npm.cmd` later and aborts with an actionable message. |
| 3 | **HF CLI (`hf`/`huggingface-cli`)** | hard | `backend/pyproject.toml` core deps (`huggingface-hub`); `up.sh`/`up.ps1` verifies in the venv after `pip install`; `backend/app/api.py` (`/models/download`) | Announced in the banner up-front. Verified inside the backend venv after deps install — missing → **exit** with `pip install huggingface-hub`. Since `huggingface-hub` is a core dep, it is always present after `pip install`. |
| 4 | **llama.cpp `llama-bench` + `llama-server`** (only serving server) | hard (interactive) | `up.sh` → `scripts/ensure-llama-cpp.sh`; `up.ps1` → `Resolve-LlamaCpp`; `servers.py` `resolve_bench_binary()`; UI readiness | `up.sh`/`up.bat` **block startup** with an interactive, cancellable flow: (1) point at existing install (LLMBENCH_LLAMA_CPP_BIN_DIR / PATH / standard dirs), (2) install now (source build on Linux/macOS), (q) cancel → abort. Non-TTY: aborts with message to run from a terminal. Agent-side: `install-serving-server` skill → detect, ask permission, verify system, fetch guide with ctx7, build CUDA into `$HOME/llama.cpp`, re-verify. |
| 5 | **Build toolchain** (git, cmake, gcc, g++, make, python3) | hard (source-build path only) | `ensure-llama-cpp.sh` `_check_requirements()` | Only needed for the source-build path: prompts `sudo apt-get install -y git cmake build-essential make python3 python3-venv`; user declines → **abort**. CUDA build additionally wants `nvcc`/CUDA toolkit + NVIDIA GPU + driver. |
| 6 | **NVIDIA GPU** | informational | README; `install.py` `requirements_for()` | CPU-only build is fine; CUDA build requires GPU + driver. No GPU/driver → noted as `[requirements]`, agent surfaces blocker. App still boots/serves. |
| 7 | **speed-bench Python deps** (datasets, requests, tqdm) | informational | `backend/pyproject.toml` `[speed-bench]`; `servers.py` `speed_bench_deps_available()` | `up.sh`/`up.bat` install as an **optional, non-blocking** step (warning only). Missing → speed-bench unavailable, configs get a `bench_error` ("requires requests/datasets/tqdm"); llama-bench path unaffected. |
| 8 | **`speed_bench.py` script** | informational | `servers.py` `ensure_speed_bench_script()` (auto-discovers next to llama-server, honors `LLMBENCH_SPEED_BENCH_SCRIPT`) | Auto-**provisioned into `~/.llmbench/speed-bench/`** on first MTP benchmark (best-effort); failure → clear `bench_error`. |
| 9 | **pywinpty (Windows ConPTY)** | informational | `backend/pyproject.toml` `[win]` extra | Installed only via `up.bat`/`down.bat`; absent only degrades download progress-bar rendering on Windows. |

**Hard gates (startup exits when missing):** #1 (Python 3.11+), #2 (Node.js 20+),
#3 (HF CLI), #4 (llama.cpp). Everything else is informational/degradable.