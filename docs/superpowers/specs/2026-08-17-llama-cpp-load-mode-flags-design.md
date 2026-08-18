# llama.cpp Config Bank Upgrade — `--load-mode none --no-mmproj` Design

Date: 2026-08-17
Status: Approved

## Overview

llama.cpp deprecated several server flags and introduced `--load-mode` and
mmproj auto-loading. The CONFIG BANK (`backend/app/flags.py`) must (1) stop
emitting deprecated flags, (2) always pin `--load-mode none --no-mmproj` at the
front of every generated llama-server serving command, and (3) map removed
speculative-decoding aliases from READMEs to their modern forms.

## Verification (llama.cpp b10472, built from `ggml-org/llama.cpp` master)

Ran `llama-server --help` / `llama-bench --help` on the locally built binaries
and cross-checked `common/arg.cpp`:

**Deprecated** (still accepted, warn on use; `arg.cpp:2524,2640,2649,2658`):
- `--mlock` → `--load-mode mlock`
- `--mmap` / `--no-mmap` → `--load-mode mmap` / `--load-mode none`
- `--direct-io` / `--no-direct-io` → `--load-mode dio`
- `--defrag-thold` / `-dt` → deprecated, "no longer necessary to specify"

**Removed** (rejected outright; `arg.cpp:4293-4321`):
- `--draft`, `--draft-n`, `--draft-max` → `--spec-draft-n-max`
- `--draft-min`, `--draft-n-min` → `--spec-draft-n-min`

**New:**
- `--load-mode MODE` (`-lm`): `auto|none|mmap|mlock|mmap+mlock|dio|numactl|isolate`
- `--mmproj-auto` / `--no-mmproj` / `--no-mmproj-auto` — mmproj is **downloaded
  automatically by default** when using `-hf`; `--no-mmproj` disables it
- `--mmproj-offload` / `--no-mmproj-offload`

**Caution (`arg.cpp:883`):** combining `--load-mode` with `--mlock`/`--mmap`/
`--direct-io` is itself deprecated and only the last flag wins. The config bank
must therefore never emit both.

## Decisions (user-approved)

1. **Pin `--load-mode none --no-mmproj` always.** Every generated llama-server
   serving command carries both, placed first (right after the model reference).
   They override any README-provided `--load-mode`, `--mmproj-auto`, or
   `--no-mmproj-auto`. Rationale: `none` avoids mmap on varied hardware; text-only
   benchmarking must not trigger unwanted mmproj auto-downloads.
2. **Drop deprecated memory-mode README flags.** `--mlock`, `--mmap`,
   `--no-mmap`, `--direct-io`, `--no-direct-io`, `--defrag-thold`, `-dt` are
   discarded when merging README flags (the pinned `--load-mode none` supersedes
   them; emitting both is itself deprecated).
3. **Map removed spec flags.** `--draft`/`--draft-n`/`--draft-max`/`--draft-n-max`
   → `--spec-draft-n-max`; `--draft-min`/`--draft-n-min` → `--spec-draft-n-min`
   (value-preserving) via `README_FLAG_MAP`.
4. **llama-server only.** `--load-mode` / `--no-mmproj` stay out of the
   llama-bench command (`_LLAMA_BENCH_FLAGS` whitelist unchanged; `--no-mmproj`
   is not a llama-bench flag).

## Config Bank (backend/app/flags.py)

`DEFAULTS["llama.cpp"]` is prepended with the pinned flags so they seed every
config and are emitted first by `_flag_tokens`:

```python
"llama.cpp": {"--load-mode": "none", "--no-mmproj": "",
              "--ctx-size": 4096, "--n-gpu-layers": 999, "--batch-size": 512,
              "--spec-type": "draft-mtp", "--spec-draft-n-max": 2},
```

New module constants:

- `LLAMA_DROPPED_FLAGS` — README flags dropped during `_baseline` merge
  (deprecated memory-mode flags + `--defrag-thold`/`-dt` + `--mmproj-auto`/
  `--no-mmproj-auto`).
- `LLAMA_PINNED_FLAGS = {"--load-mode": "none", "--no-mmproj": ""}` — re-asserted
  in `_baseline` after the README merge so the pin always wins.

`KEY_FLAGS` / `VALUE_POOLS` unchanged: the pinned flags are constants, not swept.

## README Map (backend/app/servers.py)

`README_FLAG_MAP["llama.cpp"]` gains the removed-spec aliases so `_baseline`
canonicalizes them, and `_SPEC_DECODING_FLAGS` gains `--draft`, `--draft-n` so
READMEs still using the removed names trigger spec-decoding detection.

## Bench Command

`_LLAMA_BENCH_FLAGS` unchanged. `--load-mode` and `--no-mmproj` are filtered out
by the existing whitelist, so llama-bench invocations never receive them.

## Frontend

No logic change — `ConfigBank.tsx` renders `serving_command` verbatim. Sample
commands in `frontend/src/components/ConfigBank.test.tsx`,
`frontend/src/App.test.tsx`, and `frontend/e2e/mock-server.ts` are updated to
show the new pinned flags for realism.

## Non-Goals

- Sweeping `--load-mode` / `--no-mmproj` as variable config knobs (pinned only).
- Passing `--load-mode` into llama-bench.
- Measuring speculative-decoding throughput (unchanged).