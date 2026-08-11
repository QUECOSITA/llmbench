# speed-bench for Speculative-Decoding / MTP Models — Design Spec

Date: 2026-08-07
Status: Approved

## Overview

llama.cpp configs that enable speculative decoding (e.g. MTP draft models) are
currently benchmarked with `llama-bench`, which strips server-only spec flags
(`--spec-type`, `--spec-draft-n-max`, ...) from the bench invocation. The result
is that MTP configs benchmark as duplicates with no measured difference.

This spec makes llmbench use the llama.cpp **speed-bench** server benchmark
(`tools/server/bench/speed-bench/speed_bench.py`) instead of `llama-bench` when
the model qualifies for speculative-decoding benchmarking:

- the model repo's README proposes a speculative-decoding flag (e.g. `--spec-type`), **or**
- the model name (repo id / GGUF filename) contains `MTP`.

speed-bench is a Python client that benchmarks an **already-running**
`llama-server` through its OpenAI-compatible API and reports per-category
throughput (`avg_prompt_t/s`, `avg_pred_t/s`) plus draft `accept_rate`.

All existing llmbench behavior is unchanged when the above criteria are not met.

## Goals

- Detect "bench this model with speed-bench" from the README (spec flag) or the
  model name (MTP) — computed once at config generation and carried on each
  config as `bench_tool`.
- Generate a speed-bench client command for qualifying llama.cpp configs that
  always includes `--limit 1 --category all --bench throughput_1k`.
- Run such a config as: start `llama-server` (the user's edited serving command
  on a free port) → wait for `/health` → run `speed_bench.py` → parse the
  `--output` JSON → kill the server.
- Keep every existing llama-bench / vLLM / sglang path byte-identical when the
  criteria are not met.

## Non-Goals

- Changing the llama-bench flow in any way for non-qualifying models.
- Supporting speculative decoding on vLLM / sglang (their native bench tools are
  unchanged).
- Replacing the local `coding_prompts.jsonl` workload for llama-bench; speed-bench
  uses the SPEED-Bench dataset (`nvidia/SPEED-Bench`, bench `throughput_1k`) per
  the official speed-bench README.
- Editing the user's serving command (e.g. forcing a larger `--ctx-size`); the
  served config stays exactly what the user wrote.

## Detection

`is_spec_decoding_model(repo_id, gguf_filename=None, readme_flags=None) -> bool`:

- True if `"mtp"` appears (case-insensitive) in `repo_id` or `gguf_filename`.
- True if any key in `readme_flags` is a known speculative-decoding flag:
  `--spec-type`, `-md`/`--model-draft`, `--model-mtp`/`-mtmd`, `--draft-max`,
  `--draft-min`, `--draft-p-min`, `--spec-draft-n-max`, `--spec-draft-n-min`,
  `--spec-raw-logits`, `--spec-heuristics`, `--spec-heuristic-acc`,
  `--spec-heuristic-min-tokens`.
- Otherwise False.

Applied only when `server_id == "llama.cpp"`.

**Why detect from `readme_flags` + name and not from generated flags:** every
llama.cpp config carries `--spec-type draft-mtp` as a generation default, so the
config's own flags cannot be the source of truth. `readme_flags` are
README-derived (via `readme_parser.extract_flags`); the MTP-name check is the
safety net for READMEs that do not place the flag inside a recognized command
block.

## `bench_tool` round-trip

The decision is computed once in `POST /configs/generate` and stored on each
config as `bench_tool: "speed-bench" | "llama-bench"`. The frontend round-trips
it on `POST /benchmarks` (exactly as it already round-trips `flags`,
`serving_command`, `bench_command`). `_rebuild_bench_command` trusts it, since it
cannot be safely re-derived from the edited serving command's flags (default
spec flags).

## Backend changes

### `servers.py`

- `_SPEC_DECODING_FLAGS` set and `is_spec_decoding_model(...)`.
- `resolve_serving_binary(server_id, bin_dir)` — resolves `llama-server`, mirroring
  `resolve_bench_binary`.
- `resolve_speed_bench_script(bin_dir, configured=None)` — returns the configured
  `LLMBENCH_SPEED_BENCH_SCRIPT` when set and present; otherwise auto-discovers
  `speed_bench.py` in the llama.cpp source tree that contains the resolved
  `llama-server` binary by walking up from the binary's directory looking for
  `<tree>/tools/server/bench/speed-bench/speed_bench.py`; else None.
- `build_speed_bench_command(script, osl=128, url="localhost:8080", output=...)`
  → `[sys.executable, script, "--url", url, "--bench", "throughput_1k",
  "--category", "all", "--limit", "1", "--osl", str(osl), "--output", output]`.
- `build_server_command(serving_command, bin_dir)` — shlex-split the editable
  serving command, swap the first token for the resolved `llama-server` binary,
  strip any existing `--port`/`--host` (not `-p`, which is `--parallel`).
