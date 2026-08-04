# LLM Bench

Benchmark Hugging Face coding LLMs across llama.cpp, vLLM, and sglang to find the best serving config by DECODE STAGE tokens/sec.

The tool reads the model's README to detect the intended serving program and proposed flags, generates N editable config commands, and benchmarks them serially with each server's native bench tool.

## Features

- Analyze a model from a HF link or `user/model`: serving-program detection, proposed flags, hardware fit verdict (VRAM/RAM vs. model size) with a warning banner when headroom is tight.
- Download models via the HF CLI as a background job with live WebSocket log streaming; llama.cpp downloads resolve the GGUF file path and size. Concurrent or duplicate downloads are rejected (409).
- Per-server download buttons with progress in the model input panel.
- Serial benchmarks ranked by DECODE STAGE t/s (PROMPT PROCESSING t/s also reported), persisted in SQLite.

## Requirements

- NVIDIA GPU workstation; Python 3.11+, Node 20+.
- HF CLI (`hf` / `huggingface-cli`) for downloads.
- Serving binaries to benchmark: llama.cpp (`llama-bench`/`llama-server`), vLLM, sglang. Availability is auto-detected and shown as readiness in the UI.

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
