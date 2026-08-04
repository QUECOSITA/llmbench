# llama.cpp Bench Adaptation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the llama.cpp RUN BENCHMARK path work against the locally-installed `llama-bench` (v9992) so a real benchmark completes and produces ranked results.

**Architecture:** Add a configurable llama.cpp binary dir (`Settings.llama_cpp_bin_dir`) that drives a new `resolve_bench_binary` used by readiness detection and the actual command. Regenerate the llama.cpp bench command for the v9992 CLI (`--fit-ctx`, token-count `-p`/`-n`, local GGUF `-m`), make the CSV parser accept the new schema while keeping the legacy one, resolve the local GGUF path backend-side in `/configs/generate`, and log run failures instead of swallowing them.

**Tech Stack:** Python FastAPI backend, pydantic-settings, stdlib `sqlite3`/`asyncio`/`csv`, llama-bench v9992 CLI. TDD via `pytest`.

---

### Task 1: Add `llama_cpp_bin_dir` setting

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_config.py`:

```python
def test_llama_cpp_bin_dir_default_none():
    s = Settings()
    assert s.llama_cpp_bin_dir is None


def test_llama_cpp_bin_dir_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMBENCH_LLAMA_CPP_BIN_DIR", str(tmp_path))
    s = Settings()
    assert s.llama_cpp_bin_dir == tmp_path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_config.py -q`
Expected: FAIL — `Settings` has no attribute `llama_cpp_bin_dir`.

- [ ] **Step 3: Add the field to Settings**

In `backend/app/config.py`, add to the `Settings` class (after `workload_file`):

```python
    llama_cpp_bin_dir: Path | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_config.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat: add llama_cpp_bin_dir setting for llama-bench discovery"
```

---

### Task 2: Binary resolution + new llama.cpp bench command

**Files:**
- Modify: `backend/app/servers.py`
- Test: `backend/tests/test_servers.py`

- [ ] **Step 1: Write the failing tests**

Replace the llama-specific assertions in `backend/tests/test_servers.py`. First update the import line:

```python
from app.servers import SERVERS, detect_binaries, build_bench_command, resolve_bench_binary, README_FLAG_MAP
```

Then replace `test_build_bench_command_llama` and `test_build_bench_command_llama_bare_bool_flag`, and add new tests:

```python
def test_resolve_bench_binary_uses_bin_dir(tmp_path):
    fake = tmp_path / "llama-bench"
    fake.write_text("#!/bin/sh\n")
    assert resolve_bench_binary("llama.cpp", bin_dir=str(tmp_path)) == str(fake)


def test_resolve_bench_binary_falls_back_to_path(monkeypatch):
    monkeypatch.setattr("app.servers.shutil.which",
                        lambda name: "/usr/bin/llama-bench" if name == "llama-bench" else None)
    assert resolve_bench_binary("llama.cpp") == "/usr/bin/llama-bench"
    assert resolve_bench_binary("llama.cpp", bin_dir="/nonexistent") == "/usr/bin/llama-bench"


def test_build_bench_command_llama(tmp_path):
    workload = tmp_path / "p.jsonl"
    workload.write_text('{"prompt": "hello world"}\n')
    cmd = build_bench_command("llama.cpp", model_ref="/models/x.gguf",
                              flags={"--ctx-size": "4096", "--n-gpu-layers": "999", "-hf": "org/model"},
                              workload=str(workload), timeout_s=60)
    assert cmd[0] == "llama-bench"
    assert cmd[cmd.index("-m") + 1] == "/models/x.gguf"
    assert cmd[cmd.index("--fit-ctx") + 1] == "4096"
    assert "-c" not in cmd
    assert "-hf" not in cmd
    assert cmd[cmd.index("-p") + 1] == "6"
    assert cmd[cmd.index("-n") + 1] == "128"
    assert cmd[-4:] == ["-r", "2", "-o", "csv"]


