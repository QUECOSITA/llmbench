# llama.cpp HF-Repo Model Resolution + Spec-Flag Sweeping — Design Spec

Date: 2026-08-05
Status: Approved

## Overview

The CONFIG BANK generates llama.cpp configs whose serving command references the
model with `-m <local_gguf_path>` and whose bench command uses
`llama-bench -m <local_gguf_path>`. A manually-tested serving invocation that
resolves the model via Hugging Face and enables MTP speculative decoding —

```
llama-server --hf-repo GazTrab/Qwen3.6-27B-MTP-UD-IQ3_XXS-GGUF \
  --hf-file Qwen3.6-27B-MTP-UD-IQ3_XXS.gguf \
  --spec-type draft-mtp --spec-draft-n-max 2 \
  -c 56000 --fit on -fa on -ngl 999 -t 20 \
  --no-mmap --jinja -ctk q4_0 -ctv q4_0 --host 0.0.0.0 --port 8000
```

— yields better results. This spec makes the CONFIG BANK generate llama.cpp
configs the same way: resolve the model with `--hf-repo`/`--hf-file` instead of
`-m <path>`, and sweep `--spec-type` / `--spec-draft-n-max` as key flags with the
correct values (`draft-mtp`, `2`).

## Goals

- llama.cpp serving commands use `--hf-repo <repo_id> --hf-file <gguf_filename>`
  instead of `-m <local_path>` (fallback preserved when no file is known).
- llama-bench invocations use `-hfr <repo_id> -hff <gguf_filename>` instead of
  `-m <local_path>` (fallback preserved when no file is known).
- The CONFIG BANK sweeps `--spec-type` and `--spec-draft-n-max` for llama.cpp so
  configs vary them, and every config's serving command carries the correct
  values (`--spec-type draft-mtp`, `--spec-draft-n-max 2` as baseline).
- Readme `--spec-type mtp` (invalid value) canonicalizes to the valid
  `draft-mtp`.
- Spec flags never leak into llama-bench (server-only; llama-bench rejects them).

## Non-Goals

- Measuring speculative-decoding throughput: llama-bench cannot run spec flags,
  so spec-only config differences produce duplicate bench runs with no measured
  difference. Accepted by the user.
- Adding `-c 56000` / `--fit on` handling beyond what readme extraction already
  produces; the spec covers model resolution + spec flags only.
- vLLM / sglang changes.

## Config Bank (backend/app/flags.py)

`KEY_FLAGS["llama.cpp"]` gains `--spec-type`, `--spec-draft-n-max` (appended
after the existing ctx / gpu-layers / batch keys, so spec variants sweep last).

`VALUE_POOLS["llama.cpp"]` gains:

- `--spec-type`: `["draft-mtp", "none"]`
- `--spec-draft-n-max`: `[2, 3]`

`DEFAULTS["llama.cpp"]` gains `--spec-type: draft-mtp`, `--spec-draft-n-max: 2`.

`_baseline` normalizes readme spec-type values through
`{"mtp": "draft-mtp", "draft-mtp": "draft-mtp"}` before merging readme flags.

Because `_baseline` seeds DEFAULTS first and `generate_configs` sweeps each key
flag in order, the baseline config (index 1) always carries `--spec-type
draft-mtp --spec-draft-n-max 2`; the `none` / `3` variants appear once N is large
enough to reach them (they sweep last).

## Serving Command

`build_serving_command(server_id, repo_id, flags, gguf_filename=None,
gguf_path=None)`. For llama.cpp:

- if `gguf_filename` is set: `llama-server --hf-repo <repo_id> --hf-file
  <gguf_filename> <flags>`
- elif `gguf_path` is set: `llama-server -m <gguf_path> <flags>` (fallback)
- else: `llama-server <flags>` (unchanged today)

`_flag_tokens` already renders flag + value pairs, so `--spec-type draft-mtp` and
`--spec-draft-n-max 2` appear in the serving command automatically.

## Bench Command (backend/app/servers.py)

`build_bench_command(..., gguf_filename=None)`. For llama.cpp:

- if `gguf_filename` is set: `llama-bench -hfr <model_ref> -hff <gguf_filename>
  ...` where `model_ref` is the repo id
- else: `llama-bench -m <model_ref> ...` (current behavior)

The existing `_LLAMA_BENCH_FLAGS` whitelist already strips `--spec-type` and
`--spec-draft-n-max` from llama-bench (verified: this build rejects
`--spec-type` with "invalid parameter for argument"). No change needed there.

## API Wiring (backend/app/api.py)

In `POST /configs/generate`, capture the gguf filename:

- if the caller provided `gguf_path`, derive the filename via `os.path.basename`
- otherwise `_resolve_download_path(s, repo_id, "llama.cpp", None)` already
  returns `(local_path, name, size)`; use `name`

Pass `gguf_filename=` to both `build_serving_command` and
`build_bench_command`. For the bench command pass `repo_id` (not the resolved
path) as the model ref so `-hfr`/`-hff` resolve the HF repo.

## Tests

TDD (RED → GREEN):

- `test_flags.py::test_gguf_llama_command`: serving command contains
  `--hf-repo org/model --hf-file x.gguf`, not `-m`.
- `test_flags.py` (new): readme `--spec-type mtp` normalizes to `draft-mtp` in
  the generated baseline.
- `test_servers.py::test_build_bench_command_llama`: with `gguf_filename`, cmd
  is `llama-bench -hfr <repo> -hff <file>`; `-hf` flag still stripped.
- `test_servers.py::test_build_bench_command_llama_filters_server_only_flags`:
  spec flags still absent from bench; `-m` flag from readme still stripped.
- `test_servers.py` (new): bench command contains no `--spec-type` /
  `--spec-draft-n-max` when flags include them.
- `test_api.py::test_generate_configs_llama_resolves_local_gguf`: bench has
  `-hfr org/model -hff model.Q4_K_M.gguf`; serving contains `--hf-repo
  org/model --hf-file model.Q4_K_M.gguf`.
- `test_api.py::test_generate_configs_llama_falls_back_to_repo_id_when_no_gguf`:
  unchanged — no gguf known, bench falls back to `-m org/model`.

## Frontend

No changes. CONFIG BANK renders `serving_command` from the API verbatim and the
flag sweep is server-side; `ConfigRow` / `ConfigBank.tsx` are untouched.

## Trade-offs (accepted)

Spec-only config differences yield identical llama-bench commands, so they run
the same benchmark multiple times and rank as ties. This is accepted: llama-bench
cannot measure speculative decoding, and the served configs (with correct spec
flags) are the primary output the user copies out of CONFIG BANK.
