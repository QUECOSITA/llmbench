# llama.cpp HF-Repo Resolution + Spec-Flag Sweep — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the CONFIG BANK generate llama.cpp configs that resolve the model via `--hf-repo`/`--hf-file` (serving) and `-hfr`/`-hff` (llama-bench) instead of `-m <local_path>`, and sweep `--spec-type draft-mtp` / `--spec-draft-n-max` as key flags with correct values.

**Architecture:** Backend-only change. `backend/app/flags.py` owns the config bank (KEY_FLAGS/VALUE_POOLS/DEFAULTS, `_baseline`, `build_serving_command`); `backend/app/servers.py` owns `build_bench_command`; `backend/app/api.py` resolves the gguf filename and threads it into both builders. llama-bench keeps stripping server-only spec flags via the existing `_LLAMA_BENCH_FLAGS` whitelist. No frontend changes.

**Tech Stack:** Python 3 / FastAPI, pytest (TDD), llama.cpp build at `$HOME/llama.cpp/build/bin`.

---

## Task 1: Config bank spec flags + readme `mtp` → `draft-mtp` normalization

**Files:**
- Modify: `backend/app/flags.py:1-31` (KEY_FLAGS, VALUE_POOLS, DEFAULTS)
- Modify: `backend/app/flags.py:42-53` (`_baseline`)
- Test: `backend/tests/test_flags.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_flags.py`:

```python
def test_llama_spec_flags_in_baseline():
    cfg = generate_configs("llama.cpp", {}, 1, 24)[0]["flags"]
    assert cfg["--spec-type"] == "draft-mtp"
    assert cfg["--spec-draft-n-max"] == "2"


def test_llama_spec_type_readme_mtp_normalizes_to_draft_mtp():
    cfg = generate_configs("llama.cpp", {"--spec-type": "mtp"}, 1, 24)[0]["flags"]
    assert cfg["--spec-type"] == "draft-mtp"


def test_llama_spec_type_sweeps_variants():
    configs = generate_configs("llama.cpp", {}, 12, 24)
    spec_types = {c["flags"]["--spec-type"] for c in configs}
    n_max = {c["flags"]["--spec-draft-n-max"] for c in configs}
    assert spec_types == {"draft-mtp", "none"}
    assert n_max == {"2", "3"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_flags.py -q`
Expected: the three new tests FAIL (e.g. `KeyError: '--spec-type'`).

- [ ] **Step 3: Implement**

In `backend/app/flags.py`, change the three module constants:

```python
KEY_FLAGS = {
    "llama.cpp": ["--ctx-size", "--n-gpu-layers", "--batch-size", "--spec-type", "--spec-draft-n-max"],
    "vllm": ["--max-model-len", "--max-num-seqs", "--gpu-memory-utilization", "--enforce-eager"],
    "sglang": ["--context-length", "--max-running-requests", "--mem-fraction-static", "--tp-size"],
}

VALUE_POOLS = {
    "llama.cpp": {
        "--ctx-size": [2048, 4096, 8192, 16384],
        "--n-gpu-layers": [999, 40, 0],
        "--batch-size": [512, 2048],
        "--spec-type": ["draft-mtp", "none"],
        "--spec-draft-n-max": [2, 3],
    },
    "vllm": {
        "--max-model-len": [4096, 8192, 16384],
        "--max-num-seqs": [16, 32, 64],
        "--gpu-memory-utilization": [0.85, 0.9, 0.95],
        "--enforce-eager": ["", "--enforce-eager"],
    },
    "sglang": {
        "--context-length": [4096, 8192, 16384],
        "--max-running-requests": [16, 32, 64],
        "--mem-fraction-static": [0.85, 0.9],
        "--tp-size": [1],
    },
}

DEFAULTS = {
    "llama.cpp": {"--ctx-size": 4096, "--n-gpu-layers": 999, "--batch-size": 512,
                  "--spec-type": "draft-mtp", "--spec-draft-n-max": 2},
    "vllm": {"--max-model-len": 8192, "--max-num-seqs": 32, "--gpu-memory-utilization": 0.9, "--enforce-eager": ""},
    "sglang": {"--context-length": 8192, "--max-running-requests": 32, "--mem-fraction-static": 0.9, "--tp-size": 1},
}
```

