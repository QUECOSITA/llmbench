# Agentic Session Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live, structured **Agentic Session Panel** under the metrics in `RunPanel` that shows everything the agent harness produces during an agentic bench run — prompts, model thinking/output, tool execution, loop iterations, plan submissions/revisions, and the branch (tool) the model actually selected each step.

**Architecture:** Extend `run_agent_session` (`backend/app/agentic.py`) to emit structured, parseable text blocks through the existing `on_output` callback, which already streams live to the frontend via the `bench_log` WS event into `ProgressState.lines`. A new `AgenticSessionPanel` component (rendered in `RunPanel`) parses those lines into a collapsible, auto-scrolling timeline. Live only — **no DB persistence, no migration.**

**Tech Stack:** Python 3.11+ / asyncio / httpx · React 18 / TypeScript / Vitest / Playwright.

---

## File Structure

| File | Change |
|---|---|
| `backend/app/agentic.py` | Extend `run_agent_session` to emit structured per-step lines via `on_output`; add `_emit_lines` helper |
| `backend/tests/test_agentic.py` | Add tests asserting emitted lines (step/branch/tool/result/finish) |
| `frontend/src/components/AgenticSessionPanel.tsx` | **Create** — parses `lines` into a timeline; collapsible + auto-scroll |
| `frontend/src/components/AgenticSessionPanel.test.tsx` | **Create** — tests for the new component |
| `frontend/src/components/RunPanel.tsx` | Render `<AgenticSessionPanel lines={lines} />` under `AgenticDetailStrip` |
| `frontend/src/styles/app.css` | Add session-panel styling classes |

---

## Emitted line format (contract between backend and frontend)

Each emitted line starts with a keyword prefix. The frontend panel classifies by prefix:

| Prefix | Meaning | Example |
|---|---|---|
| `── step N/M ──` | loop-iteration header | `── step 1/10 ──` |
| `PROMPT` | the task prompt sent this step | `PROMPT Analyze the codebase in /repo...` |
| `CHOICE` | the `tool_choice` used | `CHOICE forced submit_plan` / `CHOICE auto` |
| `THINK` | the model's returned `content` (or `(tool call only)`) | `THINK I will read the main file first.` |
| `BRANCH` | which tool the model selected | `BRANCH → read_file` |
| `TOOL` | tool name + args | `TOOL read_file({"path": "/repo/main.py"})` |
| `RESULT` | truncated tool result | `RESULT import time...` |
| `PLAN` | plan submitted or revised + steps | `PLAN submitted: ["a","b"]` / `PLAN revised: [...]` |
| `FINISH` | early finish + answer | `FINISH ok` |
| `BUDGET` | budget exhausted | `BUDGET exhausted after N steps` |
| `step N/M: prompt ... tok + ... tok in ...s` | per-step throughput (existing, unchanged) | `step 1/10: prompt 120 tok + 40 tok in 2.1s` |

The frontend treats lines that don't match a known prefix as plain text (rendered as-is), so the panel degrades gracefully for non-agentic benches and server logs.

---

## Task 1: Emit structured session lines in the harness (TDD)

**Files:**
- Modify: `backend/app/agentic.py`
- Test: `backend/tests/test_agentic.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_agentic.py`:

