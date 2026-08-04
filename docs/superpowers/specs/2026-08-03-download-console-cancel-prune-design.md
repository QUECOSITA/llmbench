# Download Console, Cancel, and Interactive Cache Prune

Date: 2026-08-03. Status: approved design.

Enhance the MODEL INPUT (01) panel so a download is watchable like a real
terminal, can be cancelled, and a cancelled download automatically triggers
`hf cache prune` whose confirmation prompt is answered interactively in the UI.

## Background

Today `POST /api/models/download` runs `hf download` as an asyncio background
job. Because stdout/stderr are plain pipes (not a TTY), the CLI resolves
`--format auto` to `agent`-style output and suppresses progress bars, so the UI
has almost nothing to show — it prints only the last `download_log` line inline.

Verified CLI behavior (hf 1.24.0):
- `hf download` in a TTY (human mode) renders tqdm progress bars using `\r`
  overwrites; in a pipe it prints only `path=...`.
- `--format auto` resolves via `is_agent()` (env vars such as `AGENT`), **not**
  the TTY, so interactive confirmation depends on the environment. Passing
  `--format human` explicitly makes behavior deterministic.
- `hf cache prune --format human` prints `About to delete N …`, then
  `Proceed? [y/N]:` and reads one line from stdin: `y` → deletes and exits 0,
  `n` → "Aborted!" exit 1, and when there is nothing to prune it prints
  `No unreferenced revisions or incomplete downloads found. Nothing to prune.`
  and exits 0 without prompting.

## Requirements

1. Clicking DOWNLOAD in the 01 · MODEL INPUT panel shows a scrolling console
   with the `hf download` output streamed live, including animated progress
   bars — as if the command were run manually in a terminal.
2. While downloading there is a CANCEL option. Cancelling kills the running
   `hf download` process.
3. After a cancel, `hf cache prune` runs automatically and the user answers
   its `y/N` prompt interactively in the UI.
4. After the prune step finishes the console stays visible with its full
   history and the Download button returns so the user can retry.

## Architecture

**Backend (FastAPI/asyncio):**
- `hf download` runs attached to a pseudo-terminal so tqdm renders progress.
  A background thread reads the pty master into an asyncio queue; an async
  consumer normalizes the byte stream and broadcasts WS events.
- A pure `TtyStream` normalizer (new module `backend/app/tty_stream.py`)
  converts raw pty bytes into "line" (newline-terminated) or "progress"
  (carriage-return overwrite) chunks, stripping ANSI escapes.
- Cancel is `POST /api/models/download/cancel`: 409 when idle; otherwise sets
  a cancelled flag and sends SIGINT to the running process.
- After cancel the same job spawns `hf cache prune --format human` with piped
  stdin, streams its output as `prune_log`, emits `prune_prompt` when it sees
  `Proceed?`, and waits on an asyncio queue for the user's answer. The answer
  is delivered by `POST /api/models/download/prune-answer` (`{answer: "y"|"n"}`)
  and written to the process stdin. `prune_done {accepted: rc==0}` closes the
  flow.
- Both commands take `--cache-dir <settings.hf_cache_dir>` when a custom cache
  is configured, so download and prune always scan the same cache.
- `_download_active` remains true through the prune phase (keeps the frontend
  WebSocket open) and is cleared in `finally`.

**Frontend (React/TypeScript):**
- `downloadReducer` (new, pure) maintains per-server-key state:
  `{status, command, lines[], waitingInput, pruneAccepted, message, local_path}`
  with statuses `downloading | downloaded | error | cancelled | pruning | pruned`.
- `DownloadConsole` component renders under the server row in section 01: the
  command header, a scrolling monospace console whose progress line updates in
  place, a CANCEL button while downloading, and a `Proceed? [y/N]` prompt with
  a text input plus y/n buttons while pruning.
- One shared console (downloads are serial; concurrent ones are rejected).

## Data / Event Flow