Replace `_baseline` (currently lines 42-53) and add the alias map above it:

```python
_SPEC_TYPE_ALIASES = {"mtp": "draft-mtp", "draft-mtp": "draft-mtp"}


def _baseline(server_id: str, readme_flags: dict[str, str], vram_gb: float) -> dict[str, str]:
    flags: dict[str, str] = {}
    for key, default in DEFAULTS[server_id].items():
        flags[key] = str(default)
    if server_id == "vllm":
        flags["--gpu-memory-utilization"] = _gpu_util_for_vram("vllm", vram_gb)
    if server_id == "sglang":
        flags["--mem-fraction-static"] = _gpu_util_for_vram("sglang", vram_gb)
    for flag, value in readme_flags.items():
        if flag == "--spec-type":
            value = _SPEC_TYPE_ALIASES.get(value, value)
        if flag in KEY_FLAGS[server_id] or flag not in DEFAULTS[server_id]:
            flags[flag] = value
    return flags
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_flags.py -q`
Expected: PASS (all tests, including the three new ones).

- [ ] **Step 5: Commit**

```bash
git add backend/app/flags.py backend/tests/test_flags.py
git commit -m "feat: sweep llama.cpp spec-type/spec-draft-n-max in config bank"
```

---

## Task 2: Serving command uses `--hf-repo`/`--hf-file`

**Files:**
- Modify: `backend/app/flags.py:87-98` (`build_serving_command`)
- Test: `backend/tests/test_flags.py`

- [ ] **Step 1: Write the failing tests**

Replace `test_gguf_llama_command` in `backend/tests/test_flags.py` and append two tests:

```python
def test_gguf_llama_command():
    cmd = build_serving_command("llama.cpp", "org/model", {"-c": "4096", "-ngl": "999"},
                                gguf_filename="x.gguf")
    assert "--hf-repo org/model" in cmd
    assert "--hf-file x.gguf" in cmd
    assert "-m" not in cmd


def test_gguf_llama_command_falls_back_to_path():
    cmd = build_serving_command("llama.cpp", "org/model", {"-c": "4096"},
                                gguf_path="/models/x.gguf")
    assert "-m /models/x.gguf" in cmd


def test_llama_serving_command_includes_spec_flags():
    cmd = build_serving_command("llama.cpp", "org/model",
                                {"--spec-type": "draft-mtp", "--spec-draft-n-max": "2"},
                                gguf_filename="x.gguf")
    assert "--hf-repo org/model" in cmd
    assert "--hf-file x.gguf" in cmd
    assert "--spec-type draft-mtp" in cmd
    assert "--spec-draft-n-max 2" in cmd
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_flags.py::test_gguf_llama_command tests/test_flags.py::test_gguf_llama_command_falls_back_to_path tests/test_flags.py::test_llama_serving_command_includes_spec_flags -q`
Expected: FAIL (function signature does not accept `gguf_filename`).

- [ ] **Step 3: Implement**

Replace `build_serving_command` in `backend/app/flags.py`:

```python
def build_serving_command(server_id: str, repo_id: str, flags: dict[str, str],
                          gguf_filename: str | None = None,
                          gguf_path: str | None = None) -> str:
    if server_id == "llama.cpp":
        cmd = ["llama-server"]
        if gguf_filename:
            cmd += ["--hf-repo", repo_id, "--hf-file", gguf_filename]
        elif gguf_path:
            cmd += ["-m", gguf_path]
        cmd += _flag_tokens(flags)
        return " ".join(cmd)
    if server_id == "vllm":
        return "vllm serve " + repo_id + " " + " ".join(_flag_tokens(flags))
    if server_id == "sglang":
        return "python -m sglang.launch_server --model-path " + repo_id + " " + " ".join(_flag_tokens(flags))
    raise ValueError(f"unknown server {server_id}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_flags.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/flags.py backend/tests/test_flags.py
git commit -m "feat: llama.cpp serving command uses --hf-repo/--hf-file"
```