```python
def _capture_output():
    lines = []

    async def on_output(kind, text):
        lines.append(text)

    return lines, on_output


@pytest.mark.asyncio
async def test_run_agent_session_emits_structured_step_lines(monkeypatch):
    monkeypatch.setattr("app.agentic.time.monotonic", FakeClock())
    lines, on_output = _capture_output()
    transport = httpx.MockTransport(_plan_handler([]))
    await run_agent_session(
        base_url="http://127.0.0.1:9", model="m", steps=10, max_tokens=4096,
        task="codebase_refactor", on_output=on_output, transport=transport)
    joined = "\n".join(lines)
    assert "── step 1/10 ──" in joined
    assert "CHOICE forced submit_plan" in joined
    assert "PLAN submitted" in joined
    assert "BRANCH → read_file" in joined
    assert "TOOL read_file" in joined
    assert "RESULT" in joined
    assert "FINISH" in joined


@pytest.mark.asyncio
async def test_run_agent_session_emits_budget_exhausted(monkeypatch):
    monkeypatch.setattr("app.agentic.time.monotonic", FakeClock())

    def handler(request):
        return httpx.Response(200, json=_resp(
            {"role": "assistant", "content": None,
             "tool_calls": [_tool_call("read_file", {"path": "a.py"})]}))

    lines, on_output = _capture_output()
    transport = httpx.MockTransport(handler)
    await run_agent_session(
        base_url="http://127.0.0.1:9", model="m", steps=2, max_tokens=4096,
        task="codebase_refactor", on_output=on_output, transport=transport)
    joined = "\n".join(lines)
    assert "BUDGET exhausted after 2 steps" in joined


@pytest.mark.asyncio
async def test_run_agent_session_emits_thinking_and_branch(monkeypatch):
    monkeypatch.setattr("app.agentic.time.monotonic", FakeClock())

    def handler(request):
        body = json.loads(request.content)
        if body.get("tool_choice") == {"type": "function", "function": {"name": "submit_plan"}}:
            msg = {"role": "assistant", "content": "I will make a plan",
                   "tool_calls": [_tool_call("submit_plan", {"steps": ["a"]})]}
        else:
            msg = {"role": "assistant", "content": "Let me read a file",
                   "tool_calls": [_tool_call("read_file", {"path": "/repo/main.py"})]}
        return httpx.Response(200, json=_resp(msg))

    lines, on_output = _capture_output()
    transport = httpx.MockTransport(handler)
    await run_agent_session(
        base_url="http://127.0.0.1:9", model="m", steps=3, max_tokens=4096,
        task="codebase_refactor", on_output=on_output, transport=transport)
    joined = "\n".join(lines)
    assert "THINK I will make a plan" in joined
    assert "THINK Let me read a file" in joined
    assert "BRANCH → read_file" in joined
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_agentic.py -k emits -v`
Expected: FAIL — the new structured prefixes (`── step`, `CHOICE`, `THINK`, `BRANCH`, `TOOL`, `RESULT`, `PLAN`, `FINISH`, `BUDGET`) are not emitted.

- [ ] **Step 3: Implement the emission logic**

In `backend/app/agentic.py`:

1. Add a module-level helper near the top of the tool-result helpers (e.g. after `_tool_result`):

```python
def _emit_lines(on_output, *lines: str) -> None:
    """Await on_output for each line, skipping empty/None entries."""
    if on_output is None:
        return
    for line in lines:
        if line:
            on_output("line", line)
```

2. In `run_agent_session`, at the top of the function body (after the `transcript = []` init, before the `async with` loop), add an `emit` alias so we can call it synchronously without repeating the guard:

```python
    def emit(*lines: str) -> None:
        _emit_lines(on_output, *lines)
```

3. Inside the `while step < steps:` loop, after computing `step` and the `body` dict, emit the step header + prompt + choice. Add just before the `start = time.monotonic()` line (after the `body` is built):

```python
            choice = "forced submit_plan" if step == 1 else "auto"
            emit(f"── step {step}/{steps} ──",
                 f"CHOICE {choice}",
                 f"PROMPT {messages[-1]['content']}")
```

4. After the API call and message handling, replace the existing `on_output("line", ...)` block (lines ~318-321) so it emits the full per-step detail before the throughput line. The block becomes:

```python
            if calls:
                branch = calls[0].get("function") or {}
                emit(f"BRANCH → {branch.get('name', '?')}")
                for call in calls:
                    fn = call.get("function") or {}
                    name = fn.get("name") or ""
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    if name == "finish":
                        emit("FINISH " + str(args.get("answer", "")))
                    elif name == "submit_plan":
                        plan_kind = "PLAN submitted" if step == 1 else "PLAN revised"
                        emit(f"{plan_kind}: {json.dumps(args.get('steps', []))}")
                    else:
                        result = _tool_result(name, args, corpus)
                        emit(f"TOOL {name}({json.dumps(args)})",
                             f"RESULT {result[:200]}")
            else:
                emit("THINK " + (content or "(tool call only)")[:200])
            emit(f"step {step}/{steps}: prompt {p_tok} tok + {c_tok} tok in {elapsed:.1f}s")
```

   Then remove the now-duplicated loop that appended `_tool_result` results to `transcript` **and** the old `on_output` block, consolidating so results are emitted once. Keep the `transcript` population for the existing tool-call lines (the detail strip / metrics still use `transcript`? — note: `transcript` is only used for nothing user-facing today; keep it as-is for backward compatibility). Also move the `finished` handling so it still breaks the loop.

