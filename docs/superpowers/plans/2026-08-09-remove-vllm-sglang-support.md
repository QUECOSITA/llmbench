# Remove vLLM & sglang Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make llmbench a llama.cpp-only benchmark tool: strip all vLLM and sglang code paths, detection, config generation, benchmarks, install helpers, and UI; uninstall vLLM (and its orphaned torch stack) from `backend/.venv`; keep all on-disk user data (`~/.llmbench/llmbench.db`, `~/.cache/huggingface`) untouched.

**Architecture:** The backend keeps exactly one serving server (`llama.cpp`, binary-detected) plus the speed-bench path for speculative-decoding models. README detection becomes llama.cpp-only; a model whose README proposes only vLLM/sglang is reported as "no supported server" (frontend shows the unsupported notice). `detect_binaries()` returns `{"llama.cpp": bool, "speed-bench": bool}`. The frontend's only server enumeration (`DownloadedSection`) collapses to llama.cpp; e2e mock server is rewritten to serve llama.cpp flows. Legacy vLLM/sglang rows in SQLite and the HF cache are left alone (never wiped/downgraded by the app), and legacy `server_id` values render as raw strings if ever seen.

**Tech Stack:** Python/FastAPI/uvicorn/pytest; Vite/React 18/TypeScript/vitest/@testing-library/react/Playwright. No new dependencies.

**Decisions locked with the user:** (1) uninstall = venv only, leave cache/DB alone; (2) detection = llama.cpp-only; (3) `install.py` + `install-serving-server` skill reduced to llama.cpp; (4) plan built on top of the current working tree (incl. uncommitted in-flight work).

---

## File Structure

**Backend (modify):**
- `backend/app/servers.py` — SERVERS/README_FLAG_MAP/detection/`build_bench_command` → llama.cpp only.
- `backend/app/benchmark.py` — drop `parse_vllm_throughput`/`parse_sglang_bench` + `PARSERS` entries.
- `backend/app/flags.py` — KEY_FLAGS/VALUE_POOLS/DEFAULTS/`build_serving_command` → llama.cpp only.
- `backend/app/fit.py` — `_CTX_FLAGS` + `config_fit` → llama.cpp only.
- `backend/app/readme_parser.py` — detection → llama.cpp only.
- `backend/app/sync.py` — reconcile → llama.cpp only (remove the non-llama.cpp upsert branch).
- `backend/app/db.py` — seed only `llama.cpp` in the `servers` table.
- `backend/app/api.py` — `KNOWN_SERVERS`, `_model_status`, `readme_flags_by_server`, `_download_command`, `_resolve_download_path` → llama.cpp only.
- `backend/app/install.py` — llama.cpp-only install/verify/requirements.
- `backend/app/spawn.py` — drop the vLLM env var (keep `spawn_env()` as a passthrough).

**Backend tests (modify):** `test_servers.py`, `test_benchmark.py`, `test_flags.py`, `test_fit.py`, `test_readme_parser.py`, `test_sync.py`, `test_db.py`, `test_api.py`, `test_install.py`, `test_spawn.py`.

**Frontend (modify):**
- `src/components/DownloadedSection.tsx` — `SERVER_DISPLAY`/`SERVER_ORDER` → llama.cpp only.
- `src/App.tsx` — unsupported-notice copy (singular server).
- Frontend tests: `DownloadedSection.test.tsx`, `App.test.tsx`, `api/client.test.ts`, `ConfigBank.test.tsx`, `ResultsTable.test.tsx`, `ws/*.test.ts` (cosmetic fixture updates).
- `e2e/mock-server.ts` + `e2e/flow.spec.ts` — llama.cpp-only flow.

**Docs (modify):** `README.md`, `PRODUCT.md`. (Historical `docs/superpowers/*` specs/plans are a record — left untouched.)

**Skill (modify):** `.opencode/skills/install-serving-server/SKILL.md` — llama.cpp-only.

**System (uninstall, explicit user approval at execution time):** uninstall vLLM + orphaned torch stack from `backend/.venv`. sglang is not installed (nothing to do). `~/.llmbench` and `~/.cache/huggingface` untouched.

---

## Part A — Backend

### Task 1: servers.py — single-server

