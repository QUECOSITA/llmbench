# Cross-Platform Startup Requirements Gate — Design

**Date:** 2026-08-15
**Status:** Approved by user (via plan approval)

## Problem

`up.sh` (Linux/macOS) currently verifies only llama.cpp before starting. Python
version, Node version, and the HF CLI are never checked up-front: `up.sh` runs
`npm install && npm run dev` in the background even when Node is absent, and the
HF CLI (`hf`) is only caught at download time with a 400 error. `up.ps1`
(Windows) checks Python presence, `npm.cmd`, and llama.cpp, but not versions and
not the HF CLI. Result: users can start the app and hit confusing failures later.

## Goal

On **every platform** (Linux, macOS, Windows), the startup workflow must:

1. **Show all requirements up-front** with their status (banner).
2. **Verify each requirement.**
3. **Inform the user** of anything missing.
4. **Continue only if the hard requirements are met; otherwise exit** with
   actionable install instructions.

## Requirements classification (confirmed with user)

| Requirement            | Gate type      |
|------------------------|----------------|
| Python 3.11+           | **hard**       |
| Node.js 20+            | **hard**       |
| HF CLI (`hf`/`huggingface-cli`) | **hard** |
| llama.cpp (`llama-bench`+`llama-server`) | **hard** (existing interactive flow) |
| NVIDIA GPU             | informational  |
| speed-bench deps       | informational / auto-installed |

## Decisions (confirmed with user)

- **HF CLI hard gate + reliability fix:** add `huggingface-hub` to the backend
  **core** `dependencies` in `pyproject.toml`. The venv then always provides
  `hf`/`huggingface-cli` regardless of the optional speed-bench install. The
  gate verifies the venv **after** `pip install` (that is where the app spawns
  `hf`), so fresh installs are not falsely rejected before the venv exists.
  The banner announces HF CLI as a requirement from the very start.
- **Hard gates (exit on failure):** Python ≥ 3.11, Node ≥ 20.
  - Linux/macOS (`up.sh`): check `python3 --version` and `node --version`
    before starting anything. This is new for Node on `up.sh`.
  - Windows (`up.ps1`): keep the existing `py -3`/`python` presence checks and
    **add** version checks (≥ 3.11) and a Node version check (≥ 20).
- **llama.cpp:** the existing interactive resolution flow in
  `scripts/ensure-llama-cpp.sh` (Linux/macOS) and `Resolve-LlamaCpp`
  (Windows) is **untouched** — it is the "verify llama.cpp" step. Banner lists
  it; resolution happens next.
- **Informational only:** NVIDIA GPU detected/absent (CPU-only build is fine),
  speed-bench deps optional/auto-installed. Printed, never gating.
- **Location:** a `check_requirements` function inline in `up.sh` and a
  `Show-Requirements`/`Test-Requirement` section in `up.ps1`. No new shared
  files; matches each file's existing helper style.
- **Docs:** update both `README.md` and `docs/REQUIREMENTS.md` to reflect the
  new gate semantics (HF CLI now hard) and the up-front banner.

## Workflow (identical shape on all platforms)

1. **Banner** — print all requirements with live status.
2. **Verify hard gates** — Python ≥ 3.11, Node ≥ 20. Any missing → print
   actionable message + install link → `exit 1`.
3. **llama.cpp** — hand off to the existing interactive resolution flow
   (unchanged; cancel → exit).
4. **Install deps** — venv + `pip install -e '.[dev]'` (now includes
   `huggingface-hub`).
5. **HF CLI gate (venv)** — with the venv active, verify
   `hf`/`huggingface-cli` resolves; missing → exit with `pip install
   huggingface-hub`.
6. **Informational notes** — GPU, speed-bench.
7. Continue the existing startup exactly as today (`nohup`/`Start-Process`,
   logs, URLs).

## File structure

- **Modify:** `backend/pyproject.toml` — add `huggingface-hub>=0.24` to core
  `dependencies`.
- **Modify:** `up.sh` — add `check_requirements` banner + Python/Node gates +
  post-install HF CLI venv check. Keep llama.cpp sourcing and startup logic.
- **Modify:** `scripts/up.ps1` — add banner + version gates + HF CLI venv
  check. Keep all existing `Start-Process`/log/cleanup logic.
- **Docs:** `README.md` (Requirements + Workflow section),
  `docs/REQUIREMENTS.md` (HF CLI row → hard gate), this design doc, and an
  implementation plan.

## Testing

- `bash -n up.sh scripts/ensure-llama-cpp.sh` (syntax).
- PowerShell parse check on `up.ps1` (`pwsh -Command` parser, if available).
- Backend `pytest` (pyproject change is additive; must stay green).
- Frontend `tsc -b` + `vitest run`.
- Playwright `e2e` unchanged (CI self-manages via webServer; does not invoke
  `up.sh`).
- Manual smoke test of `./up.sh` recommended (starts servers; not run in
  session by default).
