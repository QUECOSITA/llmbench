# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

A solo ML/backend engineer on their own NVIDIA-GPU workstation who wants to determine, quickly, the best way to serve a specific Hugging Face coding LLM before committing to a setup.

## Product Purpose

Benchmark Hugging Face LLMs across the llama.cpp, vLLM, and sglang serving stacks to find the best serving configuration for a given model — where "best" is defined by the most tokens/second in the DECODE stage (with PROMPT PROCESSING t/s also reported). Results are comparable across configs and stacks.

## Positioning

The tool reads the model's own README to determine which serving program the model is meant to run with and which flags the model card proposes, then turns those into editable full config commands and benchmarks them with each server's native bench tool — so the configs tested are the ones the model author intended, not a generic template.

## Operating Context

- Runs locally on one machine with a single NVIDIA GPU (CUDA).
- Uses standard locations: Hugging Face cache (`~/.cache/huggingface`) for vLLM/sglang models, a configured GGUF directory for llama.cpp.
- Uses the HF CLI (`huggingface-cli` / `hf` CLI) for downloads.
- Requires the serving programs' binaries to be present: `llama.cpp` (llama-bench / llama-server), `vLLM`, `sglang`. Availability is auto-detected and shown as readiness in the UI.
- Benchmarks are strictly serial (one config at a time) because tokens/sec are computed on the same GPU; concurrent runs would corrupt results.

## Capabilities and Constraints

- Accepts a Hugging Face model as a full `http(s)` link or as `user/model`, normalizing either form.
- Fetches and parses `README.md`/`readme.md` from the repo.
- Determines the serving program(s) from the README via heuristics; falls back to manual user selection when ambiguous or missing.
- Extracts flags the README proposes.
- Generates N (user-provided integer) distinct full config commands by varying key performance flags (context length, quantization, batch size, GPU layers, etc.) from per-server value pools. Every generated config is editable by the user before running.
- Verifies whether the model is already downloaded for the target server; if not, prompts the user to download via the HF CLI.
- For llama.cpp, the user picks the GGUF quant file from the repo's file listing.
- RUN BENCHMARK triggers a serial full-program benchmark per config: run the server's native bench tool with mapped flags, measure PROMPT PROCESSING and DECODE STAGE tokens/sec averaged over a benchmark window capped at one minute, unload the model, close the process, and continue to the next config.
- Shows a results table: model name, program used, each flag in its own column, PROMPT PROCESSING t/s, DECODE STAGE t/s, ordered by DECODE STAGE t/s.
- Persists benchmark history in SQLite.
- Has a Downloaded section listing, per serving program (llama.cpp, vLLM, sglang), the downloaded models with the option to remove them.
- Single-user local tool; no authentication.

## Brand Commitments

None established.

## Evidence on Hand

None. No testimonials, benchmarks, or case studies exist yet; future work must not fabricate them.

## Product Principles

- **Serial by design:** one config benchmarked at a time; never overlap GPU work, since results would be meaningless.
- **README fidelity:** the configs tested come from the model's own proposed flags and intended serving program, with the full serving command visible and editable.
- **Real measurement:** timing comes from each server's native bench tool, not synthetic loads.
- **Comparable output:** every run reports the same two metrics so configs can be ranked by DECODE STAGE t/s.
- **Local-first:** everything stays on the machine; results and model state live in local SQLite and standard caches.

## Accessibility & Inclusion

No product-specific accessibility requirements established.