> To keep the change minimal and non-destructive, keep the existing `transcript` appends (they are harmless) and simply ADD the `emit(...)` calls. Do not delete existing behavior.

5. After the `while` loop ends (before the final `if latencies_ms:` block), emit the terminal state if not already emitted via `FINISH`:

```python
    if not finished:
        emit(f"BUDGET exhausted after {step} steps")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_agentic.py -v`
Expected: PASS — all existing tests plus the 3 new `emits` tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agentic.py backend/tests/test_agentic.py
git commit -m "feat: emit structured session lines from agentic harness"
```

---

## Task 2: AgenticSessionPanel component (TDD)

**Files:**
- Create: `frontend/src/components/AgenticSessionPanel.tsx`
- Create: `frontend/src/components/AgenticSessionPanel.test.tsx`

- [ ] **Step 1: Write the failing component test**

Create `frontend/src/components/AgenticSessionPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { AgenticSessionPanel } from "./AgenticSessionPanel";

const sampleLines = [
  "── step 1/10 ──",
  "CHOICE forced submit_plan",
  "PROMPT Analyze the codebase in /repo.",
  "THINK I will read the main file.",
  "BRANCH → submit_plan",
  "PLAN submitted: [\"a\", \"b\"]",
  "step 1/10: prompt 120 tok + 40 tok in 2.1s",
  "── step 2/10 ──",
  "CHOICE auto",
  "THINK (tool call only)",
  "BRANCH → read_file",
  "TOOL read_file({\"path\": \"/repo/main.py\"})",
  "RESULT import time",
];

test("renders nothing when there are no lines", () => {
  const { container } = render(<AgenticSessionPanel lines={[]} />);
  expect(container.textContent).toBe("");
});