---

## Task 3: Bench command uses `-hfr`/`-hff` and keeps spec flags out

**Files:**
- Modify: `backend/app/servers.py:103-121` (`build_bench_command`)
- Test: `backend/tests/test_servers.py`

- [ ] **Step 1: Write the failing tests**

Replace `test_build_bench_command_llama` and `test_build_bench_command_llama_filters_server_only_flags` in `backend/tests/test_servers.py`, and append one new test:

```python
def test_build_bench_command_llama(tmp_path):
    workload = tmp_path / "p.jsonl"
    workload.write_text('{"prompt": "hello world"}\n')
    cmd = build_bench_command("llama.cpp", model_ref="org/model",
                              flags={"--ctx-size": "4096", "--n-gpu-layers": "999", "-hf": "org/model"},
                              workload=str(workload), timeout_s=60,
                              gguf_filename="x.gguf")
    assert cmd[0] == "llama-bench"
    assert cmd[cmd.index("-hfr") + 1] == "org/model"
    assert cmd[cmd.index("-hff") + 1] == "x.gguf"
    assert "-m" not in cmd
    assert cmd[cmd.index("--fit-ctx") + 1] == "4096"
    assert "-c" not in cmd
    assert "-hf" not in cmd
    assert cmd[cmd.index("-p") + 1] == "6"
    assert cmd[cmd.index("-n") + 1] == "128"
    assert cmd[-4:] == ["-r", "2", "-o", "csv"]


def test_build_bench_command_llama_filters_server_only_flags(tmp_path):
    workload = tmp_path / "p.jsonl"
    workload.write_text('{"prompt": "hello world"}\n')
    flags = {
        "--ctx-size": "4096",
        "--n-gpu-layers": "999",
        "--fit": "on",
        "--spec-type": "mtp",
        "--spec-draft-n-max": "2",
        "--no-mmap": "\\",
        "--jinja": "\\",
        "-m": "Qwen3.6-27B-MTP-UD-IQ3_XXS.gguf",
    }
    cmd = build_bench_command("llama.cpp", "org/model", flags,
                              workload=str(workload), timeout_s=60,
                              gguf_filename="Qwen3.6-27B-MTP-UD-IQ3_XXS.gguf")
    assert cmd[cmd.index("-hfr") + 1] == "org/model"
    assert cmd[cmd.index("-hff") + 1] == "Qwen3.6-27B-MTP-UD-IQ3_XXS.gguf"
    assert "-m" not in cmd
    for bad in ("--fit", "--spec-type", "--spec-draft-n-max", "--no-mmap", "--jinja"):
        assert bad not in cmd


def test_build_bench_command_llama_no_gguf_filename_uses_m(tmp_path):
    workload = tmp_path / "p.jsonl"
    workload.write_text('{"prompt": "hello world"}\n')
    cmd = build_bench_command("llama.cpp", "org/model", {"--ctx-size": "4096"},
                              workload=str(workload), timeout_s=60)
    assert cmd[cmd.index("-m") + 1] == "org/model"
    assert "-hfr" not in cmd
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_servers.py -q`
Expected: the three tests above FAIL (TypeError: unexpected keyword `gguf_filename`, or `-hfr` not found).

- [ ] **Step 3: Implement**

In `backend/app/servers.py`, change the `build_bench_command` signature and the llama.cpp branch. Replace lines 103-121:

