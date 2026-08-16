# Agent Instructions

## Starting and Stopping the App

- To start the backend or frontend, always run `./up.sh`.
- To stop the backend or frontend, always run `./down.sh`.
- Do not start uvicorn, the frontend dev server, or any related process with ad-hoc commands instead of `up.sh`, and do not stop them with ad-hoc `pkill`/kill commands instead of `down.sh`.

## Context Compaction

- When the conversation reaches 128k context, execute the `compact` skill.
- After compaction completes, continue with the process you were doing before compacting.

## Safe Developing Workflow

1. **Start of the Day (Get the Latest Code)** — Before writing code, fetch the latest updates from remote.
   - `git checkout main`
   - `git pull`
2. **Making Changes (Work Safely on a Branch)** — Never write code directly on `main`.
   - `git checkout -b feature/my-new-task`
3. **Checking Your Work**
   - `git status` — inspect changed or created files
   - `git diff` — review exact code changes for mistakes
4. **Local Verification (Mandatory Before Staging)**
   - Run the full local check suite (Backend `pytest`, Frontend `tsc -b` + `vitest run`, and Playwright `e2e`).
   - Fix any failing tests or compilation errors before proceeding.
5. **Saving Your Work**
   - `git add <specific-files>` — avoid broad `git add .` to prevent committing stray logs or local caches.
   - `git commit -m "feat: short explanation of change"` — write clean, descriptive commit messages.
6. **Sharing Your Work & Opening PR**
   - `git push origin feature/my-new-task`
   - Create a Pull Request against `main`.

## Merge Authorization (non-negotiable)

- NEVER auto-merge a Pull Request on GitHub (via `gh`, the GitHub API, or any agent harness: opencode, Claude, Codex, pi, etc.) without an EXPLICIT user order in the prompt.
- An order to merge MUST contain the literal word "merge" (e.g. "merge the PR", "merge feature/x into main").
- "go", "continue", "approved", "finish", "ship", "integrate" or any other synonym NEVER authorize a merge. At most they authorize suggesting the merge and waiting for the user to say "merge".
- After CI and security scans pass, still DO NOT merge — present the merge as a suggestion and wait for the user's explicit "merge" instruction.

## Security Scanning (Merge Gate)

This repository is actively scanned through:
- Security advisories
- Private vulnerability reporting
- Dependabot alerts
- Code scanning alerts
- Secret scanning alerts

Before merging any PR:
- Wait at least 3 minutes for GitHub security-tool scans and CI checks to finish on the PR.
- Check GitHub / repository alerts for any new vulnerabilities introduced.
- If any alert is found, create a new plan using the `using-superpowers` skill to fix them before merging.

## CI/CD

- Any push to any branch or PR against the GitHub remote (`QUECOSITA/llmbench`) runs `.github/workflows/ci.yml`.
- CI mirrors local checks: backend `pytest`, frontend `tsc -b` + `vitest run`, and Playwright e2e.
- E2E in CI uses Playwright's `webServer` to self-manage the vite dev server and mock-server; it does not need the real backend or HF CLI. The `./up.sh`/`./down.sh` commands are for local development only, not CI.
- When e2e depends on the mock-server (`.tsx`), keep `tsx` in `frontend` devDependencies so `npx tsx e2e/mock-server.ts` resolves in CI.

## Safety Rules (non-negotiable)

- DO NOT BREAK THE CODE! DON'T YOU DARE TO!
- I DO NOT ACCEPT MISTAKES THAT WERE ALREADY FIXED.
- ANY CHANGE MUST BE SAFE AND NON-DESTRUCTIVE. NEVER WIPE OR DOWNGRADE EXISTING USER DATA.
- ALWAYS USE CI/CD: run the full local suite before finishing — backend `pytest`, frontend `tsc -b` + `vitest run`, Playwright `e2e`.
- When told "go"/"continue"/"approved" (or any synonym), STILL proceed in SAFE MODE: unit tests → CI checks → then integrate.
- If an order could break the workflow or user data, be HIGHLY EXPLICIT about the threat BEFORE executing, and confirm first.
- When downloading any repo/file, ALWAYS also bring README.md so the workflow can use it.
- Before touching reconcile/sync/download logic, verify against the real on-disk state (~/.llmbench, HF cache).
