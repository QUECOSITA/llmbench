# llama.cpp Config Bank Upgrade — `--load-mode none --no-mmproj` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the llama.cpp config bank so every generated llama-server serving command always pins `--load-mode none --no-mmproj` (first position), README-provided deprecated memory-mode flags are dropped, and removed speculative-decoding aliases map to their modern `--spec-draft-n-*` forms.

**Architecture:** The pinned flags are prepended to `DEFAULTS["llama.cpp"]` in `backend/app/flags.py`, so every generated config seeds them and `_flag_tokens` emits them before the swept knobs. `_baseline` drops a `LLAMA_DROPPED_FLAGS` set while merging README flags and re-asserts the `LLAMA_PINNED_FLAGS` afterwards. `backend/app/servers.py` extends `README_FLAG_MAP` with the removed-spec aliases; `_LLAMA_BENCH_FLAGS` is untouched so llama-bench never receives the pinned flags. Frontend fixtures are updated cosmetically.

**Tech Stack:** Python (FastAPI), React + TS, Vitest, Playwright.

**Repo conventions:** work on a feature branch (`git checkout -b feature/llama-cpp-load-mode-flags`); never touch `main`; run full suite (`pytest`, `tsc -b` + `vitest run`, `playwright test`) before finishing.

**Reference (verified on llama.cpp b10472):** design spec `docs/superpowers/specs/2026-08-17-llama-cpp-load-mode-flags-design.md`.

---

### Task 1: Backend — pin `--load-mode none --no-mmproj` + sanitize README flags

**Files:**
- Modify: `backend/app/flags.py`
- Modify: `backend/app/servers.py`
- Test: `backend/tests/test_flags.py`, `backend/tests/test_servers.py`

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_flags.py`)

```python
def test_baseline_pins_load_mode_and_no_mmproj():
    cfg = generate_configs("llama.cpp", {}, 1, 24)[0]["flags"]
    assert cfg["--load-mode"] == "none"
    assert cfg["--no-mmproj"] == ""


def test_pinned_flags_present_in_every_generated_config():
    for cfg in generate_configs("llama.cpp", {}, 12, 24):
        assert cfg["flags"]["--load-mode"] == "none"
        assert cfg["flags"]["--no-mmproj"] == ""


def test_serving_command_prioritizes_pinned_flags():
    cfg = generate_configs("llama.cpp", {}, 1, 24)[0]
    cmd = build_serving_command("llama.cpp", "org/model", cfg["flags"], gguf_filename="x.gguf")
    assert "--load-mode none" in cmd
    assert "--no-mmproj" in cmd
    assert cmd.index("--load-mode") < cmd.index("--ctx-size")
    assert cmd.index("--no-mmproj") < cmd.index("--ctx-size")


def test_readme_deprecated_memory_flags_dropped():
    cfg = generate_configs(
        "llama.cpp",
        {"--no-mmap": "", "--mlock": "", "--direct-io": "", "--defrag-thold": "0", "-dt": "0"},
        1, 24,
    )[0]["flags"]
    for bad in ("--no-mmap", "--mlock", "--direct-io", "--defrag-thold", "-dt"):
        assert bad not in cfg
    assert cfg["--load-mode"] == "none"


def test_readme_mmproj_auto_flags_dropped():
    cfg = generate_configs("llama.cpp", {"--mmproj-auto": "", "--no-mmproj-auto": ""}, 1, 24)[0]["flags"]
    assert "--mmproj-auto" not in cfg
    assert "--no-mmproj-auto" not in cfg
    assert cfg["--no-mmproj"] == ""


def test_readme_modern_load_mode_overridden():
    cfg = generate_configs("llama.cpp", {"--load-mode": "mlock"}, 1, 24)[0]["flags"]
    assert cfg["--load-mode"] == "none"