- `detect_binaries` gains an additive `"speed-bench": <bool>` readiness key.
- `build_bench_command` is **unchanged**.

### `benchmark.py`

- `parse_speed_bench_json(text)` — parse the `--output` JSON; find the `overall`
  row in `summary`; map `avg_pred_t_s` → `decode_tps`, `avg_prompt_t_s` →
  `prompt_processing_tps`; `None`s when absent.
- `SpeedBenchRunner` — holds `server_command`, `bench_command`, `timeout_s`,
  `startup_timeout_s`, `output_dir`.
  - `run(on_output)`:
    1. allocate a free port; pick a temp `--output` JSON path under `output_dir`.
    2. spawn `server_command + ["--port", str(port), "--host", "127.0.0.1"]`,
       streaming output via the same TtyStream pump as `BenchmarkRunner`.
    3. poll `GET http://127.0.0.1:{port}/health` until 200 or `startup_timeout_s`.
    4. rewrite the client command's `--url` and `--output` values for the port /
       temp path; run it with a `timeout_s` cap, streaming output.
    5. read the output JSON, parse via `parse_speed_bench_json`.
    6. `finally`: kill the server.
  - Returns the standard result dict `{status, prompt_processing_tps, decode_tps,
    duration_s, output}`.
  - `abort()` kills both the server and client processes.
- `BenchmarkRunner` is **unchanged**; the TtyStream pump logic is reused (kept
  local to each class).

### `config.py`

- `speed_bench_script: Path | None = None` (env `LLMBENCH_SPEED_BENCH_SCRIPT`).
- `speed_bench_timeout_s: int = 300`.
- `speed_bench_osl: int = 128`.

### `api.py`

- `POST /configs/generate`: when `server_id == "llama.cpp"` and
  `is_spec_decoding_model(repo_id, gguf_filename, readme_flags)`, set
  `cfg["bench_tool"] = "speed-bench"` and build the speed-bench bench command;
  otherwise `cfg["bench_tool"] = "llama-bench"` and the existing
  `build_bench_command` path (unchanged).
- `_rebuild_bench_command`: for `bench_tool == "speed-bench"`, build
  `cfg["server_command"]` (from the edited serving command) and
  `cfg["bench_command"]` (speed-bench client command); if the llama-server binary
  or the speed-bench script cannot be resolved, set `cfg["bench_error"]` with a
  clear message. The llama-bench path is unchanged.
- `start_run`: after rebuilding, if any config has `bench_error`, reject with
  HTTP 422 and the message (clear failure — no silent wrong results).
- `_run_job`: branch on `cfg["bench_tool"]` → `SpeedBenchRunner` vs
  `BenchmarkRunner`.

### `pyproject.toml`

- Optional extra `[speed-bench] = ["datasets", "requests", "tqdm"]`. These deps
  are needed only by the spawned `speed_bench.py` subprocess; no new hard
  dependencies, no new runtime imports.

## Frontend changes

- `api/client.ts`: add `bench_tool?: string` to the `generateConfigs` return type.
- `components/ConfigBank.tsx`: add `bench_tool?: string` to `ConfigRow`; render a
  small `SPEED-BENCH` badge on qualifying rows.
- `App.tsx` `onRun`: include `bench_tool: c.bench_tool` in the `/benchmarks`
  payload.
- `e2e/mock-server.ts`: add `bench_tool: "llama-bench"` to the canned config so
  the e2e flow stays type-consistent.

## Tests

TDD (RED → GREEN):

- `test_servers.py`: `is_spec_decoding_model` cases (MTP in repo id, MTP in GGUF
  filename, `--spec-type` in readme flags, `-md` in readme flags, none → False);
  `resolve_speed_bench_script` auto-discovery + configured override;
  `build_speed_bench_command` contains `--limit 1 --category all
  --bench throughput_1k`, `--url`, `--output`; `build_server_command` swaps the
  binary and strips `--port`/`--host`.
- `test_benchmark.py`: `parse_speed_bench_json` (overall row, missing overall,
  invalid JSON); `SpeedBenchRunner` with faked `create_subprocess_exec` + faked
  `/health` (asserts metric mapping, server teardown).
- `test_api.py`: generate with `--spec-type` readme flag → configs carry
  `bench_tool: speed-bench` and a speed-bench bench command; non-MTP model →
  `bench_tool: llama-bench` with an unchanged llama-bench command;
  `_rebuild_bench_command` speed-bench branch; `start_run` rejects with 422 when
  the script cannot be resolved.

## Trade-offs (accepted)

- `--limit 1 --category all` on `throughput_1k` runs 3 samples (high_entropy,
  low_entropy, mixed). If one sample fails (e.g. `-c` too small for the 1024-token
  inputs), the config reports failed with the error visible in the live console.
- First model load can take 30–120s; the 300s `speed_bench_timeout_s` budget
  covers server startup plus the client run.
- README detection relies on `readme_flags` (README-derived); READMEs that never
  put the spec flag in a recognized command block are still caught by the
  MTP-name check.
