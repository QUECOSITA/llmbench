# LLM Bench

[![CI](https://github.com/QUECOSITA/llmbench/actions/workflows/ci.yml/badge.svg)](https://github.com/QUECOSITA/llmbench/actions/workflows/ci.yml)

Benchmark Hugging Face coding LLMs with llama.cpp to find the best serving config — ranked by **DECODE STAGE tokens/sec**.

LLM Bench reads a model's own README to detect the intended serving program and proposed flags, generates N editable config commands, and benchmarks them serially with the server's native bench tool. The configs tested are the ones the model author intended, not a generic template.

## Table of Contents

- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [The Flow](#the-flow)
- [Key Features](#key-features)
- [How It Works](#how-it-works)
- [Data & Configuration](#data--configuration)
- [Platform Notes](#platform-notes)
- [Tests](#tests)
- [Project Docs](#project-docs)

## Requirements

`up.sh` (Linux/macOS) and `up.bat` (Windows) run a **requirements gate** before starting anything: every requirement is listed up-front with its status, then verified. If a hard requirement is missing, you are told and startup exits. Informational requirements never block startup.

| Requirement | Gate | Notes |
|---|---|---|
| Python 3.11+ | **hard** | verified by `up.sh`/`up.bat`; missing → exit with install instructions |
| Node.js 20+ | **hard** | verified by `up.sh`/`up.bat`; missing → exit with install instructions |
| HF CLI (`hf` / `huggingface-cli`) | **hard** | installed into the backend venv as a core dependency (`huggingface-hub`), so always present after `pip install`; re-verified after deps install |
| llama.cpp (`llama-bench` + `llama-server`) | **hard** (interactive) | resolved interactively — point at an existing install, build it now, or cancel → exit |
| NVIDIA GPU | informational | a CPU-only build of llama.cpp also works; GPU-fit semantics assume CUDA |
| speed-bench deps (`datasets`, `requests`, `tqdm`) | informational | installed as an optional step that never blocks startup; only needed for speculative-decoding / MTP benchmarks |

Deep failure-workflow details (what happens when each requirement is missing) live in [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md).

## Quick Start

One-shot start (installs deps, then launches backend + frontend in the background):

```
./up.sh
```

Open **http://localhost:5173** in your browser.

Stop everything:

```
./down.sh
```

**Windows:** use `up.bat` / `down.bat` instead — they run the same workflow via PowerShell.

To run manually:

```bash
# Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --port 8000
```

```bash
# Frontend
cd frontend
npm install
npm run dev
```

## The Flow

The UI is a single-page instrument with numbered panels that mirror the workflow:

- **01 · MODEL INPUT** — paste a HF link or `user/model`, analyze, review the serving program and proposed flags, check hardware fit, and download the model.
- **02 · CONFIG BANK** — set N (1–10), optionally pick the bench tool, and generate editable config commands.
- **03 · RUN** — run or cancel the benchmark; watch live metrics and streamed logs.
- **05 · RESULTS — RANKED** — configs ranked by DECODE STAGE t/s, winner highlighted.
- **DOWNLOADED** — list of downloaded models, with LOAD / REMOVE.

The `/results` page shows the full benchmark history.

## Key Features

### Model Analysis

- Accepts a model as a full `http(s)` link or `user/model`, normalizing either form.
- Fetches and parses the repo's `README.md` to detect the **intended serving program** and extract the **proposed flags** (only lines that invoke `llama-server`/`llama-cli`/`llama-bench` count, so build/install commands don't leak flags).
- Falls back to manual serving-program selection when the README is ambiguous.
- **Hardware-fit verdict** per model and per `.gguf` file: fits VRAM, needs offload, CPU-only, or no-fit — with a warning banner when headroom is tight.
- Flags repos whose README doesn't document a llama.cpp serving command (download is gated behind an explicit "download anyway").

### Downloads

- Background downloads via the HF CLI with **live WebSocket log streaming** (progress bars included).
- Repos with multiple `.gguf` files show **one selectable checkbox per file**, each with its own fit verdict; only the selected files download.
- Cancel support — stops the download and runs `hf cache prune` to reclaim space.
- Concurrent or duplicate downloads are rejected (HTTP 409).

### Config Bank

- Generates N distinct configs by sweeping key performance flags (context size, GPU layers, batch size, spec flags) over per-server value pools.
- Every generated serving command is **editable before running** — edits take effect in the executed benchmark.
- Per-config **fit badge** (fits VRAM / offload / CPU / no fit, with needed GB).
- **Manual bench-tool selection**: the bench tool (`llama-bench` default, `speed-bench`, or `agentic`) is always selectable in the CONFIG BANK, per run.
- GENERATE is disabled until the model is downloaded.

### Benchmarking

- **Strictly serial** — one config at a time, because tokens/sec are measured on the same GPU.
- Results ranked by **DECODE STAGE t/s**; PROMPT PROCESSING t/s is also reported.
- Each config runs the server's native bench tool with mapped flags, averaged over a window capped at one minute.
- **Cancel** any active run at any time.
- Speculative-decoding / MTP models (README proposes `--spec-type`/spec flags, or the name contains `MTP`) are benchmarked with **speed-bench** (llama-server + `speed_bench.py`) instead of `llama-bench`, so MTP configs are actually measured.
- The **agentic** bench tool drives a real in-process plan→act agent harness (tools, planning loop, decision branching) against the serving model and reports effective AGENTIC t/s across the whole session — total tokens (prompt + completion) over wall time, so it reflects real interactive agentic load including every prefill.

### Results & Persistence

- Benchmark history persisted in **SQLite**, restored when you reload the page.
- Ranked results table highlights the winning config's row and digit.
- `/results` history page with **clear history**.
- On reload, an in-progress run **re-attaches** automatically and the latest completed run's results are restored.

### UX

- **"Lab counter" design**: flat panels, hairline rules, engineered-monospace digits, and a single neon-orange accent reserved for the lit digit and active state.
- **15 languages** with full i18n (en, zh, ja, de, fr, es, ko, ar with RTL, pt, it, nl, sv, no, da, fi), persisted and switchable from the header.
- Live hardware line in the header (GPU name · VRAM · RAM · arch).

## How It Works

Two local processes, talking over REST + WebSocket:

| Layer | Stack | Role |
|---|---|---|
| **Backend** | Python 3.11+ · FastAPI · uvicorn (port 8000) | Single `/api` router: model analysis, README parsing, config generation, hardware-fit math, HF CLI downloads (via PTY with live progress), serial benchmark orchestration, SQLite persistence, WebSocket event stream |
| **Frontend** | Vite 7 · React 18 · TypeScript · react-router (routes `/` and `/results`) | The instrument UI; streams progress over `ws://localhost:8000/api/ws`, with a 1-second polling fallback while a run is active |

External tools the backend spawns:

- **`hf` CLI** — model downloads, cache prune, cache rm (deletion).
- **`llama-bench`** — native benchmark for standard configs (`-o csv`, prompt from a coding-prompt workload, `-n 128 -r 2`).
- **`llama-server`** — serving side for speed-bench.
- **`speed_bench.py`** — speculative-decoding / MTP client; auto-discovered next to `llama-server`, honored via `LLMBENCH_SPEED_BENCH_SCRIPT`, or downloaded into `~/.llmbench/speed-bench/` on first use (best-effort). Always runs with `--limit 1 --category all --bench qualitative --osl 528`.
- **agentic** — in-process plan→act agent harness; runs a conversational benchmark against a live `llama-server` using function calling (plan → act → finish), reporting effective AGENTIC t/s plus steps, tool calls, plan revisions, avg/p95 latency, and context tokens (`--steps 10 --max-tokens 4096 --task codebase_refactor` by default). Requires a model that supports OpenAI tool calling.
- **`nvidia-smi`** — GPU name / VRAM / driver detection.

## Data & Configuration

All app data lives in `~/.llmbench` by default (`LLMBENCH_DATA_DIR`):

| Path | Contents |
|---|---|
| `~/.llmbench/llmbench.db` | SQLite database (servers, models, runs, configs, results) |
| `~/.llmbench/gguf/` | Local GGUF drop directory (`LLMBENCH_GGUF_DIR`) |
| `~/.llmbench/speed-bench/` | Provisioned `speed_bench.py` + `speed-bench-*.json` result artifacts |
| `~/.cache/huggingface/hub` | HF model cache (`LLMBENCH_HF_CACHE_DIR` to override) |

Environment variables (all prefixed `LLMBENCH_`):

| Variable | Default | Purpose |
|---|---|---|
| `LLMBENCH_DATA_DIR` | `~/.llmbench` | App data dir |
| `LLMBENCH_GGUF_DIR` | `<data_dir>/gguf` | Local GGUF directory |
| `LLMBENCH_HF_CACHE_DIR` | HF default | HF cache override |
| `LLMBENCH_LLAMA_CPP_BIN_DIR` | auto-detect | Directory holding `llama-bench` / `llama-server` |
| `LLMBENCH_SPEED_BENCH_SCRIPT` | auto-discover | Explicit `speed_bench.py` path |
| `LLMBENCH_BENCHMARK_TIMEOUT_S` | `60` | llama-bench timeout |
| `LLMBENCH_SPEED_BENCH_TIMEOUT_S` | `300` | speed-bench client timeout |
| `LLMBENCH_SPEED_BENCH_OSL` | `528` | Default OSL for speed-bench |
| `LLMBENCH_WORKLOAD_FILE` | `backend/data/coding_prompts.jsonl` | Coding-prompt workload for prompt token counts |

## Platform Notes

- **Linux/macOS** — `up.sh`/`down.sh` work as-is. On macOS, RAM detection uses `psutil` (no `/proc` dependency); install llama.cpp via Homebrew (`brew install llama.cpp`) or a Metal build. Homebrew ships only compiled binaries, so the app auto-downloads `speed_bench.py` on the first MTP benchmark. GPU benchmarking is NVIDIA/CUDA-oriented; on Apple Silicon the app boots and serves but GPU-fit semantics are unchanged.
- **Windows** — `up.bat`/`down.bat` run the same workflow via `scripts\up.ps1` / `scripts\down.ps1`. They install the Windows-only `pywinpty` extra (ConPTY, so download progress bars render like Linux), resolve `npm.cmd` (aborting with an actionable message if Node.js is missing), and install the optional speed-bench deps so MTP benchmarks work with prebuilt Windows builds that ship no Python tools. Install llama.cpp yourself — grab a prebuilt build from the [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases); `up.bat` resolves it from `LLMBENCH_LLAMA_CPP_BIN_DIR`, PATH, or standard locations.

## Tests

| Suite | Command |
|---|---|
| Backend | `cd backend && python -m pytest` |
| Frontend (typecheck + unit) | `cd frontend && npx tsc -b && npx vitest run` |
| E2E (Playwright) | `cd frontend && npx playwright test` |

CI (`.github/workflows/ci.yml`) runs backend `pytest` on Ubuntu/Windows/macOS, frontend `tsc` + `vitest` on Ubuntu, and Playwright e2e with a self-managed mock backend — no real server or HF CLI required.

## Project Docs

- [`PRODUCT.md`](PRODUCT.md) — product purpose, positioning, capabilities and constraints.
- [`DESIGN.md`](DESIGN.md) — the "lab counter" design system (colors, typography, layout).
- [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) — requirements and failure workflows in detail.
