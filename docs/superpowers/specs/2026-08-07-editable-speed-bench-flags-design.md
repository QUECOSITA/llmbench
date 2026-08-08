# Editable Speed-Bench Flags Design

**Date:** 2026-08-07
**Status:** Approved

## Goal

Let the user edit the speed-bench client flags (`--bench throughput_1k --category all --limit 1 --osl 128`) in the config bank for speed-bench configs, and add any extra speed-bench flags. At run start the flags are validated: every flag must exist in the speed-bench CLI options, and `--bench`/`--category` values must exist in the SPEED-Bench dataset variants; otherwise the run is rejected with a clear 422.

## Approach

**Approach A (approved):** Free-text flags per config + static allowlist validation at run start.

- For each speed-bench config row, a second editable textarea holds the flags string (default `--bench throughput_1k --category all --limit 1 --osl 128`), round-tripped through the frontend like `serving_command`.
- At run start, `_rebuild_bench_command` parses the flags (`shlex`), validates them against a static allowlist (flag names + per-bench categories), and on failure sets `bench_error` so `start_run` raises a clear 422.
- `--url` and `--output` are managed by the app: rejected in the editable string, and injected at execution time by the existing `SpeedBenchRunner`.

Rejected alternatives:
- **B — validate at generate time only:** the user edits flags after generate, so run-start validation is required anyway.
- **C — global run-level flags:** loses per-config flexibility and diverges from `serving_command`.

## Data model & round-trip

New per-config field `bench_flags: str` (the user-editable speed-bench client flags). Flows like `serving_command`:

- **Generate** (`POST /configs/generate`): for `bench_tool === "speed-bench"` configs the backend sets `cfg["bench_flags"] = "--bench throughput_1k --category all --limit 1 --osl 128"` and builds `cfg["bench_command"]` from it. Absent for llama-bench/vllm/sglang configs.
- **Frontend**: `bench_flags` is stored per `ConfigRow`, shown/edited in the bank, and sent back in the `/api/benchmarks` payload (`configs[].bench_flags`).
- **Run start** (`_rebuild_bench_command`): for `bench_tool === "speed-bench"`, parse `bench_flags`, validate, and rebuild `bench_command = [sys.executable, script] + <validated flags> + ["--url", "localhost:8080", "--output", "<data_dir>/speed-bench.json"]`. The existing runner still substitutes the real free port + temp output at execution time.

## Backend validation (static allowlist)

New helpers in `backend/app/servers.py`:

- `SPEED_BENCH_CLI_FLAGS` — the 10 CLI options: `--url --model --bench --category --osl --extra-inputs --concurrency --limit --timeout --output`.
- `SPEED_BENCH_BENCHES` — `qualitative, throughput_1k, throughput_2k, throughput_8k, throughput_16k, throughput_32k`.
- `SPEED_BENCH_CATEGORIES` — dict: each throughput bench → `{high_entropy, mixed, low_entropy}`; `qualitative` → `{coding, humanities, math, qa, rag, reasoning, stem, writing, multilingual, summarization, roleplay}`. `all` always allowed.
- `parse_speed_bench_flags(text) -> list[str]` — `shlex.split`, dropping a leading bare token (so pasting the whole command works).
- `validate_speed_bench_flags(flags) -> str | None` — returns an error message or `None`:
  - unknown flag name → error with the allowed list;
  - `--bench` value not in benches → error;
  - `--category` value neither `all` nor in the selected bench's categories → error;
  - `--url`/`--output` present → error ("managed by the app");
  - bare non-flag token after the first → error.

Validation runs inside `_rebuild_bench_command`; a failing validation sets `cfg["bench_error"]`, and `start_run` already raises 422 with that message. The llama-bench/vllm/sglang paths are untouched. The speed-bench client re-validates at runtime as a safety net.

## Frontend UI

- `frontend/src/api/client.ts`: add `bench_flags?: string` to the `generateConfigs` config item type.
- `frontend/src/components/ConfigBank.tsx`: for rows with `bench_tool === "speed-bench"`, render a second textarea under the existing `serving_command` one, bound to `cfg.bench_flags`, with a small label (`SPEED-BENCH FLAGS`). New prop `onEditFlags?: (index: number, flags: string) => void`.
- `frontend/src/App.tsx`: `onEditFlags` updates `configs[i].bench_flags`; `onRun` includes `bench_flags` in each mapped config; `setConfigs(data.configs)` already carries the field through from generate.

## Error handling

Single rejection surface: the run's 422 from `start_run`, with messages like:

- `unknown speed-bench flag '--foo'; allowed: --url --model --bench --category --osl --extra-inputs --concurrency --limit --timeout --output`
- `unknown --bench 'foo'; available benches: qualitative, throughput_1k, throughput_2k, throughput_8k, throughput_16k, throughput_32k`
- `unknown --category 'coding' for bench 'throughput_1k'; available: all, high_entropy, mixed, low_entropy`
- `--url/--output are managed by the app; remove them from the speed-bench flags`

## Testing

- Backend `test_servers.py`: `parse_speed_bench_flags` (defaults, extra flags, leading program token, `--flag=value` form), `validate_speed_bench_flags` (valid passes, unknown flag, bad bench, per-bench bad category, reserved `--url`/`--output`).
- Backend `test_api.py`: generate sets the default `bench_flags`; rebuild with edited flags produces the right command; rebuild with invalid flags sets `bench_error` → 422 via `start_run`.
- Frontend: ConfigBank renders + edits the flags textarea; App round-trips `bench_flags` in the run payload.
- Full suite: `pytest`, `tsc -b`, `vitest run`, `playwright test`.