**Files:**
- Modify: `backend/app/servers.py`
- Test: `backend/tests/test_servers.py`

- [ ] **Step 1: Update the SERVERS registry, README flag map, and readiness helpers**

In `backend/app/servers.py`:

1. Replace the `SERVERS` dict and `README_FLAG_MAP` with:

```python
SERVERS = {
    "llama.cpp": {
        "display": "llama.cpp",
        "bench_binaries": ["llama-bench"],
        "serving_binaries": ["llama-server"],
    },
}

# README flag name -> canonical flag name per server
README_FLAG_MAP = {
    "llama.cpp": {
        "-c": "--ctx-size", "-n": "--predict", "-t": "--threads", "-b": "--batch-size",
        "-ngl": "--n-gpu-layers", "-m": "-m",
    },
}
```

2. `resolve_bench_binary`: remove the `module` branch — llama.cpp is binary-based:

```python
def resolve_bench_binary(server_id: str, bin_dir: str | None = None) -> str | None:
    """Resolve the executable that runs a server's benchmark. llama.cpp resolves
    the llama-bench binary from bin_dir or PATH."""
    if server_id == "llama.cpp" and bin_dir:
        candidate = Path(bin_dir) / "llama-bench"
        if candidate.is_file():
            return str(candidate)
    for b in SERVERS[server_id]["bench_binaries"]:
        found = shutil.which(b)
        if found:
            return found
    return None
```

3. Remove `_VLLM_BENCH_FLAGS` and its comment block. Remove the `vllm`/`sglang` branches of `model_ref_from_flags` and `build_bench_command` so they keep only the llama.cpp branch followed by `raise ValueError(f"unknown server {server_id}")`.

- [ ] **Step 2: Update the unit tests**

In `backend/tests/test_servers.py`:
- `test_detect_missing`: expectation becomes `{"llama.cpp": False, "speed-bench": False}`.
- `test_readme_flag_map_aliases`: drop the `README_FLAG_MAP["vllm"]` assertion.
- Delete: `test_detect_vllm_requires_module_not_python`, `test_detect_vllm_module_importable_is_ready`, `test_detect_sglang_module_importable_is_ready`, `test_build_bench_command_vllm`, `test_build_bench_command_vllm_bare_bool_flag`, `test_build_bench_command_vllm_filters_server_only_flags`, `test_build_bench_command_sglang_uses_sys_executable`, `test_build_bench_command_sglang_empty_max_running_requests`, `test_parse_serving_command_vllm`, `test_parse_serving_command_sglang`.
- `test_parse_serving_command_empty`: drop the `parse_serving_command("vllm", ...)` line.
- `test_model_ref_from_flags_fallbacks`: drop the `model_ref_from_flags("vllm", ...)` line.
- `test_roundtrip_rebuild_bench_command_matches_generated`: loop `("llama.cpp",)`; `gguf = "x.gguf"`.

- [ ] **Step 3: Run the tests**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_servers.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/servers.py backend/tests/test_servers.py && git commit -m "refactor: make llama.cpp the only serving server"
```

### Task 2: benchmark.py — drop vLLM/sglang parsers

**Files:**
- Modify: `backend/app/benchmark.py`
- Test: `backend/tests/test_benchmark.py`

- [ ] **Step 1: Remove the parsers**

Delete `parse_vllm_throughput`, `parse_sglang_bench`, and change `PARSERS` to:

```python
PARSERS = {
    "llama.cpp": parse_llama_bench_csv,
}
```

- [ ] **Step 2: Update tests**

In `backend/tests/test_benchmark.py`:
- Drop `parse_vllm_throughput, parse_sglang_bench` from the import.
- Delete `VLLM_OUT`, `SGLANG_OUT` and all `test_parse_vllm_throughput*` and `test_parse_sglang_bench` tests.
- `BenchmarkRunner(server_id="vllm", ...)` → `server_id="llama.cpp"`.
- Delete the `VLLM_WSL2_ENABLE_PIN_MEMORY` assertions.

- [ ] **Step 3: Run tests**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_benchmark.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/benchmark.py backend/tests/test_benchmark.py && git commit -m "refactor: remove vllm/sglang benchmark parsers"
```

