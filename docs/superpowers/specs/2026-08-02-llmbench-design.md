# LLM Bench — Design Spec

Date: 2026-08-02
Status: Approved (pending spec review)

## Overview

A local single-user web app that benchmarks Hugging Face coding LLMs across the
llama.cpp, vLLM, and sglang serving stacks to find the best serving
configuration for a given model — where "best" is the most tokens/second in the
DECODE stage (PROMPT PROCESSING t/s also reported). The app reads the model's
own README to determine the intended serving program and proposed flags, turns
those into editable full config commands, and benchmarks each config serially
with each server's native bench tool.

## Goals

- Normalize a Hugging Face model input given as a full `http(s)` link or as `user/model`.
- Determine from the README which serving program the model is meant to run with; allow manual override when ambiguous.
- Extract proposed flags from the README and generate N (user-supplied integer) distinct full config commands, all user-editable.
- Detect the machine's hardware and verify the model fits VRAM → RAM → neither, warning (never blocking) when it won't fit.
- Verify the model is downloaded for the target server; if not, drive a download via the HF CLI.
- Run benchmarks serially (one config at a time), each up to 60s, via each server's native bench tool; unload/close after each config.
- Show results ranked by DECODE STAGE t/s, persist all history in SQLite, and expose a dedicated Results section with all past and current runs.
- Show a Downloaded section grouped by serving program with remove options.

## Workflow

1. **Hardware** — detected at startup and surfaced in the UI (CPU, arch, RAM, GPU + VRAM).
2. **Model input** — paste a link or `user/model`; Analyze.
3. **Analysis** — normalize input; fetch README + file listing; detect serving program(s); extract proposed flags; run the model-fit check; pick GGUF quant when the target is llama.cpp.
4. **Configs** — enter N; generate N editable full serving commands + structured flag table.
5. **Run** — RUN BENCHMARK starts the serial queue; progress streams over WebSocket.
6. **Results** — inline ranked table plus the dedicated Results/History section.
7. **Downloaded** — per-server model list with removal.

## Architecture

- **Stack:** Python FastAPI backend + React/Vite frontend. SQLite via stdlib `sqlite3`. No auth (local single-user tool).
- **Benchmark orchestration:** in-process async worker with a single-slot serial queue (`asyncio.Lock`). Only one job runs at a time — never overlap GPU work, since t/s are computed on the same GPU.
- **Progress:** WebSocket broadcast of job events (config index, status, partial metrics, errors).
- **Persistence:** SQLite. Results survive restarts; benchmark jobs do not.

```
llmbench/
  backend/
    app/
      main.py          # FastAPI app, CORS, static, WS route
      config.py        # paths, cache dirs, settings
      db.py            # sqlite3 schema + repository
      hf.py            # HF API: normalize input, README, file listing, GGUF list, download via HF CLI
      readme_parser.py # detect serving program + extract proposed flags
      flags.py         # per-server flag defs + value pools + N-config generator
      servers.py       # adapters: binary detection, serving cmd, flag→bench mapping, unload
      hardware.py      # CPU/arch/RAM/GPU detection
      fit.py           # model-fit estimator (weights + KV cache + activations)
      benchmark.py     # serial runner: job state machine, subprocess, timing, parse results
      api.py           # REST endpoints + WS broadcaster
    tests/
  frontend/
    src/
      ...              # React/Vite app
```

## Data Model (SQLite)

- `servers` — registry: id (`llama.cpp`, `vllm`, `sglang`), display name, binary/detection commands, bench tool command, model store type (`gguf_dir` | `hf_cache`), unload/close behavior.
- `models` — id, repo_id, source (link|repo-id), server_id, format (`gguf`|`hf`), local_path, status (`downloaded`|`missing`), size_bytes, gguf_filename (nullable), downloaded_at. Unique on (repo_id, server_id).
- `configs` — id, run_id, server_id, model_id, flag_conf_json (ordered `{flag, value}` list), serving_command (full editable string), bench_command.
- `runs` — id, model_id, requested_n, created_at, status (`queued`|`running`|`completed`|`aborted`|`error`).
- `results` — id, config_id, prompt_processing_tps, decode_tps, duration_s, output_snippet, status (`ok`|`failed`), completed_at.

## API Surface

