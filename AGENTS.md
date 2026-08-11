# Agent Instructions

## Starting and Stopping the App

- To start the backend or frontend, always run `./up.sh`.
- To stop the backend or frontend, always run `./down.sh`.
- Do not start uvicorn, the frontend dev server, or any related process with ad-hoc commands instead of `up.sh`, and do not stop them with ad-hoc `pkill`/kill commands instead of `down.sh`.

## Context Compaction

- When the conversation reaches 128k context, execute the `compact` skill.
- After compaction completes, continue with the process you were doing before compacting.

## Safe Developing Workflow

1. **Start of the Day (Get the Latest Code)** — Before you write any code, grab the latest updates that your teammates might have uploaded.
   - `git checkout main` — switch to your main codebase
   - `git pull` — download and merge the newest changes to your computer
2. **Making Changes (Work Safely on a Branch)** — Never write code directly on the main project line. Always create a separate workspace called a branch.
   - `git checkout -b feature/my-new-task` — create and switch to a brand new branch
3. **Checking Your Work (See What Changed)** — As you write code, see which files you modified and check for mistakes.
   - `git status` — shows a list of files you changed or created
   - `git diff` — shows the exact lines of code you added or deleted
4. **Saving Your Work (The Daily Save Point)** — When your new code is working, save a snapshot of it.
   - `git add .` — gathers all your changed files and gets them ready to save
   - `git commit -m "Fix login button bug"` — saves the changes with a short note explaining what you did
5. **Sharing Your Work (Send to GitHub)** — Finally, send your saved work from your computer up to the GitHub website.
   - `git push origin feature/my-new-task` — uploads your branch to GitHub

## Security Scanning (Merge Gate)

This repository is actively scanned through the following settings/tools:
- Security advisories — Enabled
- Private vulnerability reporting — Enabled
- Dependabot alerts — Enabled
- Code scanning alerts — Enabled
- Secret scanning alerts — Enabled

Before any merge:
- Wait at least 3 minutes for the security-tool scans to finish.
- Always check for any existing alert.
- If any alert is found, create a new plan using the `using-superpowers` skill to fix them.

## CI/CD

- Any push to any branch or any pull request against the GitHub remote (`QUECOSITA/llmbench`) runs the CI workflow (`.github/workflows/ci.yml`).
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