### Task 3: flags.py — llama.cpp-only config generation

**Files:**
- Modify: `backend/app/flags.py`
- Test: `backend/tests/test_flags.py`

- [ ] **Step 1: Strip vLLM/sglang**

- `KEY_FLAGS`, `VALUE_POOLS`, `DEFAULTS`: remove the `vllm` and `sglang` entries.
- `_gpu_util_for_vram`: delete entirely (was only used by vLLM/sglang).
- `_baseline`: remove the `if server_id == "vllm"` and `if server_id == "sglang"` branches.
- `build_serving_command`: remove the `vllm` and `sglang` branches; keep llama.cpp + `raise ValueError`.

- [ ] **Step 2: Update tests**

- `test_generate_configs_count_and_baseline`: rewrite for `llama.cpp` with `readme_flags={"--ctx-size": "8192"}`; assert on `KEY_FLAGS["llama.cpp"]`.
- `test_build_serving_command_vllm`: delete.
- `test_deterministic`, `test_generate_configs_no_duplicates_high_n`, `test_generate_configs_does_not_overshoot`: use `llama.cpp`.
- `test_bool_flag_on_variant_renders_once`: delete (vLLM-only).
- Keep all llama.cpp tests.

- [ ] **Step 3: Run tests**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_flags.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/flags.py backend/tests/test_flags.py && git commit -m "refactor: llama.cpp-only config generation"
```

### Task 4: fit.py — llama.cpp-only fit

**Files:**
- Modify: `backend/app/fit.py`
- Test: `backend/tests/test_fit.py`

- [ ] **Step 1: Strip vLLM/sglang**

- `_CTX_FLAGS`: remove the `vllm` and `sglang` entries.
- `config_fit`: remove the `elif server_id in ("vllm", "sglang"):` branch and the now-unused `_to_float` helper.

- [ ] **Step 2: Update tests**

Delete: `test_config_fit_vllm_uses_gpu_utilization`, `test_config_fit_sglang_uses_mem_fraction`, `test_config_fit_ctx_flag_scales_kv`, `test_config_fit_defaults_arch_and_ctx`. All llama.cpp fit tests stay.

- [ ] **Step 3: Run tests**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_fit.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/fit.py backend/tests/test_fit.py && git commit -m "refactor: llama.cpp-only hardware fit"
```

### Task 5: readme_parser.py — llama.cpp-only detection

**Files:**
- Modify: `backend/app/readme_parser.py`
- Test: `backend/tests/test_readme_parser.py`

- [ ] **Step 1: Restrict detection**

- `_SERVERS` → `("llama.cpp",)`.
- `_COMMAND_PATTERNS`: remove the `vllm` and `sglang` keys.
- `detect_serving_programs`: `scores = {"llama.cpp": 0}`.

- [ ] **Step 2: Update tests**

- Delete: `test_detect_vllm_by_command`, `test_detect_sglang`, `test_gguf_plus_multi_server_readme_ties_to_none` (rewrite), the vllm/sglang extraction cases (`test_extract_flag_equals_form`, `test_extract_flags_adjacent_bool_flags`, `test_extract_flags_negative_number_value`, and the `vllm` block in `test_extract_flags_does_not_bleed_other_servers_flags`).
- `test_detect_llamacpp_by_gguf`: `scores == {"llama.cpp": 3}`.
- Add: a README that only mentions `vllm serve ...` (no GGUF) scores `{"llama.cpp": 0}` and `top_serving_program(...) is None`.

- [ ] **Step 3: Run tests**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_readme_parser.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/readme_parser.py backend/tests/test_readme_parser.py && git commit -m "refactor: llama.cpp-only README server detection"
```

### Task 6: sync.py — llama.cpp-only reconcile

**Files:**
- Modify: `backend/app/sync.py`
- Test: `backend/tests/test_sync.py`

- [ ] **Step 1: Restrict reconcile**

`reconcile_models`: remove the `else:` non-llama.cpp upsert branch; delete the now-unused `snap_path` line:

```python
    for repo_id, snap in scan_hf_cache(cache_root).items():
        ggufs = _ggufs_in_snapshot(snap)
        detected = detect_server_from_snapshot(snap, has_gguf=bool(ggufs))
        if detected is None:
            continue
        if detected == "llama.cpp" and ggufs:
            g = max(ggufs, key=lambda p: p.stat().st_size)
            db_mod.upsert_model(conn, repo_id, "llama.cpp", "hf", str(g),
                                "downloaded", gguf_filename=g.name, size_bytes=g.stat().st_size)
        _set_downloaded_servers(conn, repo_id, ("llama.cpp",))