- `GET  /api/servers` — readiness (binary detection per server).
- `POST /api/models/analyze` — `{input}` → normalized repo_id, readme_text, detected_servers, extracted_flags, gguf_files, fit_verdict.
- `POST /api/models/download` — `{repo_id, server_id, gguf_filename?}` → starts download job; progress via WS.
- `GET  /api/models` — per-server downloaded list (HF cache scan + GGUF dir scan).
- `DELETE /api/models/{server_id}/{model_ref}` — remove a downloaded model.
- `POST /api/configs/generate` — `{repo_id, server_id, n}` → list of configs `{flag_conf, serving_command}`.
- `POST /api/benchmarks` — `{repo_id, configs[], workload}` → run_id; starts the serial job.
- `POST /api/benchmarks/{id}/abort` — cancel a running job.
- `GET  /api/benchmarks` — run history.
- `GET  /api/benchmarks/{id}` — full results for a run.
- `WS   /ws` — job progress events.

## Hardware Detection & Model-Fit Check

- CPU name/model + core/thread count (`os.cpu_count()`, `/proc/cpuinfo`, `lscpu`).
- Architecture via `platform`/`uname -m` (x86_64, aarch64, etc.).
- RAM total + available (`/proc/meminfo` or `os.sysconf`).
- GPU name + VRAM via `nvidia-smi` (fallback `pynvml`/PyTorch if available); "none" if no NVIDIA GPU → llama.cpp CPU-only routing.
- Model-fit: sum weight-file sizes (GGUF sizes for llama.cpp; safetensors shards for vLLM/sglang); estimate working memory `weights + kv_cache(ctx) + activations` with a conservative ×1.2 factor from the baseline config.
- Decision tree: fits VRAM → full GPU; exceeds VRAM but fits RAM → offload path (llama.cpp partial `-ngl`, others flagged CPU-only/note); architecture can't use GPU → full RAM load; weights alone exceed RAM → **warning only, never block**. Verdict feeds flag defaults (e.g. `-ngl`, `--gpu-memory-utilization`) and a warning banner.

## README Analysis Pipeline

- Fetch README.md / readme.md case-insensitively via the HF API.
- Serving-program detection (heuristic scoring): `.gguf` files present → +3 llama.cpp; `llama-server`/`llama-cli`/`llama.cpp`/`gguf` commands → +2; `vllm`/`vllm serve`/`from vllm import`/OpenAI api_server → +3; `sglang.launch_server`/`sglang serve` → +3. Top score wins; tie/none → manual picker.
- Flag extraction: scan code blocks for known server commands; pull `--flag value` / `--flag=value` tokens; map against a per-server registry (unknown flags flagged, known ones typed with pools).

## Config Generation

- Baseline = README flags + per-server defaults (vLLM `--gpu-memory-utilization 0.9`, sglang `--mem-fraction-static 0.9`, etc.).
- Remaining N−1 configs vary one key performance flag at a time across its value pool (llama.cpp: `--ctx-size`, `-ngl`, `--batch-size`; vLLM: `--max-model-len`, `--max-num-seqs`, `--gpu-memory-utilization`, `--enforce-eager`; sglang: `--context-length`, `--max-running-requests`, `--tp-size`); cycle pools if N exceeds combinations.
- Each config exposes a full serving command (editable) + structured flag table (editable), kept in sync.
- Deterministic (seeded) generation.

## Download Check & HF CLI

- vLLM/sglang: model considered downloaded when the HF cache snapshot (`~/.cache/huggingface/hub/models--{org}--{name}`) is complete.
- llama.cpp: downloaded when the chosen GGUF file exists in the configured GGUF dir.
- Missing → UI shows "Download with HF CLI" (`hf download <repo>` or `hf download <repo> --include "*.gguf"`), progress streamed over WS. Missing HF CLI → error with the exact manual command.

## Benchmark Execution Engine

Per config, serially:

1. Pre-flight: model present, server binary detected.
2. Map serving flags → bench-tool flags (`llama-bench`, vLLM `benchmark_throughput`, sglang bench).
3. Run the bench tool as a subprocess with a 60s cap; feed the built-in coding prompt set (function generation, bugfix, refactor, explanation, unit-test generation, code review).
4. Parse output → PROMPT PROCESSING t/s and DECODE STAGE t/s (llama-bench pp/tg; vLLM input/output t/s; sglang prefill/decode).
5. Unload/close the process (natural shutdown or kill).
6. Save result; emit WS event; next config.