def test_build_bench_command_llama_resolved_binary(tmp_path):
    (tmp_path / "llama-bench").write_text("#!/bin/sh\n")
    cmd = build_bench_command("llama.cpp", "/models/x.gguf", {"--ctx-size": "2048"},
                              workload="/nonexistent/prompts.jsonl", timeout_s=60, bin_dir=str(tmp_path))
    assert cmd[0] == str(tmp_path / "llama-bench")
    assert cmd[cmd.index("--fit-ctx") + 1] == "2048"
    assert cmd[cmd.index("-p") + 1] == "512"


def test_build_bench_command_llama_bare_bool_flag(tmp_path):
    cmd = build_bench_command("llama.cpp", "/models/x.gguf", {"--enforce-eager": ""},
                              workload="/nonexistent/prompts.jsonl", timeout_s=60)
    idx = cmd.index("--enforce-eager")
    assert idx != -1
    assert idx == len(cmd) - 1 or cmd[idx + 1] != "--enforce-eager"
    assert cmd[cmd.index("-p") + 1] == "512"
    assert cmd[-4:] == ["-r", "2", "-o", "csv"]
```

Note: `{"prompt": "hello world"}` is 24 chars → `24 // 4 == 6`; a missing workload file falls back to `-p 512`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_servers.py -q`
Expected: FAIL — `resolve_bench_binary` undefined, and llama command still uses `-c`/`-p <file>`.

- [ ] **Step 3: Implement binary resolution and new llama.cpp command**

In `backend/app/servers.py`, add `from pathlib import Path` at the top, then replace `detect_binaries` and the llama.cpp branch of `build_bench_command`:

```python
def resolve_bench_binary(server_id: str, bin_dir: str | None = None) -> str | None:
    meta = SERVERS[server_id]
    if server_id == "llama.cpp" and bin_dir:
        candidate = Path(bin_dir) / "llama-bench"
        if candidate.is_file():
            return str(candidate)
    for b in meta["bench_binaries"]:
        found = shutil.which(b)
        if found:
            return found
    return None


def detect_binaries(bin_dir: str | None = None) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for server_id in SERVERS:
        out[server_id] = resolve_bench_binary(server_id, bin_dir) is not None
    return out


_LLAMA_HF_FLAGS = {"-hf", "-hfr", "--hf-repo", "-hff", "--hf-file", "-hft", "--hf-token"}


def _llama_token_counts(workload: str) -> tuple[int, int]:
    prompt = 512
    try:
        with open(workload, "r", encoding="utf-8") as fh:
            lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    except OSError:
        lines = []
    if lines:
        prompt = max(1, sum(len(ln) for ln in lines) // 4)
    return prompt, 128
```

Then update the llama.cpp branch of `build_bench_command` (keep the vllm and sglang branches unchanged) and add the `bin_dir` parameter to the signature:

```python
def build_bench_command(server_id: str, model_ref: str, flags: dict[str, str],
                        workload: str, timeout_s: int, bin_dir: str | None = None) -> list[str]:
    flags = _canonical_flags(server_id, flags)
    if server_id == "llama.cpp":
        cmd = [resolve_bench_binary("llama.cpp", bin_dir) or "llama-bench", "-m", model_ref]
        mapped = {"--ctx-size": "--fit-ctx", "--n-gpu-layers": "-ngl", "--batch-size": "-b", "--threads": "-t"}
        for flag, value in flags.items():
            if flag in _LLAMA_HF_FLAGS:
                continue
            bench_flag = mapped.get(flag, flag)
            if value:
                cmd += [bench_flag, value]
            elif flag.startswith("--"):
                cmd += [bench_flag]
        prompt, gen = _llama_token_counts(workload)
        cmd += ["-p", str(prompt), "-n", str(gen), "-r", "2", "-o", "csv"]
        return cmd
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_servers.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/servers.py backend/tests/test_servers.py
git commit -m "feat: resolve llama-bench via configurable bin dir and emit v9992 CLI"
```

---

### Task 3: Parse the v9992 CSV schema