```

- [ ] **Step 2: Update tests**

- `test_reconcile_discovers_hf_cache_snapshot`: rewrite as a GGUF snapshot → llama.cpp row downloaded; vllm/sglang not.
- `test_reconcile_only_marks_readme_detected_server`: rewrite for a llama.cpp README.
- `test_reconcile_downgrades_stale_all_server_rows`: seed all three; llama.cpp GGUF repo → llama.cpp downloaded, vllm/sglang missing.
- `test_reconcile_keeps_existing_rows_when_readme_detects_none`: keep (still passes).
- `test_reconcile_keeps_rows_when_no_readme_and_no_gguf`: keep; seed `llama.cpp`.
- `test_reconcile_marks_stale_rows_missing`: keep/seed llama.cpp.
- `test_remove_model_*`: update seeds to `llama.cpp`.
- `test_list_models_status_filter`: assert on llama.cpp.

- [ ] **Step 3: Run tests**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_sync.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/sync.py backend/tests/test_sync.py && git commit -m "refactor: llama.cpp-only model reconcile"
```

### Task 7: db.py — seed llama.cpp only

**Files:**
- Modify: `backend/app/db.py`
- Test: `backend/tests/test_db.py`

- [ ] **Step 1: Update the seed**

```python
    conn.executescript(
        "INSERT OR IGNORE INTO servers(id, display_name) VALUES "
        "('llama.cpp','llama.cpp');"
    )
```

- [ ] **Step 2: Update tests**

Change `server_id="vllm"` fixtures and vllm serving/bench strings to llama.cpp equivalents.

- [ ] **Step 3: Run tests**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_db.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/db.py backend/tests/test_db.py && git commit -m "refactor: seed llama.cpp as the only serving server"
```

### Task 8: api.py — single-server API

**Files:**
- Modify: `backend/app/api.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Restrict the API**

- `KNOWN_SERVERS = ("llama.cpp",)`.
- `_download_command`: make the include unconditional:

```python
def _download_command(repo_id: str, server_id: str, gguf_filename: str | None = None,
                      cache_dir: str | None = None) -> list[str]:
    cmd = ["hf", "download", "--format", "human", repo_id]
    cmd += ["--include", gguf_filename or "*.gguf", "--include", "README.md"]
    if cache_dir:
        cmd += ["--cache-dir", cache_dir]
    return cmd
```

- `analyze`: `readme_flags_by_server = {"llama.cpp": extract_flags(readme, ["llama.cpp"])}`.
- `_model_status`: iterate `("llama.cpp",)`.
- `_resolve_download_path`: remove the trailing unconditional snapshot block; keep only the llama.cpp branch.

- [ ] **Step 2: Update tests**

Surgery across `test_api.py` (~40 call sites): readiness set == `{"llama.cpp", "speed-bench"}`; analyze detection → llama.cpp; `readme_flags_by_server` → llama.cpp key only; `/configs/generate` server_id → llama.cpp (drop `vllm.entrypoints.cli.main` assertions); `/models/download` server_id → llama.cpp; `test_download_vllm_success_upserts_downloaded` → llama.cpp; `_download_command` asserts llama.cpp include list; reconcile-through-API → GGUF/llama.cpp.

- [ ] **Step 3: Run the API tests**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_api.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/api.py backend/tests/test_api.py && git commit -m "refactor: single-server download/generate API"
```

### Task 9: install.py + spawn.py — llama.cpp only

**Files:**
- Modify: `backend/app/install.py`, `backend/app/spawn.py`
- Test: `backend/tests/test_install.py`, `backend/tests/test_spawn.py`

- [ ] **Step 1: install.py**

- `_USAGE` → `"usage: python -m app.install llama.cpp"`.
- `requirements_for`: remove the `if server_id in ("vllm", "sglang"):` branch; keep the `elif server_id == "llama.cpp":` branch.
- `install_commands`: remove the `vllm` and `sglang` branches; keep llama.cpp.

- [ ] **Step 2: spawn.py**

```python
import os