def test_readme_removed_draft_flags_mapped():
    cfg = generate_configs("llama.cpp", {"--draft-max": "3", "--draft-min": "1"}, 1, 24)[0]["flags"]
    assert cfg["--spec-draft-n-max"] == "3"
    assert cfg["--spec-draft-n-min"] == "1"
    assert "--draft-max" not in cfg
    assert "--draft-min" not in cfg


def test_readme_removed_draft_short_aliases_mapped():
    cfg = generate_configs("llama.cpp", {"--draft": "2", "--draft-n": "4"}, 1, 24)[0]["flags"]
    assert cfg["--spec-draft-n-max"] == "2"
    assert "--draft" not in cfg
    assert "--draft-n" not in cfg
```

- [ ] **Step 2: Append the bench-exclusion test** to `backend/tests/test_servers.py`

```python
def test_build_bench_command_excludes_load_mode_and_no_mmproj(tmp_path):
    workload = tmp_path / "p.jsonl"
    workload.write_text('{"prompt": "hello world"}\n')
    cmd = build_bench_command(
        "llama.cpp", "/models/x.gguf",
        {"--ctx-size": "4096", "--load-mode": "none", "--no-mmproj": ""},
        workload=str(workload), timeout_s=60,
    )
    assert "--load-mode" not in cmd
    assert "--no-mmproj" not in cmd
    assert cmd[cmd.index("--fit-ctx") + 1] == "4096"
```

- [ ] **Step 3: Run both new test files to verify they fail**

Run: `cd backend && python -m pytest tests/test_flags.py tests/test_servers.py -q`
Expected: FAIL — new tests error (e.g. `--load-mode` missing from baseline, `--no-mmap` still present).

- [ ] **Step 4: Implement in `backend/app/flags.py`**

Replace the top of the module (lines 1-22) so it reads:

```python
import shlex

from app.servers import README_FLAG_MAP

KEY_FLAGS = {
    "llama.cpp": ["--ctx-size", "--n-gpu-layers", "--batch-size", "--spec-type", "--spec-draft-n-max"],
}

VALUE_POOLS = {
    "llama.cpp": {
        "--ctx-size": [2048, 4096, 8192, 16384],
        "--n-gpu-layers": [999, 40, 0],
        "--batch-size": [512, 2048],
        "--spec-type": ["draft-mtp", "none"],
        "--spec-draft-n-max": [2, 3],
    },
}

# Pinned flags applied to every generated llama-server command, emitted first
# (right after the model reference). --load-mode none avoids mmap; --no-mmproj
# disables the mmproj auto-download that is on by default when using -hf.
LLAMA_PINNED_FLAGS = {"--load-mode": "none", "--no-mmproj": ""}

# README flags dropped during _baseline merge. Deprecated memory-mode flags and
# --defrag-thold/-dt are superseded by the pinned --load-mode none; the mmproj
# auto variants are superseded by the pinned --no-mmproj. Emitting these
# alongside --load-mode is itself deprecated (arg.cpp:883).
LLAMA_DROPPED_FLAGS = {
    "--mlock", "--mmap", "--no-mmap", "--direct-io", "--no-direct-io",
    "--defrag-thold", "-dt", "--mmproj-auto", "--no-mmproj-auto",
}