**Files:**
- Modify: `backend/app/benchmark.py`
- Test: `backend/tests/test_benchmark.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_benchmark.py`:

```python
LLAMA_CSV_V9992 = """\
build_commit,build_number,cpu_info,gpu_info,backends,model_filename,model_type,model_size,model_n_params,n_batch,n_ubatch,n_threads,cpu_mask,cpu_strict,poll,type_k,type_v,n_gpu_layers,n_cpu_moe,split_mode,main_gpu,no_kv_offload,flash_attn,devices,tensor_split,tensor_buft_overrides,use_mmap,use_direct_io,embeddings,no_op_offload,no_host,fit_target,fit_min_ctx,n_prompt,n_gen,n_depth,test_time,avg_ns,stddev_ns,avg_ts,stddev_ts
"6eddde06a","9992","cpu","gpu","CUDA","x.gguf","q4","216","354","512","512","16","0x0","0","50","f16","f16","999","0","layer","0","0","-1","auto","0","none","1","0","0","0","0","0","0","64","0","0","2026-08-04T00:00:00Z","7374707","0","8678.31","0"
"6eddde06a","9992","cpu","gpu","CUDA","x.gguf","q4","216","354","512","512","16","0x0","0","50","f16","f16","999","0","layer","0","0","-1","auto","0","none","1","0","0","0","0","0","0","0","32","0","2026-08-04T00:00:00Z","33876041","0","944.62","0"
"""


def test_parse_llama_bench_csv_v9992():
    r = parse_llama_bench_csv(LLAMA_CSV_V9992)
    assert r["prompt_processing_tps"] == 8678.31
    assert r["decode_tps"] == 944.62
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_benchmark.py::test_parse_llama_bench_csv_v9992 -q`
Expected: FAIL — both values are `None` (no `test`/`t/s` columns).

- [ ] **Step 3: Make the parser version-tolerant**

Replace `parse_llama_bench_csv` in `backend/app/benchmark.py`:

```python
def parse_llama_bench_csv(text: str) -> dict:
    rows = list(csv.DictReader(io.StringIO(text)))

    if rows and "avg_ts" in rows[0]:
        pp = None
        tg = None
        for r in rows:
            try:
                n_prompt = int(r.get("n_prompt") or 0)
            except (TypeError, ValueError):
                n_prompt = 0
            try:
                n_gen = int(r.get("n_gen") or 0)
            except (TypeError, ValueError):
                n_gen = 0
            try:
                ts = float(r["avg_ts"])
            except (TypeError, ValueError):
                ts = None
            if n_prompt > 0 and n_gen == 0:
                pp = ts
            elif n_gen > 0:
                tg = ts
        return {"prompt_processing_tps": pp, "decode_tps": tg}

    def tps(row):
        try:
            return float(row.get("t/s"))
        except (TypeError, ValueError):
            return None

    pp = next((tps(r) for r in rows if r.get("test") == "pp"), None)
    tg = next((tps(r) for r in rows if r.get("test") == "tg"), None)
    return {"prompt_processing_tps": pp, "decode_tps": tg}
```

- [ ] **Step 4: Run the full benchmark test module**

Run: `cd backend && .venv/bin/python -m pytest tests/test_benchmark.py -q`
Expected: PASS (11 passed) — legacy fixture, schema-drift, runner, timeout, abort, parser-error all still green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmark.py backend/tests/test_benchmark.py
git commit -m "feat: parse llama-bench v9992 CSV schema alongside legacy format"
```

---

### Task 4: Wire bin dir + local GGUF resolution + failure logging in the API

**Files:**
- Modify: `backend/app/api.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api.py`:

```python
def _make_snapshot_gguf(settings, repo_id: str) -> str:
    root = settings.hf_cache_dir
    snap = root / f"models--{repo_id.replace('/', '--')}" / "snapshots" / "ref1"
    snap.mkdir(parents=True)
    gguf = snap / "model.Q4_K_M.gguf"
    gguf.write_bytes(b"dummy-gguf")
    return str(gguf)


