# Follow-ups: fit verdict banner + real HF CLI download job

Date: 2026-08-02. Status: approved design.

These are the two documented follow-ups from the llmbench implementation plan's
Self-Review, plus finishing the `feature/llmbench` branch.

## 1. Fit verdict warning banner

Surface the hardware-fit computation (`backend/app/fit.py::fit_verdict`) in the
analyze panel so users see when a model may not fit in available VRAM/RAM.

### Backend

- `POST /api/models/analyze` already returns `weights_bytes` (sum of weights
  file sizes from the HF repo tree). Add:
  - call `detect_hardware()` (already imported in `api.py`);
  - compute `fit_verdict(weights_bytes, hw["gpu_vram_gb"], hw["ram_total_gb"])`;
  - add `fit_verdict` and `hardware` keys to the response:
    `fit_verdict: {stage, warning, needed_gb}` and
    `hardware: {gpu_vram_gb, ram_total_gb, gpu_name}`.

### Frontend

- `frontend/src/api/client.ts`: extend `Analysis` with optional
  `fit_verdict?: {stage: string; warning: boolean; needed_gb: number}` and
  `hardware?: {gpu_vram_gb?: number; ram_total_gb?: number; gpu_name?: string}`.
  `App.tsx` declares a second, shape-identical `Analysis` interface for its
  state — add the same two optional fields there (or consolidate onto the
  client type during implementation, whichever is cleaner).
- `frontend/src/App.tsx`, MODEL INPUT panel: under the existing analysis summary
  line (`→ repo_id · server N flags`), when `analysis.fit_verdict?.warning` is
  true render one accent-colored line:
  `headroom tight — model needs ~X GB (weights + KV cache), available Y GB VRAM + Z GB RAM`.
  Hidden when warning is false or absent.

### Tests

- Backend: extend `backend/tests/test_api.py` — analyze response includes
  `fit_verdict` with `warning` boolean and `needed_gb`, plus `hardware`.
- Frontend: App unit test asserts the banner renders when
  `fit_verdict.warning === true` and is absent when `false`.

## 2. Real HF CLI download job

Replace the stubbed `download_command` with an actual background download that
runs `hf download` and streams progress over WebSocket.

### Backend

- New endpoint `POST /api/models/download`, body
  `{repo_id, server_id, gguf_filename?}`.
  - `repo_id` and `server_id` required; `server_id` must be one of the known
    servers (`llama.cpp`, `vllm`, `sglang`). 422 otherwise.
  - Command:
    - vllm / sglang: `hf download <repo_id>`
    - llama.cpp: `hf download <repo_id> --include "*.gguf"`
  - If `shutil.which("hf")` is None → 400 with the exact manual command in the
    error message (no fallback to `huggingface-cli`).
  - Guard with a `_download_active` flag parallel to `_job_active`; a second
    concurrent download → 409.
- Background download task (via `asyncio.create_task`):
  1. broadcast `download_started {server_id, repo_id, command}`;
  2. run `asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=STDOUT)`;
  3. read output lines and broadcast `download_log {server_id, repo_id, line}`;
  4. on exit 0:
     - resolve `local_path`:
       - vllm / sglang: HF cache snapshot dir
         `~/.cache/huggingface/hub/models--{org}--{name}` (or
         `settings.hf_cache_dir` when set);
       - llama.cpp: first `*.gguf` in `settings.resolved_gguf_dir` (or the
         file matching `gguf_filename` when provided).
     - upsert model row status `downloaded` with `local_path`,
       `downloaded_at`, and `size_bytes` (file stat for llama.cpp; None for HF
       cache dirs).
     - broadcast `download_done {server_id, repo_id, status: "downloaded", local_path}`.
  5. on non-zero exit: upsert status `missing`, broadcast
     `download_error {server_id, repo_id, message}`.
  6. `finally`: clear `_download_active`.

### Frontend

- `frontend/src/api/client.ts`: add
  `downloadModel({repo_id, server_id, gguf_filename?})` → `POST /models/download`
  returning `{ok: true}`.
- New hook `frontend/src/ws/useDownloadProgress.ts`: same connection pattern as
  `useBenchmarkProgress`, returns `DownloadEvent[]` for types
  `download_started | download_log | download_done | download_error`.
- `frontend/src/App.tsx`:
  - state `downloads: Record<string, DownloadStatus>` keyed
    `"{server_id}::{repo_id}"`, `DownloadStatus = {status: "downloading"|"downloaded"|"error", line?, message?}`.
  - `onDownload(serverId)`: set that key to `downloading`; `await
    api.downloadModel(...)`; on success dispatch a local
    `download_started` (mirrors the benchmark `run_started` pattern so the UI
    is correct even if a WS event arrives first); on failure set `error`.
  - `useEffect` over `useDownloadProgress(anyDownloadActive)`: apply
    `download_log` → `line`; `download_done` → `downloaded` + refresh
    `listModels()`; `download_error` → `error` + message.
  - MODEL INPUT panel: when `analysis.repo_id` is set, render one row per
    known server under the summary. Each row: server label + Download button
    when not downloaded; status text (latest log line or "downloaded") while
    active; error text on failure. Hidden for servers already downloaded
    (    from `analysis.downloaded`). The known-server set is exactly
    (`llama.cpp`, `vllm`, `sglang`), matching the backend `_model_status`.

### Tests

- Backend (`test_api.py`):
  - CLI missing: monkeypatch `shutil.which("hf")` → None; assert 400 and
    message contains `hf download <repo_id>`.
  - Success path with a fake quick command (e.g. `shutil.which` → a tiny
    shell script or `true`): assert model row status `downloaded`, `local_path`
    resolved, `download_done` broadcast. Use a temp `data_dir` so the HF cache
    / GGUF dir are hermetic.
  - 409 when a download is already active.
- Frontend:
  - App unit test: click Download → row shows "downloading"; then a mocked
    `download_done` → row shows "downloaded" and `api.listModels` was re-fetched.
  - `useDownloadProgress` unit test: returns download events.

## 3. Finish the branch

After all tests are green (backend pytest, frontend vitest + build + e2e),
use the finishing-a-development-branch skill to integrate `feature/llmbench`
into `master` (no remote configured; local merge or squash as the skill
recommends).

## Out of scope

- `gguf_filename` picker UI for multi-GGUF llama.cpp repos (download uses
  `--include "*.gguf"` and auto-detects the first file). Documented as a
  follow-up if needed.
- Download cancellation, resume, or retry.
- Surfacing `fit_verdict` anywhere other than the MODEL INPUT panel.