def spawn_env() -> dict[str, str]:
    """Environment for spawned server/bench subprocesses."""
    return dict(os.environ)
```

- [ ] **Step 3: Update tests**

- `test_install.py`: delete vllm/sglang tests; rewrite system/requirement/main tests against `llama.cpp`; keep llama.cpp tests + unknown-server tests.
- `test_spawn.py`: assert `spawn_env()` returns a copy of `os.environ` and does NOT contain `VLLM_WSL2_ENABLE_PIN_MEMORY`.

- [ ] **Step 4: Run tests**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_install.py tests/test_spawn.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/install.py backend/app/spawn.py backend/tests/test_install.py backend/tests/test_spawn.py && git commit -m "refactor: llama.cpp-only install helper and drop vLLM spawn env"
```

---

## Part B — Frontend

### Task 10: DownloadedSection + App copy

**Files:**
- Modify: `frontend/src/components/DownloadedSection.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/components/DownloadedSection.test.tsx`, `frontend/src/App.test.tsx`

- [ ] **Step 1: Collapse the server map**

In `DownloadedSection.tsx`:

```ts
const SERVER_DISPLAY: Record<string, string> = {
  "llama.cpp": "llama.cpp",
};

const SERVER_ORDER = ["llama.cpp"];
```

In `App.tsx`, update the unsupported notice to singular: `model not supported by llama.cpp`.

- [ ] **Step 2: Update unit tests**

- `DownloadedSection.test.tsx`: `getByText("llama.cpp")` instead of the 3-server join / `vLLM`; seed llama.cpp.
- `App.test.tsx`: `detected_server`/`server_id` mocks → `llama.cpp`; `downloaded` maps → `{ "llama.cpp": false }`; `findByText("vLLM")` → `findByText("llama.cpp")`; `getByText("vllm:")` → `"llama.cpp:"`.

- [ ] **Step 3: Run typecheck + unit suite**

