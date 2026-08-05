# llama.cpp Bench Adaptation — Design Spec

Date: 2026-08-04
Status: Approved (pending spec review)

## Overview

The RUN BENCHMARK flow reports `Error: run failed` for a GGUF model even though
a working llama.cpp build is installed locally. Root cause: the app's llama.cpp
integration targets an older `llama-bench` CLI and CSV format, and never finds
the locally-built `llama-bench` (it is not on PATH).

This spec adapts the llama.cpp bench pipeline to the installed `llama-bench`
build (v9992, built under `/home/ruben/llama.cpp/build/bin`) so a real run
completes and produces ranked results on this machine. vLLM and sglang are out
of scope (their modules are not installed; their readiness flag is a weak
`python` existence check).

## Goals

- Locate `llama-bench` reliably: a configurable binary directory, falling back
  to PATH lookup, driving both the readiness indicator and the actual run.
- Generate a `llama-bench` command the installed build accepts, referencing the
  actual downloaded GGUF file (resolved backend-side, no frontend change).
- Parse the installed build's CSV output into PROMPT PROCESSING t/s and
  DECODE t/s, while keeping the legacy CSV parser working.
- Surface run failures instead of swallowing them (log the exception that
  currently marks runs `failed` with no traceback).

## Non-Goals

- vLLM / sglang bench pipelines and their readiness detection.
- Supporting arbitrary llama-bench versions beyond v9992 + the legacy format
  already parsed today.
- Changing the frontend's RUN flow or the WebSocket protocol.

## Binary Resolution

`Settings` gains an optional `llama_cpp_bin_dir` (env `LLAMA_CPP_BIN_DIR`,
default empty). When set, it points at a directory containing `llama-bench`
(e.g. `/home/ruben/llama.cpp/build/bin`).

A helper `resolve_bench_binary(server_id)`:

- For `llama.cpp`: if `llama_cpp_bin_dir` is set, return `<dir>/llama-bench`
  when it exists; otherwise fall back to `shutil.which("llama-bench")`.
- For `vllm`/`sglang`: unchanged (`python`).

`detect_binaries()` uses the resolver so the "ready" indicator matches what a
run would actually execute. `BenchmarkRunner` runs the resolved absolute path,
so a bare `llama-bench` no longer raises `FileNotFoundError`.

## Command Generation (llama.cpp)

`build_bench_command` for `llama.cpp` emits:

```
<llama-bench> -m <local_gguf_path> -ngl <n> -b <batch> -p <prompt_count>
              -n <gen_count> --fit-ctx <ctx> -r 2 -o csv
```

Changes vs. the legacy command:

- `-m` is the resolved local GGUF path (from the model DB row / downloaded
  snapshot), not `repo_id`.
- `-c`/`--ctx-size` is removed (not a v9992 option); its value is mapped onto
  `--fit-ctx <ctx>` (verified accepted, rc=0).
- The stray `-hf <repo_id>` is dropped (the model is local).
- `-p`/`-n` are token counts (see Workload Sizing).

Other server branches are unchanged.

## Local GGUF Path Resolution

During `POST /configs/generate`, the backend resolves the llama.cpp model path
once per config using the existing `_resolve_download_path` logic (llama.cpp
GGUF dir → largest `*.gguf` → HF snapshot). The resolved path feeds both
`build_serving_command(..., gguf_path=...)` and `build_bench_command(..., model_ref=<path>)`.

No frontend change is required: the frontend already sends `repo_id` (and does
not send `gguf_path`), and the backend can resolve the downloaded file itself.

## Workload Sizing

`coding_prompts.jsonl` remains the workload source. llama-bench v9992 accepts
token counts, not a prompt file, so counts are derived:

- `prompt_tokens = max(1, sum_of_line_lengths // 4)` (line lengths exclude
  trailing newlines).
- `gen_tokens = 128` (fixed DECODE stage size).
- If the workload file is missing or empty, fall back to `-p 512 -n 128`.

## CSV Parsing

`parse_llama_bench_csv` becomes version-tolerant:

- If the CSV has an `avg_ts` column (v9992): the row with `n_prompt > 0`
  yields `prompt_processing_tps`; the row with `n_gen > 0` yields `decode_tps`;
  both read `avg_ts`.
- If the CSV has `test`/`t/s` columns (legacy): unchanged behavior.

The runner logic that treats `decode_tps is None` as a failed result is
unchanged.

## Error Surfacing

`_run_job`'s `except Exception` currently marks the run `failed` with no log.
Add `logging.exception(...)` there (and keep the existing WS `run_done failed`
broadcast) so future run failures are diagnosable.

## Testing

Backend:

- `build_bench_command("llama.cpp", ...)` asserts the new CLI shape: resolved
  `-m` path, `--fit-ctx`, no `-c`, no `-hf`, `-p`/`-n` as integers.
- `resolve_bench_binary` unit tests: bin-dir set vs. PATH fallback.
- `parse_llama_bench_csv` accepts a v9992-style CSV fixture (avg_ts +
  n_prompt/n_gen) and still parses the legacy fixture.
- Workload sizing derives counts from a sample `coding_prompts.jsonl`.
- Live verification: run one llama.cpp config for the LFM2-350M GGUF through
  the real runner and confirm a non-None `decode_tps` and a `completed` run.

## Open Items

- Confirm `--fit-ctx` semantics with `--fit-target` absent (inert vs. applied);
  if inert, `--fit-ctx` still documents intent and is harmless. Not blocking.