def test_generate_configs_llama_resolves_local_gguf(client):
    from app.api import state
    gguf_path = _make_snapshot_gguf(state.settings, "org/model")
    r = client.post("/api/configs/generate", json={
        "repo_id": "org/model", "server_id": "llama.cpp", "n": 2,
        "readme_flags": {"--ctx-size": "4096"},
    })
    assert r.status_code == 200
    for cfg in r.json()["configs"]:
        assert cfg["bench_command"][cfg["bench_command"].index("-m") + 1] == gguf_path
        assert gguf_path in cfg["serving_command"]


def test_generate_configs_llama_falls_back_to_repo_id_when_no_gguf(client):
    r = client.post("/api/configs/generate", json={
        "repo_id": "org/model", "server_id": "llama.cpp", "n": 1,
        "readme_flags": {"--ctx-size": "4096"},
    })
    assert r.status_code == 200
    cfg = r.json()["configs"][0]
    assert cfg["bench_command"][cfg["bench_command"].index("-m") + 1] == "org/model"
    assert "--fit-ctx" in cfg["bench_command"]
```

The `client` fixture in `test_api.py` already sets `hf_cache_dir=tmp_path / "hf"` and `gguf_dir=tmp_path / "gguf"`, and `create_app` assigns the module-level `app.api.state`, so `state.settings` matches the fixture's `Settings`. The backend's `_resolve_download_path` finds the snapshot GGUF at the path above (the empty `gguf_dir` is checked first and skipped).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py::test_generate_configs_llama_resolves_local_gguf tests/test_api.py::test_generate_configs_llama_falls_back_to_repo_id_when_no_gguf -q`
Expected: FAIL — the bench `-m` is `org/model` (repo_id), not the snapshot path.

- [ ] **Step 3: Implement the generate + servers + logging changes**

In `backend/app/api.py`:

1. Add `import logging` to the imports and a module logger after `router = APIRouter(prefix="/api")`:

```python
logger = logging.getLogger(__name__)
```

2. Update the `/servers` endpoint (line ~147) to pass the bin dir:

```python
@router.get("/servers")
async def servers():
    s = _require_state()
    bin_dir = str(s.settings.llama_cpp_bin_dir) if s.settings.llama_cpp_bin_dir else None
    return {"readiness": detect_binaries(bin_dir), "hardware": detect_hardware()}
```

3. In the `generate` endpoint, replace the block starting at `weights = payload.get("weights_bytes")`:

```python
    weights = payload.get("weights_bytes")
    resolved_gguf = payload.get("gguf_path")
    if resolved_gguf is None and server_id == "llama.cpp":
        local_path, _name, _size = _resolve_download_path(s, repo_id, "llama.cpp", None)
        resolved_gguf = local_path
    bin_dir = str(s.settings.llama_cpp_bin_dir) if s.settings.llama_cpp_bin_dir else None
    for cfg in configs:
        cfg["serving_command"] = build_serving_command(
            server_id, repo_id, cfg["flags"],
            gguf_path=resolved_gguf,
        )
        model_ref = resolved_gguf or repo_id
        cfg["bench_command"] = build_bench_command(
            server_id, model_ref, cfg["flags"],
            workload=str(s.settings.workload_file),
            timeout_s=s.settings.benchmark_timeout_s,
            bin_dir=bin_dir,
        )
        if weights is None:
            cfg["fit"] = None
        else:
            cfg["fit"] = config_fit(
                server_id, cfg["flags"], float(weights), vram_gb,
                float(payload.get("ram_gb", 0.0)), payload.get("model_arch"),
            )
    return {"configs": configs}
```

4. In `_run_job`, add logging to the `except Exception` block:

```python
            except Exception:
                logger.exception("run %s failed", run_id)
                db_mod.set_run_status(s.conn, run_id, "failed")
                await broadcast(s, {"type": "run_done", "run_id": run_id, "status": "failed"})
```