Run: `cd frontend && npx tsc -b && npx vitest run src/components/DownloadedSection.test.tsx src/App.test.tsx`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/ruben/test/llmbench && git add frontend/src/components/DownloadedSection.tsx frontend/src/App.tsx frontend/src/components/DownloadedSection.test.tsx frontend/src/App.test.tsx && git commit -m "refactor: llama.cpp-only UI server labels and copy"
```

### Task 11: remaining frontend fixtures

**Files:**
- Modify: `frontend/src/api/client.test.ts`, `frontend/src/components/ConfigBank.test.tsx`, `frontend/src/components/ResultsTable.test.tsx`, `frontend/src/ws/downloadReducer.test.ts`, `frontend/src/ws/useBenchmarkProgress.test.ts`, `frontend/src/ws/useDownloadProgress.test.ts`

- [ ] **Step 1: Cosmetic fixture updates**

- `client.test.ts`: `readiness` → `{ "llama.cpp": true }`.
- `ConfigBank.test.tsx`: `"vllm serve ..."` → `"llama-server ..."`.
- `ResultsTable.test.tsx`: `server_id: "vllm"` → `"llama.cpp"`.
- `ws/*.test.ts`: opaque `"vllm"` ids → `"llama.cpp"`.

- [ ] **Step 2: Run the full unit suite**

Run: `cd frontend && npx tsc -b && npx vitest run`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
cd /home/ruben/test/llmbench && git add frontend/src/api/client.test.ts frontend/src/components/ConfigBank.test.tsx frontend/src/components/ResultsTable.test.tsx frontend/src/ws/ && git commit -m "test: use llama.cpp fixtures across frontend unit tests"
```

### Task 12: e2e mock-server + flow

**Files:**
- Modify: `frontend/e2e/mock-server.ts`
- Modify: `frontend/e2e/flow.spec.ts`

- [ ] **Step 1: Rewrite the mock server to llama.cpp**

- `seedModel("llama.cpp", "org/model", "model.gguf")`.
- `readiness: { "llama.cpp": true, "speed-bench": true }`.
- `detected_server: "llama.cpp"`.
- `readme_flags: { "--ctx-size": "8192" }`.
- `downloaded: { "llama.cpp": false }`.
- `flags: { "--ctx-size": "8192" }`.
- `serving_command: "llama-server --hf-repo org/model --hf-file model.gguf --ctx-size 8192"`.
- `bench_tool: "llama-bench"`.
- results: `server_id: "llama.cpp"`, `flag_conf: { "--ctx-size": "8192" }`, same serving_command.

- [ ] **Step 2: Update the flow spec**

- `/server vLLM/i` → `/server llama.cpp/i` (3x).
- `/vllm serve org\/model/i` → `/llama-server/i`.
- `getByText("vLLM")` → `getByText("llama.cpp")` (2x).

- [ ] **Step 3: Run e2e**

Stop dev servers: `./down.sh`. Run: `cd frontend && npx playwright test`. Expected: PASS (4 tests).

- [ ] **Step 4: Commit**

```bash
cd /home/ruben/test/llmbench && git add frontend/e2e/mock-server.ts frontend/e2e/flow.spec.ts && git commit -m "test: e2e flows through llama.cpp"
```

---

## Part C — Docs & Skill

### Task 13: README + PRODUCT

- [ ] **Step 1: Update `README.md`**

Line 5 → llama.cpp only. Line 12 → "Model download button". Line 21 → llama.cpp binaries only. Keep speed-bench requirement.

- [ ] **Step 2: Update `PRODUCT.md`**

Lines 15, 24, 26, 41: remove vLLM/sglang.

- [ ] **Step 3: Commit**

```bash
cd /home/ruben/test/llmbench && git add README.md PRODUCT.md && git commit -m "docs: llama.cpp-only scope in README and product doc"
```

### Task 14: install-serving-server skill

**Files:**
- Modify: `.opencode/skills/install-serving-server/SKILL.md`

- [ ] **Step 1: Reduce the skill to llama.cpp**

Rewrite: readiness = `llama-bench`/`llama-server` resolvable; detection via `python -m app.install llama.cpp`; install = CUDA build from source in `$HOME/llama.cpp`; ctx7 scoped to llama.cpp. Remove all vLLM/sglang references.

- [ ] **Step 2: Commit**

```bash
cd /home/ruben/test/llmbench && git add .opencode/skills/install-serving-server/SKILL.md && git commit -m "docs: llama.cpp-only install-serving-server skill"
```

---

## Part D — Uninstall (system change, user-run)

### Task 15: Uninstall vLLM from the backend venv (USER RUNS THIS)

**Safety note:** mutates `backend/.venv` only; never touches `~/.llmbench/llmbench.db` or `~/.cache/huggingface`. Run after the code changes land:

```bash
cd /home/ruben/test/llmbench/backend
source .venv/bin/activate
pip check
pip list | grep -iE "vllm|torch|triton|flashinfer|transformers"
pip uninstall -y vllm
# verify each is orphaned (pip show <pkg> → "Required-by:" empty or only vllm):
pip uninstall -y torch torchvision torchaudio torchcodec torchgen torch_c_dlpack_ext triton
pip check
python -m pytest -q
python -c "import vllm"            # expect ModuleNotFoundError
python -m app.install llama.cpp    # llama.cpp readiness still works
```

---

## Final Verification (full local CI suite)

- [ ] **Backend:** `cd backend && source .venv/bin/activate && python -m pytest -q` — PASS.
- [ ] **Frontend:** `cd frontend && npx tsc -b && npx vitest run` — PASS.
- [ ] **E2E:** `./down.sh`, `cd frontend && npx playwright test`, then `./up.sh` — PASS (4 tests).
- [ ] **Readiness sanity:** `curl -s localhost:8000/api/servers` → `readiness` has only `llama.cpp` + `speed-bench`.
- [ ] **Data safety check:** `sqlite3 ~/.llmbench/llmbench.db "SELECT server_id, status, count(*) FROM models GROUP BY server_id, status"` — vllm/sglang rows unchanged; `r0b0tlab/FastContext-1.0-4B-RL-NVFP4` vllm row still `downloaded`.
- [ ] **Push / PR** to `QUECOSITA/llmbench` to run CI.
