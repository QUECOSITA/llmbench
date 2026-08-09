# Design: Install Missing Serving Server + Truthful Readiness

## Problem

The app's readiness detection lies. vLLM and sglang are reported "ready" whenever
*any* `python` is on `PATH`, because `SERVERS["vllm"]["bench_binaries"] = ["python"]`
(`backend/app/servers.py:14`) and `detect_binaries()` resolves it with
`shutil.which("python")`. Running a vLLM/sglang benchmark therefore always fails at
runtime with `ModuleNotFoundError: No module named 'vllm'` while the UI still shows the
server as ready.

Separately, when a serving server is genuinely missing, there is no workflow to
install it. This design adds one, driven by the agent: detect → ask the user → verify
the system → fetch the current install guide via ctx7 → install → continue.

## Scope

- **Backend (CI-tested, pytest):**
  - Truthful readiness: vLLM/sglang are ready only when their module is importable in
    the interpreter that spawns the bench (`sys.executable`), not when `python` exists.
  - A side-effect-free helper module `backend/app/install.py` that reports detection,
    system verification, install commands, and post-install verification. It never
    executes installs itself.
- **Agent skill (`.opencode/skills/install-serving-server/SKILL.md`):**
  - Orchestrates: ask the user → verify → ctx7 install guide → install into the backend
    venv → re-verify → continue the workflow.
- **No frontend changes.** The frontend never renders `readiness`; plumbing tests stay
  green. No `opencode.json` change: `.opencode/skills/` is auto-discovered.

## Part A — Truthful readiness (`backend/app/servers.py`)

- Add a `module` key to `SERVERS["vllm"]` (`"vllm"`) and `SERVERS["sglang"]` (`"sglang"`).
- `resolve_bench_binary` / `detect_binaries`: for vLLM/sglang, check
  `importlib.util.find_spec(module)` (same pattern as `speed_bench_deps_available`,
  `servers.py:51`). llama.cpp keeps its binary/PATH logic.
- `build_bench_command` vLLM/sglang paths (`servers.py:346,356`): swap literal `"python"`
  for `sys.executable`, matching `build_speed_bench_command` (`servers.py:204`), so
  readiness and execution target the same interpreter (the backend venv).

**Tests (`backend/tests/test_servers.py`):**
- Regression: `find_spec("vllm")` → `None` with `python` on PATH ⇒
  `detect_binaries()["vllm"] is False` (and sglang).
- Module importable ⇒ ready.
- vLLM/sglang bench commands start with `sys.executable`.
- Existing `which`-mocked tests updated to also mock `find_spec` for the module servers.

## Part B — Install/verify helper (`backend/app/install.py`)

Pure, side-effect-free; CI can test it without touching the system.

- `server_detection(server_id) -> dict`: installed (bool) + version (str|None), reusing
  the fixed detection.
- `verify_system(server_id) -> dict`: python version, pip availability, GPU
  (`detect_hardware()` + driver version via nvidia-smi), VRAM, free disk, OS/arch, and
  `requirements_for(server_id)` (e.g. NVIDIA GPU present, driver suitable for the GPU,
  python >= 3.11).
- `install_commands(server_id) -> list[str]`: base commands:
  - vLLM: `pip install vllm`
  - sglang: `pip install "sglang[all]"`
  - llama.cpp: CUDA build-from-source steps (`cmake -B build -DGGML_CUDA=on` …)
  - Targets the backend venv so `sys.executable` sees the module.
- `verify_install(server_id) -> dict`: re-runs detection; success + version.
- `python -m app.install <server>` CLI that prints detection → verification → commands
  → post-install re-check. **Prints only; never installs.** The skill executes the
  commands after the user approves.

**Tests (`backend/tests/test_install.py`):**
- `verify_system` returns expected keys with/without GPU.
- `install_commands` returns the expected pip/build commands per server.
- `verify_install` maps a detection result to success/version.

## Part C — Agent skill (`.opencode/skills/install-serving-server/SKILL.md`)

Frontmatter: `name: install-serving-server`; `description` front-loading trigger
keywords (vLLM, sglang, llama.cpp, install, not installed, missing, serving server).

Body workflow:
1. Determine the needed server (e.g. `detected_server` from `/models/analyze`, or the
   readiness report).
2. Detect; if installed, continue the workflow — no prompt.
3. If missing, **ask the user** whether to install (explicit, per AGENTS.md safety).
4. Verify the system via the Part B helper; present GPU/driver/python/disk report.
5. **ctx7 lookup** — `npx ctx7@latest library <server> "<hw-specific install>"`, pick the
   best source, `npx ctx7@latest docs <id> "<question>"`; use the fetched *current*
   guidance (Blackwell/sm_120 requires recent torch + vLLM) to refine the install
   commands. Never hardcode versions.
6. Present the install plan; on approval run it into `backend/.venv`.
7. `verify_install`; then **continue** the benchmark/serve workflow.

## CI / verification

- Backend `pytest` covers Parts A + B (new/updated tests) — runs in
  `.github/workflows/ci.yml`.
- Frontend `tsc -b` + `vitest run` + Playwright e2e unchanged; still run locally before
  finishing (per AGENTS.md).
- Full local suite before completion: backend pytest, frontend typecheck + unit, e2e.

## Safety

- Nothing auto-installs; every install is gated behind the explicit user prompt.
- Install target is `backend/.venv`; no system-wide or destructive changes.
- `"python"` → `sys.executable` is a behavior change: a vLLM installed in a different
  interpreter than the backend venv will no longer be detected/used. This is intended
  (speed-bench already behaves this way) and will be called out in the PR.
- The in-flight uncommitted download-console WS work is untouched (disjoint files).
