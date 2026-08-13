# llama.cpp Startup Gate in `up.sh` — Design

**Date:** 2026-08-13
**Status:** Approved by user (via plan approval)

## Problem

`up.sh` only points llama-bench discovery at `$HOME/llama.cpp/build/bin` when that
directory happens to exist. If llama.cpp is absent (e.g. never installed, installed
elsewhere, or not on PATH), `up.sh` silently continues, the backend starts, and
benchmarks are never triggered — no explanation, no remediation.

## Goal

Before starting anything, `up.sh` must truthfully resolve llama.cpp
(`llama-bench` + `llama-server`) from:

1. an explicit `LLMBENCH_LLAMA_CPP_BIN_DIR` override, or
2. PATH, or
3. the standard install locations for the actual OS.

If it cannot be found, run an interactive, **cancellable** flow that lets the user
either point at an existing custom install (verified) or trigger a fresh source
build (with requirements handled). Cancelling at **any** prompt aborts `up.sh`.

## Decisions (confirmed with user)

- **Code location:** new sourced script `scripts/ensure-llama-cpp.sh`, sourced from
  `up.sh`. Sourcing (not executing) is required so the `export
  LLMBENCH_LLAMA_CPP_BIN_DIR` propagates into the processes `up.sh` spawns.
- **Cancel behavior:** abort `up.sh` with a clear message (`exit 1`); nothing starts.
- **Requirements:** verify `git`, `cmake`, C/C++ compiler, `make`, `python3`; report
  missing ones; then **offer** `sudo apt-get update && sudo apt-get install -y ...`
  with explicit confirmation. CUDA toolkit is reported/noted, never auto-installed.
- **Build type:** auto-detect via `nvidia-smi` → CUDA build (`-DGGML_CUDA=ON`) when a
  GPU + driver are present, otherwise CPU-only. The choice is printed in the plan.
- **Non-interactive safety:** if stdin/stdout are not a TTY, the script cannot prompt;
  it aborts with an explanatory message instead of hanging or guessing.

## Standard install locations per OS

| OS       | Candidate bin dirs                                         |
|----------|------------------------------------------------------------|
| Linux    | `/usr/local/bin`, `/usr/bin`, `/opt/llama.cpp/build/bin`, `$HOME/llama.cpp/build/bin` |
| macOS    | `$(brew --prefix)/bin`, `/opt/homebrew/bin`, `/usr/local/bin`, `$HOME/llama.cpp/build/bin` |
| Other    | `/usr/local/bin`, `/usr/bin`, `$HOME/llama.cpp/build/bin`  |

A dir "contains llama.cpp" iff both `llama-bench` and `llama-server` exist **and are
executable** there. If both resolve via `command -v` (PATH), no env var is exported —
the backend already falls back to PATH (`app/servers.py:resolve_bench_binary`).

## Install procedure (verified against llama.cpp docs via ctx7, 2026-08-13)

```bash
git clone --depth 1 https://github.com/ggml-org/llama.cpp "$HOME/llama.cpp"   # if absent
git -C "$HOME/llama.cpp" pull --ff-only                                        # if existing git checkout
cmake -B "$HOME/llama.cpp/build" -S "$HOME/llama.cpp"                          # CPU
cmake -B "$HOME/llama.cpp/build" -S "$HOME/llama.cpp" -DGGML_CUDA=ON          # CUDA
cmake --build "$HOME/llama.cpp/build" --config Release -j"$(nproc)"
```

Binaries are emitted to `${CMAKE_BINARY_DIR}/bin` → `$HOME/llama.cpp/build/bin`
(confirmed in `CMakeLists.txt` via ctx7). These match `backend/app/install.py:
install_commands()`; no backend change needed.

## New file: `scripts/ensure-llama-cpp.sh` — flow

1. **TTY guard** — if not a TTY, print "llama.cpp not found and up.sh is not
   interactive" and `_abort`.
2. **Explicit override** — if `LLMBENCH_LLAMA_CPP_BIN_DIR` is set and valid, use it;
   if set but invalid, warn and continue detection.
3. **PATH** — if both binaries resolve via `command -v`, done.
4. **Standard dirs** — scan per-OS list; first valid dir wins → export + return.
5. **Interactive menu** (cancellable; `q`/`c`/`cancel`/empty abort):
   - **(1) Already installed elsewhere** → prompt for dir path (leading `~` expanded)
     → verify → export + return; invalid → inform + offer retry / install / cancel.
   - **(2) Install now** → system check → optional `sudo apt-get` install of missing
     build deps (confirmed) → GPU/build-type detection → print install plan → require
     `y` → run steps (each step retryable/cancellable) → verify `build/bin` → export +
     return.
   - **(q) Cancel** → `_abort`.

`_abort` prints `llama.cpp (llama-bench + llama-server) is required for benchmarks.
Startup aborted.` and `exit 1`.

## Backend consistency

No backend source changes. `app/config.py` reads `LLMBENCH_LLAMA_CPP_BIN_DIR`;
`app/servers.py` falls back to PATH; `app/install.py` probe (`python -m app.install
llama.cpp`) will reflect the resolution after `up.sh` runs. The backend's own
detection remains the single source of truth at runtime.

## Testing

- `bash -n` syntax check on `up.sh` and `scripts/ensure-llama-cpp.sh`.
- Manual branch tests with simulated prompts (canned `read` input):
  - override valid / override invalid → falls through
  - PATH present → continues, no export
  - standard dir present → exports that dir
  - custom location valid / invalid → inform → install → cancel
  - install full happy path (cloned temp copy, CPU build) → exports `build/bin`
  - cancel at every prompt → exits 1, nothing starts
- Full local suite (unchanged app code must stay green): backend `pytest`,
  frontend `tsc -b` + `vitest run`, Playwright `e2e`.

## File structure

- **Create:** `scripts/ensure-llama-cpp.sh` — detection + interactive install flow.
- **Modify:** `up.sh` — replace lines 2–5 with `source` of the new script.
- **Docs:** `docs/superpowers/specs/2026-08-13-llama-cpp-startup-gate-design.md`,
  `docs/superpowers/plans/2026-08-13-llama-cpp-startup-gate.md`.