Watchdog kills any subprocess that exceeds the cap. Abort stops the queue.

## Frontend — Visual World: Lab Counter

**Direction contract (nixie laboratory counter):**

- THESIS: the benchmark is an instrument — quantities are the interface. Refuses the dark-GPU-dashboard rut of heavy cards.
- OWN-WORLD: blackened-steel ground (`#16130f`-family), hairline panel rules (`#3a342b`/`#4a443a`), engraved-cap labels (small, letter-spaced, `#8a8478`), one neon-orange accent (`#FF7A00`) reserved for active state and the lit digits — especially DECODE STAGE t/s and the winning result row. Monospace numerals throughout; labels in engineered form caps.
- STORY: the visitor feeds a model, reads its intended program and flags off the README, generates an editable config bank, and watches the counters — the best config glows brightest, ranked forever after.
- FIRST VIEWPORT: persistent header bar (LLM BENCH + hardware spec), then numbered panels 01 MODEL INPUT → 02 CONFIG BANK → 03 RUN → 04 METRICS → 05 RESULTS — RANKED, then the Downloaded strip. Primary action is the RUN BENCHMARK button in the accent.
- FORM: nixie laboratory counter, challenged direction (seed `signals-instruments-nixie-laboratory-counter`), chosen by the user over transit-map, conference-program, and canon.

- Motion: single cross-fades for digit changes; mechanical-feeling progress; no scattered hover effects.
- Responsive: metric banks collapse to essential digits on phones; panels stack.

### Layout (single page, stacked panels)

- Header: product wordmark + hardware spec line.
- 01 MODEL INPUT — text input + ANALYZE; shows normalized repo, detected server, flag count, fit verdict.
- 02 CONFIG BANK — N integer input, GENERATE, editable config rows (each shows the full serving command + editable flag table).
- 03 RUN — RUN BENCHMARK button (disabled while a job runs) + live progress (config i/N, %, current metrics).
- 04 METRICS — PROMPT PROC t/s and DECODE STAGE t/s banks for the current/latest config.
- 05 RESULTS — RANKED — link/view into the dedicated Results section.
- DOWNLOADED strip — per-server counts with remove actions.

### Dedicated Results section (`/results`)

- Aggregates all runs (past + current) from SQLite history.
- Columns: run date, model, server program, each flag as its own column, PROMPT PROC t/s, DECODE STAGE t/s.
- Ranked by DECODE STAGE t/s by default; sortable; top row per run glows orange.
- Filters: model, server program, date range. Run row expands to show full configs/serving commands.
- Live updates via WS as new configs complete.

## Error Handling & Edge Cases

- Invalid model input → inline validation error; repo not found/gated → friendly error echoing the HF URL.
- README missing → defaults used for flags; manual serving-program picker.
- Model not downloaded → download prompt with progress; HF CLI missing → error + exact manual command.
- Server binary missing → server marked not-ready; configs for it disabled until installed.
- Bench tool crash/timeout → config marked failed (stderr snippet saved); run continues; summary lists failures.
- Concurrent run attempt → rejected while a job is active.
- Fit check → warning only, never blocks the run.
- Cancel/abort available during any run.
- Long flag values → truncated cells with full tooltips; t/s formatted to 1 decimal.

## Testing

- Unit: input normalizer; README parser (fixture READMEs); config generator (deterministic N, edit round-trip); serving→bench flag mapping; bench-output parsers (fixture stdout for llama-bench / vLLM / sglang); hardware detector; fit estimator; DB repository.
- Integration: serial runner with fake bench binaries — happy path, timeout kill, unload, abort, crash→continue.
- Frontend: Vitest + Testing Library for the config editor and results table (sorting, ranking); Playwright E2E against a mocked backend for the full flow.

## Out of Scope

- Parallel/concurrent benchmarking (never — invalidates GPU measurements).
- Authentication, multi-user.
- Installing missing server binaries from the UI.
- Non-NVIDIA GPU vendor support (AMD/Intel iGPU) beyond CPU-only fallback.

## Open Questions

- Exact bench-tool CLI wrappers for each server need confirming against installed versions at build time (llama-bench flags, vLLM `benchmark_throughput`, sglang bench entry points).
- GGUF dir location: configurable, default `~/models/gguf` or config setting.