```python
def build_bench_command(server_id: str, model_ref: str, flags: dict[str, str],
                        workload: str, timeout_s: int, bin_dir: str | None = None,
                        gguf_filename: str | None = None) -> list[str]:
    flags = _canonical_flags(server_id, flags)
    if server_id == "llama.cpp":
        bench = resolve_bench_binary("llama.cpp", bin_dir) or "llama-bench"
        if gguf_filename:
            cmd = [bench, "-hfr", model_ref, "-hff", gguf_filename]
        else:
            cmd = [bench, "-m", model_ref]
        mapped = {"--ctx-size": "--fit-ctx", "--n-gpu-layers": "-ngl", "--batch-size": "-b", "--threads": "-t"}
        for flag, value in flags.items():
            if flag in _LLAMA_HF_FLAGS or flag == "-m":
                continue
            if flag not in _LLAMA_BENCH_FLAGS:
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_servers.py -q`
Expected: PASS (all tests, including the updated ones).

- [ ] **Step 5: Commit**

```bash
git add backend/app/servers.py backend/tests/test_servers.py
git commit -m "feat: llama-bench resolves model via -hfr/-hff when gguf file known"
```

---

## Task 4: API threads gguf filename into both builders

**Files:**
- Modify: `backend/app/api.py:456-480` (`POST /configs/generate`)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Replace `test_generate_configs_llama_resolves_local_gguf` and `test_generate_configs_llama_falls_back_to_repo_id_when_no_gguf` in `backend/tests/test_api.py`:

```python
def test_generate_configs_llama_resolves_local_gguf(client):
    from app.api import state
    gguf_path = _make_snapshot_gguf(state.settings, "org/model")
    r = client.post("/api/configs/generate", json={
        "repo_id": "org/model", "server_id": "llama.cpp", "n": 2,
        "readme_flags": {"--ctx-size": "4096"},
    })
    assert r.status_code == 200
    for cfg in r.json()["configs"]:
        assert cfg["bench_command"][cfg["bench_command"].index("-hfr") + 1] == "org/model"
        assert cfg["bench_command"][cfg["bench_command"].index("-hff") + 1] == "model.Q4_K_M.gguf"
        assert "--hf-repo org/model" in cfg["serving_command"]
        assert "--hf-file model.Q4_K_M.gguf" in cfg["serving_command"]
        assert gguf_path not in cfg["serving_command"]


def test_generate_configs_llama_falls_back_to_repo_id_when_no_gguf(client):
    r = client.post("/api/configs/generate", json={
        "repo_id": "org/model", "server_id": "llama.cpp", "n": 1,
        "readme_flags": {"--ctx-size": "4096"},
    })
    assert r.status_code == 200
    cfg = r.json()["configs"][0]
    assert cfg["bench_command"][cfg["bench_command"].index("-m") + 1] == "org/model"
    assert "--fit-ctx" in cfg["bench_command"]
    assert "--hf-file" not in cfg["serving_command"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_api.py::test_generate_configs_llama_resolves_local_gguf tests/test_api.py::test_generate_configs_llama_falls_back_to_repo_id_when_no_gguf -q`
Expected: FAIL (`-hfr` not found in bench_command; serving_command still has `-m` path).

- [ ] **Step 3: Implement**

In `backend/app/api.py`, replace the block at lines 456-473 (from `weights = payload.get(...)` through the `build_bench_command` call) with:

```python
    weights = payload.get("weights_bytes")
    resolved_gguf = payload.get("gguf_path")
    gguf_filename = os.path.basename(resolved_gguf) if resolved_gguf else None
    if resolved_gguf is None and server_id == "llama.cpp":
        local_path, name, _size = _resolve_download_path(s, repo_id, "llama.cpp", None)
        resolved_gguf = local_path
        gguf_filename = name
    bin_dir = str(s.settings.llama_cpp_bin_dir) if s.settings.llama_cpp_bin_dir else None
    for cfg in configs:
        cfg["serving_command"] = build_serving_command(
            server_id, repo_id, cfg["flags"],
            gguf_filename=gguf_filename,
            gguf_path=resolved_gguf,
        )
        bench_ref = repo_id if gguf_filename else (resolved_gguf or repo_id)
        cfg["bench_command"] = build_bench_command(
            server_id, bench_ref, cfg["flags"],
            workload=str(s.settings.workload_file),
            timeout_s=s.settings.benchmark_timeout_s,
            bin_dir=bin_dir,
            gguf_filename=gguf_filename,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: thread gguf filename through config generation to builders"
```

