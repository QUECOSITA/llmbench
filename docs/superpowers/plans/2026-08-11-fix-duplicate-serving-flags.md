# Fix Duplicate Long/Short Serving Flags in Generated Configs

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Prevent generated serving commands from containing both a flag and its short alias (e.g. `--ctx-size 4096` **and** `-c 4096`) by canonicalizing README flag aliases.

**Architecture:** The bug lives in `backend/app/flags.py` — `_baseline()` merges README flags into the defaults dict but never maps short aliases (`-c`, `-ngl`, `-b`, `-t`, `-n`) to their canonical long forms. The repo already has the correct machinery in `backend/app/servers.py` (`README_FLAG_MAP` + `_canonical_flags`), used only on the bench path. We'll apply the same canonicalization on the serving path: normalize aliases in `_baseline` (long form wins), plus first-wins dedup in `build_serving_command` as defense-in-depth. Backend-only change; frontend just renders the returned `serving_command` string.

**Tech Stack:** Python (FastAPI backend), existing `README_FLAG_MAP` in `servers.py`, `pytest`.

---

## File Structure

- Modify: `backend/app/flags.py` — canonicalize README aliases in `_baseline`; add first-wins dedup in `build_serving_command`.
- Test: `backend/tests/test_flags.py` — add regression tests.
- No frontend changes.

Dependencies/imports: `flags.py` currently imports only `shlex`. It will need to import `README_FLAG_MAP` from `app.servers`. `servers.py` does **not** import `flags.py` (verified), so no circular import.

---

### Task 1: Canonicalize README flag aliases in `_baseline`

**Files:**
- Modify: `backend/app/flags.py:1` (add import) and `:28-37` (`_baseline`)
- Test: `backend/tests/test_flags.py`

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_flags.py`:

```python
def test_baseline_readme_short_alias_is_canonicalized():
    cfg = generate_configs("llama.cpp", {"-c": "8192"}, 1, 24)[0]["flags"]
    assert cfg["--ctx-size"] == "8192"
    assert "-c" not in cfg


def test_baseline_long_form_wins_over_short_alias():
    cfg = generate_configs("llama.cpp", {"-c": "57344", "--ctx-size": "4096"}, 1, 24)[0]["flags"]
    assert cfg["--ctx-size"] == "4096"
    assert "-c" not in cfg


def test_baseline_other_aliases_canonicalized():
    cfg = generate_configs(
        "llama.cpp", {"-ngl": "40", "-b": "2048", "-t": "8"}, 1, 24
    )[0]["flags"]
    assert cfg["--n-gpu-layers"] == "40"
    assert cfg["--batch-size"] == "2048"
    assert "--threads" in cfg
    assert "-ngl" not in cfg
    assert "-b" not in cfg
    assert "-t" not in cfg
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_flags.py -v`
Expected: new tests FAIL — `cfg["--ctx-size"]` present but `"-c" in cfg` is True (short alias not stripped).

- [x] **Step 3: Write minimal implementation**

Add import to `backend/app/flags.py:1`:

```python
import shlex

from app.servers import README_FLAG_MAP
```

Replace `_baseline` (`backend/app/flags.py:28-37`):

```python
def _baseline(server_id: str, readme_flags: dict[str, str], vram_gb: float) -> dict[str, str]:
    flags: dict[str, str] = {}
    for key, default in DEFAULTS[server_id].items():
        flags[key] = str(default)
    mapping = README_FLAG_MAP.get(server_id, {})
    for flag, value in readme_flags.items():
        canon = mapping.get(flag, flag)
        if canon == "--spec-type":
            value = _SPEC_TYPE_ALIASES.get(value, value)
        # Canonical long form wins: if we already have a value for this key
        # (from DEFAULTS or an earlier long-form README entry), keep it.
        if flag in KEY_FLAGS[server_id] or flag not in DEFAULTS[server_id]:
            if canon not in flags:
                flags[canon] = value
    return flags
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_flags.py -v`
Expected: all tests PASS, including the pre-existing `test_llama_spec_type_*` and `test_generate_configs_*` suites.

- [x] **Step 5: Commit**

```bash
git add backend/app/flags.py backend/tests/test_flags.py
git commit -m "fix: canonicalize README flag aliases in generated configs"
```

---

### Task 2: Defense-in-depth dedup in `build_serving_command`

**Files:**
- Modify: `backend/app/flags.py:80-92` (`build_serving_command`)
- Test: `backend/tests/test_flags.py`

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_flags.py`:

```python
def test_build_serving_command_strips_duplicate_alias():
    cmd = build_serving_command(
        "llama.cpp", "org/model",
        {"--ctx-size": "4096", "-c": "8192"},
        gguf_filename="x.gguf",
    )
    tokens = cmd.split()
    assert "-c" not in tokens
    assert "--ctx-size 4096" in cmd
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_flags.py::test_build_serving_command_strips_duplicate_alias -v`
Expected: FAIL — `-c` is present in the command.

- [x] **Step 3: Write minimal implementation**

Add a module-level helper and use it in `build_serving_command` (first-wins, matching `servers._canonical_flags` semantics):

```python
def _canonicalize(server_id: str, flags: dict[str, str]) -> dict[str, str]:
    mapping = README_FLAG_MAP.get(server_id, {})
    out: dict[str, str] = {}
    for flag, value in flags.items():
        canon = mapping.get(flag, flag)
        if canon not in out:
            out[canon] = value
    return out
```

In `build_serving_command`, before assembling tokens, canonicalize the flags:

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
        if gguf_filename or gguf_path:
            flags = {k: v for k, v in flags.items() if k not in _LLAMA_MODEL_FLAGS}
        flags = _canonicalize(server_id, flags)
        cmd += _flag_tokens(flags)
        return " ".join(cmd)
    raise ValueError(f"unknown server {server_id}")
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_flags.py -v`
Expected: all PASS, including `test_build_serving_command_*` and `test_llama_serving_command_strips_readme_m_when_hf_file_given`.

- [x] **Step 5: Commit**

```bash
git add backend/app/flags.py backend/tests/test_flags.py
git commit -m "fix: dedupe canonical vs alias flags when building serving command"
```

---

### Task 3: Run full local suite (merge gate)

- [x] **Step 1: Backend tests**

Run: `pytest` (from `backend/`)
Expected: all pass.

- [x] **Step 2: Frontend typecheck + unit tests**

Run: `npx tsc -b && npx vitest run` (from `frontend/`)
Expected: pass. No frontend source changes expected (it only renders the returned `serving_command`); this confirms no regression.

- [x] **Step 3: Playwright e2e (if local env supports)**

Run via the repo's e2e setup. If not runnable locally, note that CI will cover it.

- [x] **Step 4: No commit** — this is verification only; continue per AGENTS.md safe-developing workflow (work on a branch, wait for security scans before merge).
