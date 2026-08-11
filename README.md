# LLM Bench

[![CI](https://github.com/QUECOSITA/llmbench/actions/workflows/ci.yml/badge.svg)](https://github.com/QUECOSITA/llmbench/actions/workflows/ci.yml)

Benchmark Hugging Face coding LLMs with llama.cpp to find the best serving config by DECODE STAGE tokens/sec.

The tool reads the model's README to detect the intended serving program (llama.cpp) and proposed flags, generates N editable config commands, and benchmarks them serially with llama.cpp's native bench tools.

## Features

- Analyze a model from a HF link or `user/model`: serving-program detection, proposed flags, hardware fit verdict (VRAM/RAM vs. model size) with a warning banner when headroom is tight.
- Download models via the HF CLI as a background job with live WebSocket log streaming; llama.cpp downloads resolve the GGUF file path and size. Concurrent or duplicate downloads are rejected (409).
- Model download button with progress in the model input panel.
- Serial benchmarks ranked by DECODE STAGE t/s (PROMPT PROCESSING t/s also reported), persisted in SQLite.
- llama.cpp models that propose speculative decoding (README `--spec-type` / spec flags) or carry `MTP` in the name are benchmarked with `speed-bench` (llama-server + `speed_bench.py`) instead of `llama-bench`, so MTP configs are actually measured.

## Requirements

- NVIDIA GPU workstation; Python 3.11+, Node 20+.
- HF CLI (`hf` / `huggingface-cli`) for downloads.
- Serving binaries to benchmark: llama.cpp (`llama-bench`/`llama-server`). Availability is auto-detected and shown as readiness in the UI.
- To benchmark speculative-decoding / MTP llama.cpp models, the llama.cpp source tree must include `tools/server/bench/speed-bench/speed_bench.py` (auto-discovered next to `llama-server`, or point `LLMBENCH_SPEED_BENCH_SCRIPT` at it) and its Python deps installed (`cd backend && pip install -e '.[speed-bench]'`). The speed-bench client always runs with `--limit 1 --category all --bench throughput_1k`.

## Run

One-shot start (installs deps, then launches backend + frontend in the background):

```
./up.sh
```

This creates the backend venv, installs deps, and starts `uvicorn app.main:app --port 8000` and the frontend dev server (`npm install && npm run dev`).

Open http://localhost:5173.

Stop everything:

```
./down.sh
```

This kills the `uvicorn` and `vite` processes and reminds you to `deactivate` the backend venv. To run manually:

Backend:
```
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --port 8000
```
Frontend: `cd frontend && npm install && npm run dev`

## Tests

Backend: `cd backend && python -m pytest`
Frontend: `cd frontend && npx vitest run && npx playwright test`