DEFAULTS = {
    "llama.cpp": {"--load-mode": "none", "--no-mmproj": "",
                  "--ctx-size": 4096, "--n-gpu-layers": 999, "--batch-size": 512,
                  "--spec-type": "draft-mtp", "--spec-draft-n-max": 2},
}
```

Then update `_baseline` (lines 30-54) to skip dropped flags and re-assert the pins:

```python
def _baseline(server_id: str, readme_flags: dict[str, str], vram_gb: float) -> dict[str, str]:
    flags: dict[str, str] = {}
    for key, default in DEFAULTS[server_id].items():
        flags[key] = str(default)
    mapping = README_FLAG_MAP.get(server_id, {})
    canon_from_readme: set[str] = set()
    for flag, value in readme_flags.items():
        if flag in LLAMA_DROPPED_FLAGS:
            continue
        canon = mapping.get(flag, flag)
        # Only canonical long-form README entries override the defaults directly.
        if canon == flag:
            if canon == "--spec-type":
                value = _SPEC_TYPE_ALIASES.get(value, value)
            if flag in KEY_FLAGS[server_id] or flag not in DEFAULTS[server_id]:
                flags[canon] = value
                canon_from_readme.add(canon)
    for flag, value in readme_flags.items():
        if flag in LLAMA_DROPPED_FLAGS:
            continue
        canon = mapping.get(flag, flag)
        # Aliases (e.g. -c) map to their canonical long form; the long form
        # wins if the README also provided it explicitly.
        if canon != flag and canon not in canon_from_readme:
            if canon == "--spec-type":
                value = _SPEC_TYPE_ALIASES.get(value, value)
            if flag in KEY_FLAGS[server_id] or flag not in DEFAULTS[server_id]:
                flags[canon] = value
    # The pins are non-negotiable: a README may not override load-mode/mmproj.
    for flag, value in LLAMA_PINNED_FLAGS.items():
        flags[flag] = value
    return flags
```

- [ ] **Step 5: Implement in `backend/app/servers.py`**

Extend `README_FLAG_MAP["llama.cpp"]` (lines 24-29) with the removed-spec aliases:

```python
README_FLAG_MAP = {
    "llama.cpp": {
        "-c": "--ctx-size", "-n": "--predict", "-t": "--threads", "-b": "--batch-size",
        "-ngl": "--n-gpu-layers", "-m": "-m",
        # Removed speculative-decoding aliases (llama.cpp b10472) map to the
        # modern --spec-draft-n-* flags, preserving their values.
        "--draft": "--spec-draft-n-max", "--draft-n": "--spec-draft-n-max",
        "--draft-max": "--spec-draft-n-max", "--draft-n-max": "--spec-draft-n-max",
        "--draft-min": "--spec-draft-n-min", "--draft-n-min": "--spec-draft-n-min",
    },
}
```

Extend `_SPEC_DECODING_FLAGS` (line 74-79) so READMEs still using removed draft
names still trigger spec-decoding detection:

```python
_SPEC_DECODING_FLAGS = {
    "--spec-type", "-md", "--model-draft", "--model-mtp", "-mtmd",
    "--draft", "--draft-n", "--draft-max", "--draft-min", "--draft-p-min",
    "--spec-draft-n-max", "--spec-draft-n-min", "--spec-raw-logits",
    "--spec-heuristics", "--spec-heuristic-acc", "--spec-heuristic-min-tokens",
}
```

- [ ] **Step 6: Run the backend flag/server tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_flags.py tests/test_servers.py -q`
Expected: PASS (all new + existing tests green, including `test_roundtrip_rebuild_bench_command_matches_generated`).

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/flags.py backend/app/servers.py backend/tests/test_flags.py backend/tests/test_servers.py
git commit -m "feat: pin --load-mode none --no-mmproj in llama.cpp config bank"
```

---

### Task 2: Frontend — update sample serving-command fixtures

**Files:**
- Modify: `frontend/src/components/ConfigBank.test.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/e2e/mock-server.ts`

Sample llama-server commands gain `--load-mode none --no-mmproj` after the model
reference (`--hf-repo ... --hf-file ...`), matching the new backend output.
Speed-bench fixtures gain the pins too. Any regex/display-value assertion that
references the old string must be updated to the new string.

- [ ] **Step 1: Update `frontend/src/components/ConfigBank.test.tsx`**

Every `llama-server --hf-repo m --hf-file model.gguf` string becomes
`llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj`.
Specifically:

- Line 8: `serving_command: "llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj --ctx-size 8192"` and `flags` gains `"--load-mode": "none", "--no-mmproj": ""`.
- Line 9: same with `--ctx-size 4096`.
- Line 12: update the `getByText` regex to
  `/llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj --ctx-size 8192/i`.
- Line 19: `serving_command: "llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj"`.
- Line 21: `getByDisplayValue("llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj")`.
- Line 22: new value `"llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj --ctx-size 16384"`.
- Line 30: `serving_command: "llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj --ctx-size 8192"`.
- Line 35: `serving_command: "llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj --ctx-size 16384"`.
- Line 45: `serving_command: "llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj"`.
- Lines 52, 64, 78: `--spec-type draft-mtp` / bare commands gain
  `--load-mode none --no-mmproj` (e.g. line 52: `"llama-server --load-mode none --no-mmproj --spec-type draft-mtp"`, line 78: `"llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj"`).

- [ ] **Step 2: Update `frontend/src/App.test.tsx`**

Replace every `llama-server --hf-repo org/model --hf-file model.gguf --ctx-size 8192`
(line 264, 310, 1002, 1051) and `llama-server --hf-repo org/model --hf-file model.gguf`
(line 607, 662) with the pinned variants:

- `"llama-server --hf-repo org/model --hf-file model.gguf --load-mode none --no-mmproj --ctx-size 8192"`
- `"llama-server --hf-repo org/model --hf-file model.gguf --load-mode none --no-mmproj"`

Speed-bench fixtures (lines 582, 691): `"llama-server --spec-type draft-mtp"` →
`"llama-server --load-mode none --no-mmproj --spec-type draft-mtp"`.

Keep `--n-gpu`/`python serve.py` fixtures (lines 23, 573, 1009) unchanged — they
are not llama-server commands.

- [ ] **Step 3: Update `frontend/e2e/mock-server.ts`**

- Line 94-95: `flags` gains `"--load-mode": "none", "--no-mmproj": ""` and
  `serving_command` becomes `"llama-server --hf-repo org/model --hf-file model.gguf --load-mode none --no-mmproj --ctx-size 8192"`.
- Line 116-117: `flag_conf` gains the pins and `serving_command` matches the new shape.

- [ ] **Step 4: Run frontend typecheck + unit tests**

Run: `cd frontend && npx tsc -b && npx vitest run`
Expected: PASS (no type errors, all unit tests green).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ConfigBank.test.tsx frontend/src/App.test.tsx frontend/e2e/mock-server.ts
git commit -m "test(frontend): show pinned --load-mode none --no-mmproj in sample commands"
```