test("renders step headers, choices, thinking, branches, and tool results", () => {
  render(<AgenticSessionPanel lines={sampleLines} />);
  expect(screen.getByText(/step 1\/10/i)).toBeInTheDocument();
  expect(screen.getByText(/forced submit_plan/i)).toBeInTheDocument();
  expect(screen.getByText(/I will read the main file/i)).toBeInTheDocument();
  expect(screen.getByText(/→ read_file/i)).toBeInTheDocument();
  expect(screen.getByText(/read_file\(\{\"path\"/i)).toBeInTheDocument();
  expect(screen.getByText(/import time/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/components/AgenticSessionPanel.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/AgenticSessionPanel.tsx`:

```tsx
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

type LineKind =
  | "step"
  | "choice"
  | "prompt"
  | "think"
  | "branch"
  | "tool"
  | "result"
  | "plan"
  | "finish"
  | "budget"
  | "plain";

function classify(line: string): { kind: LineKind; text: string } {
  if (/^── step \d+\/\d+ ──$/.test(line)) return { kind: "step", text: line };
  if (line.startsWith("CHOICE ")) return { kind: "choice", text: line.slice(7) };
  if (line.startsWith("PROMPT ")) return { kind: "prompt", text: line.slice(7) };
  if (line.startsWith("THINK ")) return { kind: "think", text: line.slice(6) };
  if (line.startsWith("BRANCH ")) return { kind: "branch", text: line.slice(7) };
  if (line.startsWith("TOOL ")) return { kind: "tool", text: line.slice(5) };
  if (line.startsWith("RESULT ")) return { kind: "result", text: line.slice(7) };
  if (line.startsWith("PLAN ")) return { kind: "plan", text: line.slice(5) };
  if (line.startsWith("FINISH ")) return { kind: "finish", text: line.slice(7) };
  if (line.startsWith("BUDGET ")) return { kind: "budget", text: line.slice(7) };
  return { kind: "plain", text: line };
}

export function AgenticSessionPanel({ lines }: { lines: string[] }) {
  const { t } = useTranslation();
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  if (lines.length === 0) return null;

  return (
    <div className="agentic-session">
      <div className="agentic-session-head">{t("panel.agenticSession")}</div>
      <div className="agentic-session-body" ref={boxRef}>
        {lines.map((line, i) => {
          const { kind, text } = classify(line);
          return (
            <div key={i} className={`agentic-line agentic-${kind}`}>
              <span className="agentic-tag">{kind}</span>
              <span className="agentic-text">{text}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

Add the i18n key. In `frontend/src/i18n/locales/en/translation.json`, add under `"panel"`:

```json
"agenticSession": "AGENTIC SESSION"
```

Add the same key to the `panel` object in the other 14 locale files (`zh, ja, de, fr, es, ko, ar, pt, it, nl, sv, no, da, fi`), using the English string as placeholder (existing i18n convention allows English fallback).

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/AgenticSessionPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AgenticSessionPanel.tsx frontend/src/components/AgenticSessionPanel.test.tsx frontend/src/i18n/locales/
git commit -m "feat: add AgenticSessionPanel timeline component"
```

---

## Task 3: Wire the panel into RunPanel + styling

**Files:**
- Modify: `frontend/src/components/RunPanel.tsx`
- Modify: `frontend/src/styles/app.css`

- [ ] **Step 1: Render the panel in RunPanel**

In `frontend/src/components/RunPanel.tsx`, add the import and render the panel under `AgenticDetailStrip` (after the `</AgenticDetailStrip>` element, before the existing `{lines.length > 0 && (<div className="dl-console">...)}` block):

```tsx
import { AgenticSessionPanel } from "./AgenticSessionPanel";
```

```tsx
      <AgenticSessionPanel lines={lines} />
```

Place it directly after the `AgenticDetailStrip` element (around line 69).

- [ ] **Step 2: Add styling classes**

Append to `frontend/src/styles/app.css`:

```css
.agentic-session {
  border: 1px solid var(--rule-bright);
  border-radius: var(--radius);
  background: var(--panel);
  margin-top: 10px;
  padding: 8px;
  font-size: 12px;
}
.agentic-session-head {
  color: var(--anode);
  letter-spacing: .04em;
  margin-bottom: 6px;
}
.agentic-session-body {
  max-height: 240px;
  overflow-y: auto;
  padding: 6px;
  background: var(--steel);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--tube);
}
.agentic-line { display: flex; gap: 8px; align-items: baseline; }
.agentic-tag {
  flex: 0 0 64px;
  color: var(--anode);
  text-transform: uppercase;
  letter-spacing: .06em;
  font-size: 10px;
}
.agentic-step .agentic-tag, .agentic-step .agentic-text { color: var(--accent); }
.agentic-branch .agentic-tag { color: var(--warn); }
.agentic-tool .agentic-tag { color: var(--ok); }
.agentic-finish .agentic-tag, .agentic-budget .agentic-tag { color: var(--accent); }
.agentic-result .agentic-text { opacity: .8; }
```

- [ ] **Step 3: Verify frontend typecheck + unit tests**

Run: `cd frontend && npx tsc -b && npx vitest run`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/RunPanel.tsx frontend/src/styles/app.css
git commit -m "feat: surface agentic session panel in run panel"
```

---

## Verification (per AGENTS.md — mandatory before staging)

- [ ] Backend: `cd backend && python -m pytest`
- [ ] Frontend typecheck + unit: `cd frontend && npx tsc -b && npx vitest run`
- [ ] E2E: `cd frontend && npx playwright test` (webServer self-manages the mock-server; no real backend/HF needed)

## Execution Handoff

Open a new session in this repo, then run one of:

- **Subagent-Driven (recommended):** load `superpowers:subagent-driven-development` and execute `docs/superpowers/plans/2026-08-19-agentic-session-panel.md` task-by-task.
- **Inline Execution:** load `superpowers:executing-plans` and run the plan with batch checkpoints.

---

## Notes

- Live only — no DB migration; the `config_done` result dict and `save_result` are untouched.
- The existing per-step throughput line (`step n/N: prompt ...`) is preserved and emitted after the detail lines for each step.
- `_tool_result` already bounds content to 4000 chars; emitted `RESULT` lines are truncated to 200 chars and `THINK` to 200 chars to keep WS payloads bounded.