- [ ] **Step 4: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q`
Expected: PASS — 137+ passed (the 2 new tests plus all existing).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: resolve local gguf for llama.cpp bench, pass bin dir, log run failures"
```

---

### Task 5: Point `up.sh` at the llama.cpp build dir

**Files:**
- Modify: `up.sh`

- [ ] **Step 1: Add the env default**

In `up.sh`, after `#!/bin/bash` (before the venv lines), add:

```bash
# Point llama-bench discovery at a local llama.cpp build if present.
if [ -z "${LLMBENCH_LLAMA_CPP_BIN_DIR:-}" ] && [ -d "$HOME/llama.cpp/build/bin" ]; then
    export LLMBENCH_LLAMA_CPP_BIN_DIR="$HOME/llama.cpp/build/bin"
fi
```

- [ ] **Step 2: Sanity check**

Run: `bash -n up.sh`
Expected: no output (syntax OK).

- [ ] **Step 3: Commit**

```bash
git add up.sh
git commit -m "chore: default llama-bench bin dir to local llama.cpp build in up.sh"
```

---

### Task 6: Live verification

- [ ] **Step 1: Restart the app**

Run: `cd /home/ruben/test/llmbench && ./down.sh && ./up.sh`
Wait a few seconds, then check readiness:
`curl -s http://localhost:8000/api/servers | python3 -m json.tool`
Expected: `"llama.cpp": true`.

- [ ] **Step 2: Confirm the backend resolves the GGUF and builds a working command**

Run:
```bash
curl -s -X POST http://localhost:8000/api/configs/generate \
  -H "Content-Type: application/json" \
  -d '{"repo_id":"LiquidAI/LFM2-350M-Extract-GGUF","server_id":"llama.cpp","n":1,"vram_gb":15.9,"readme_flags":{"-hf":"LiquidAI/LFM2-350M-Extract-GGUF"},"weights_bytes":219307648,"ram_gb":23.3,"model_arch":null}' \
  | python3 -m json.tool
```
Expected: `bench_command[0]` is the absolute llama-bench path, `-m` is the snapshot GGUF path, contains `--fit-ctx` and `-p <int>` `-n 128`, and no `-c`/`-hf`.

- [ ] **Step 3: Run the generated command manually to confirm it works**

Run the exact `bench_command` from Step 2 (bash array form) with `timeout 90`. Expected: exit 0 and a CSV row with a non-zero `avg_ts`.

- [ ] **Step 4: Exercise the full API run cycle**

POST `/api/benchmarks` with the generated config; poll `GET /api/benchmarks/{run_id}` every 1s. Expected: `status` becomes `"completed"` and `results` has a row with non-null `decode_tps`.

- [ ] **Step 5: Confirm the UI flow**

In the running app at http://localhost:5173, load the LFM2 GGUF, ANALYZE, GENERATE, RUN BENCHMARK. Expected: RUN disables then re-enables, config progress advances, the ranked Results table populates with the llama.cpp row and its DECODE t/s, and no `Error: run failed`.

- [ ] **Step 6: Commit any verification fixes**

If the live run exposed a discrepancy, fix it TDD-style (failing test first) and commit with a descriptive message.

---

## Self-Review Notes

- **Spec coverage:** bin-dir resolution (Tasks 1-2, 4), v9992 CLI command gen (Task 2), workload token counts (Task 2), local GGUF resolution backend-side (Task 4), CSV parser both formats (Task 3), failure logging (Task 4), `up.sh` default (Task 5), live verification (Task 6). All spec sections mapped.
- **Type consistency:** `bin_dir` is `str | None` throughout (`Settings.llama_cpp_bin_dir` is `Path | None`, converted with `str(...) if ... else None` at both call sites). `resolve_bench_binary` returns `str | None`. `build_bench_command` gained only the optional `bin_dir` kwarg; existing vllm/sglang tests unchanged.
- **Parser detection:** `avg_ts in rows[0]` guards empty input; legacy path unchanged so `test_parse_llama_bench_csv_schema_drift` still passes.