---

### Task 3: Full verification + finish

**Files:** none (verification only)

- [ ] **Step 1: Run the full local suite**

Backend: `cd backend && python -m pytest -q` → PASS.
Frontend: `cd frontend && npx tsc -b && npx vitest run` → PASS.
Playwright e2e: `cd frontend && npx playwright test` → PASS.

- [ ] **Step 2: Manually eyeball a generated serving command**

Run: `cd backend && python -c "from app.flags import generate_configs, build_serving_command; c=generate_configs('llama.cpp', {}, 1, 24)[0]; print(build_serving_command('llama.cpp', 'org/model', c['flags'], gguf_filename='x.gguf'))"`
Expected: `llama-server --hf-repo org/model --hf-file x.gguf --load-mode none --no-mmproj --ctx-size 4096 --n-gpu-layers 999 --batch-size 512 --spec-type draft-mtp --spec-draft-n-max 2`

- [ ] **Step 3: `git status` / `git diff` review, then commit any stragglers**

```bash
git status
git diff
git add docs/superpowers/specs/2026-08-17-llama-cpp-load-mode-flags-design.md docs/superpowers/plans/2026-08-17-llama-cpp-load-mode-flags.md
git commit -m "docs: add llama.cpp load-mode config bank design spec + plan"
```

- [ ] **Step 4: Push + open PR** (do NOT merge — merge requires explicit user instruction)

```bash
git push origin feature/llama-cpp-load-mode-flags
gh pr create --title "feat: pin --load-mode none --no-mmproj in llama.cpp config bank" --body "See plan + design spec in docs/superpowers/."
```