WS events (extend `DownloadEvent`):
- `download_started {server_id, repo_id, command}`
- `download_log {server_id, repo_id, line}` — append a finalized line.
- `download_progress {server_id, repo_id, line}` — replace the current line.
- `download_done {server_id, repo_id, status, local_path}` — unchanged.
- `download_error {server_id, repo_id, message}` — unchanged.
- `download_cancelled {server_id, repo_id}`
- `prune_started {repo_id, command}`
- `prune_log {repo_id, line}`
- `prune_prompt {repo_id}` — prune is waiting for `y`/`n`.
- `prune_done {repo_id, accepted, message}` — flow finished.

REST:
- `POST /api/models/download/cancel` → `{ok:true}`; 409 when no download is
  running.
- `POST /api/models/download/prune-answer` body `{answer: "y"|"n"}` → `{ok:true}`;
  422 for any other answer; 409 when no prune is awaiting input.

## Backend Details

### Commands

- Download: `hf download --format human <repo> [--include <glob>] [--cache-dir <dir>]`.
- Prune: `hf cache prune --format human [--cache-dir <dir>]`.

`--format human` is passed explicitly because `--format auto` is resolved from
environment variables (e.g. `AGENT=1`), not the TTY, and would suppress
progress bars / interactive confirmation in agent-like environments.

### AppState additions

- `_download_proc: asyncio.subprocess.Process | None`
- `_download_cancelled: bool`
- `_prune_proc: asyncio.subprocess.Process | None`
- `_prune_answer: asyncio.Queue[str] | None`

### TtyStream (`backend/app/tty_stream.py`)

Pure class. `feed(chunk: bytes) -> list[tuple[str, str]]` returning events
`(kind, text)` with `kind ∈ {"line", "progress"}`. Rules:
- Strip ANSI escape sequences (`\x1b[…letter`), including `\x1b[K`.
- `\r\n` and `\n` finalize the current line as a `"line"` event.
- A lone `\r` (progress overwrite) emits the current buffer as a `"progress"`
  event and clears it.
- Trim trailing whitespace from progress frames.
- Non-printable control bytes are dropped; partial UTF-8 is buffered.

### `_download_job` rewrite

```
broadcast download_started {command}
open pty (master, slave); spawn hf download with stdin/stdout/stderr = slave, start_new_session=True
close slave in parent; store _download_proc
reader thread: os.read(master) chunks -> loop.call_soon_threadsafe(queue.put_nowait)
consumer: for each chunk, TtyStream.feed -> broadcast download_log / download_progress
on EOF:
    if _download_cancelled: broadcast download_cancelled; await prune flow
    elif rc != 0: mark model missing; broadcast download_error
    else: resolve path; upsert downloaded; broadcast download_done
finally: clear _download_active, _download_proc, _download_cancelled
```

Spawn/read helpers live at module level (`_open_pty`, `_spawn_pty`,
`_read_master`) so tests can inject fakes.

### Prune flow (helper `_prune_job`)

```
cmd = ["hf", "cache", "prune", "--format", "human"] + cache-dir flag
spawn with stdin=PIPE, stdout=PIPE, stderr=STDOUT; store _prune_proc
broadcast prune_started {command}
loop read chunks; split into lines; broadcast each as prune_log
  when buffer contains "Proceed?" and no prompt sent:
      broadcast prune_prompt
      _prune_answer = asyncio.Queue()
      answer = await _prune_answer.get()
      write (answer + "\n") to stdin
on EOF: rc = await proc.wait(); broadcast prune_done {accepted: rc == 0, message: last line}
finally: clear _prune_proc, _prune_answer
```

Edge cases:
- Nothing to prune → no `Proceed?`, prune exits 0 → `prune_done {accepted: true}`
  with no prompt; the UI must not block.
- `n` → click aborts, exit 1 → `prune_done {accepted: false}`.
- No WS clients or answer never arrives → prune stays blocked on stdin (accepted
  limitation; the flow is user-driven).

### Endpoints

- `POST /api/models/download/cancel`: if not `_download_active` → 409. Else set
  `_download_cancelled = True`, `proc.send_signal(SIGINT)`, return `{ok:true}`.
- `POST /api/models/download/prune-answer`: if `_prune_answer is None` → 409.
  Validate `answer in ("y", "n")` else 422. `await _prune_answer.put(answer)`.