---

## Task 5: Full verification + live end-to-end run

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend suite**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: all tests PASS (147 existing + new).

- [ ] **Step 2: Run the frontend suite (unaffected, sanity check)**

Run: `npx tsc -b && npx vitest run`
Expected: `tsc` clean, 59 tests PASS.

- [ ] **Step 3: Restart the app**

Run: `./down.sh` then `./up.sh` (per AGENTS.md — never ad-hoc uvicorn/vite).
Expected: backend on :8000, frontend on :5173.

- [ ] **Step 4: Verify generated commands for the real model**

Run (from `backend/` with venv active):

```bash
curl -s -X POST http://localhost:8000/api/configs/generate \
  -H 'Content-Type: application/json' \
  -d '{"server_id":"llama.cpp","repo_id":"GazTrab/Qwen3.6-27B-MTP-UD-IQ3_XXS-GGUF","n":4,"vram_gb":16.0,"readme_flags":{}}' \
  | python -m json.tool
```

Expected: each `serving_command` starts `llama-server --hf-repo GazTrab/... --hf-file Qwen3.6-27B-MTP-UD-IQ3_XXS.gguf` and contains `--spec-type draft-mtp --spec-draft-n-max 2`; each `bench_command` starts with `llama-bench -hfr GazTrab/... -hff Qwen3.6-27B-MTP-UD-IQ3_XXS.gguf` and contains **no** `--spec-type`/`--spec-draft-n-max`.

- [ ] **Step 5: Live end-to-end benchmark run**

POST one config to `/api/benchmarks` (add `server_id` to each config, as the frontend does), poll `/api/benchmarks/{run_id}` until `status == "completed"`.

Expected: each result has non-null `prompt_processing_tps` / `decode_tps` (llama-bench resolves the model from the HF cache via `-hfr`/`-hff`; no download needed since `~/.cache/huggingface/hub/models--GazTrab--Qwen3.6-27B-MTP-UD-IQ3_XXS-GGUF` exists).

If the run shows `failed`, capture the `output_snippet`: if it indicates a model download attempt, stop and report — do not leave a half-downloaded 12 GB model.

- [ ] **Step 6: Commit any stray state**

Run: `git status`
Expected: working tree clean apart from the committed plan/spec docs. No code changes expected in this step.

---

## Self-Review

**Spec coverage:**
- Serving command uses `--hf-repo`/`--hf-file` → Task 2.
- Bench command uses `-hfr`/`-hff` → Task 3.
- Spec flags swept as key flags with correct values → Task 1.
- Readme `--spec-type mtp` → `draft-mtp` normalization → Task 1.
- Spec flags never leak into llama-bench → Task 3 (whitelist + test).
- API wiring / fallback when no gguf known → Task 4.
- No frontend changes → none required; Task 5 sanity-check proves it.

**Placeholder scan:** every step has exact code, exact commands, expected output. No TODOs.

**Type consistency:** `build_serving_command(server_id, repo_id, flags, gguf_filename=None, gguf_path=None)` is defined in Task 2 and called in Task 4 with `gguf_filename=`/`gguf_path=`. `build_bench_command(server_id, model_ref, flags, workload, timeout_s, bin_dir=None, gguf_filename=None)` is defined in Task 3 and called in Task 4 with `bench_ref` + `gguf_filename=`. `generate_configs` unchanged signature. All names match.
