# Agent Instructions

## Starting and Stopping the App

- To start the backend or frontend, always run `./up.sh`.
- To stop the backend or frontend, always run `./down.sh`.
- Do not start uvicorn, the frontend dev server, or any related process with ad-hoc commands instead of `up.sh`, and do not stop them with ad-hoc `pkill`/kill commands instead of `down.sh`.

## Context Compaction

- When the conversation reaches 128k context, execute the `compact` skill.
- After compaction completes, continue with the process you were doing before compacting.

## CI/CD

- Any push to any branch or any pull request against the GitHub remote (`QUECOSITA/llmbench`) runs the CI workflow (`.github/workflows/ci.yml`).
- CI mirrors local checks: backend `pytest`, frontend `tsc -b` + `vitest run`, and Playwright e2e.
- E2E in CI uses Playwright's `webServer` to self-manage the vite dev server and mock-server; it does not need the real backend or HF CLI. The `./up.sh`/`./down.sh` commands are for local development only, not CI.
- When e2e depends on the mock-server (`.tsx`), keep `tsx` in `frontend` devDependencies so `npx tsx e2e/mock-server.ts` resolves in CI.