## Frontend Details

### `downloadReducer` (`frontend/src/ws/downloadReducer.ts`)

`DownloadStatus`:
```ts
interface DownloadStatus {
  status: "downloading" | "downloaded" | "error" | "cancelled" | "pruning" | "pruned";
  command: string;
  lines: string[];
  waitingInput: boolean;
  pruneAccepted: boolean | null;
  message?: string;
  local_path?: string;
}
```

Reducer mapping (by `server_id::repo_id` key):
- `download_started` → `downloading`, set `command`, reset `lines`.
- `download_log` → append `line`.
- `download_progress` → replace `lines[last]`.
- `download_done` → `downloaded` + `local_path`.
- `download_error` → `error` + `message`.
- `download_cancelled` → `cancelled` (console kept).
- `prune_started` → `pruning`.
- `prune_log` → append.
- `prune_prompt` → `waitingInput: true`.
- `prune_done` → `pruned`, `pruneAccepted`, `waitingInput: false`.

### `DownloadConsole` component

Props: `{status, command, lines, waitingInput, pruneAccepted, message, local_path,
onCancel, onPruneAnswer}`. Renders:
- Header: `$ {command}`.
- Scrollable `<pre>` console; autoscrolls to bottom; the live progress line
  updates in place.
- CANCEL button while `status === "downloading"`.
- Prompt row while `waitingInput`: `hf cache prune — Proceed? [y/N]` plus a text
  input and `y` / `n` buttons.
- Terminal state lines: `downloaded` (+ path), `cancelled · pruned` (or
  `pruned · nothing to delete`), or the error message.

Style: flat inset panel (hairline border, `--panel` background), monospace, dim
anode label; CANCEL is a neutral bordered button (the orange accent stays
reserved for the one lit figure per the design system).

### App wiring

- Replace `downloads` state with `downloadReducer`.
- `downloadActive` = any status in `{"downloading", "pruning"}`.
- Add `cancelDownload` and `answerPrune` to `frontend/src/api/client.ts`.
- Section 01: keep the per-server button row; render the shared
  `DownloadConsole` beneath it when a flow is active/finished for the analyzed
  repo. After `download_done` refresh `downloaded` list (existing behavior).

## Testing

Backend (`backend/tests/`):
- `test_tty_stream.py`: ANSI stripping, `\n` lines, `\r` progress overwrite,
  `\r\n`, trailing whitespace, control bytes, partial UTF-8.
- `test_api.py` additions:
  - `_download_command` includes `--format human` and `--cache-dir` when given.
  - cancel: 409 when idle; SIGINT on the stored process when active.
  - cancel flow: download job with a cancelled flag emits `download_cancelled`
    and then runs prune (fake subprocesses).
  - prune flow: fake `hf cache prune` that prints the summary + `Proceed?`,
    blocks on stdin, then exits per the fed answer — assert `prune_prompt`,
    then `POST /prune-answer` with `y` → `prune_done {accepted: true}`, and
    with `n` → `{accepted: false}`.
  - nothing-to-prune: prune exits 0 with no prompt → `prune_done {accepted: true}`.
  - `prune-answer` 422 for bad answer, 409 when no prune waiting.
  - existing download success/duplicate tests updated for the new command shape
    and event stream.

Frontend (`frontend/src/`):
- `downloadReducer.test.ts`: each event mapping incl. progress overwrite and
  the full cancel→prune sequence.
- `DownloadConsole.test.tsx`: renders lines + command; CANCEL calls `onCancel`;
  y/N prompt calls `onPruneAnswer`; autoscroll presence.
- `App.test.tsx`: update the existing download test for the console; add a
  cancel flow test (download → CANCEL → prune prompt → answer).
- e2e `mock-server.ts`: add `/api/models/download/cancel` and
  `/api/models/download/prune-answer`; extend `flow.spec.ts` with a console
  + cancel + prune assertion.

## Out of Scope

- Pausing/resuming a download.
- Running multiple concurrent downloads (unchanged: rejected with 409).
- A full terminal emulator / xterm.js.
- Automatic prune confirmation (the user always decides `y`/`n`).
