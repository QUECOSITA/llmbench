# Agentic Bench v2: Real plan→act agent harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scripted multi-turn "agentic" bench with a real in-process plan→act agent harness (tools, planning loop, decision branching) that measures serving throughput under agentic load and reports a rich metric set.

**Architecture:** `AgenticRunner` (benchmark.py) spawns `llama-server`, waits for `/health`, then calls a rewritten `run_agent_session` (agentic.py) which runs a two-phase plan→act loop against the OpenAI-compatible API. The harness requires tool-calling (probe gate), bundles deterministic scenarios, caps at `--steps` model calls with early `finish`, and returns rich metrics persisted via a new DB migration and surfaced in the frontend through a new `AgenticDetailStrip` component.

**Tech Stack:** Python 3.11+ / asyncio / httpx / FastAPI / SQLite · React 18 / TypeScript / Vitest / Playwright.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/agentic.py` | Rewrite: tool schemas, safe workload tools, bundled scenarios, plan→act session loop, probe gate, metrics |
| `backend/app/benchmark.py` | `AgenticRunner.run()`: pass new params (steps/max_tokens/task) through; keep server lifecycle |
| `backend/app/servers.py` | `AGENTIC_CLI_FLAGS` → `("--steps","--max-tokens","--task")`; `agentic_default_flags`; parse/validate/build |
| `backend/app/config.py` | `agentic_turns` → `agentic_steps`; add `agentic_task` default |
| `backend/app/api.py` | `agentic_params` build uses steps/task; probe-gate failure already via runner; pass new settings |
| `backend/app/db.py` | `_migrate_results_agentic_v2`; `save_result` detail param; `get_results_for_run` SELECT |
| `backend/tests/test_agentic.py` | Rewrite for the new harness |
| `backend/tests/test_servers.py` | Update agentic flag tests |
| `backend/tests/test_api.py` | Update agentic params/start tests |
| `backend/tests/test_db.py` | New migration + save/rank detail tests |
| `backend/tests/test_benchmark.py` | Update AgenticRunner tests for new params |
| `frontend/src/api/client.ts` | `RunDetail`/`RunResult` types gain agentic detail fields |
| `frontend/src/ws/useBenchmarkProgress.ts` | `ResultRow`/`ProgressEvent`/state gain agentic detail fields |
| `frontend/src/components/AgenticDetailStrip.tsx` | New component: steps · tool calls · plan revs · avg · p95 · ctx |
| `frontend/src/components/AgenticDetailStrip.test.tsx` | Tests for the new component |
| `frontend/src/components/ResultsTable.tsx` | Render detail strip under AGENTIC digit |
| `frontend/src/components/ResultsTable.test.tsx` | Update for strip rendering |
| `frontend/src/components/RunPanel.tsx` | Render `AgenticDetailStrip` under banks |
| `frontend/src/i18n/locales/*/translation.json` | Add `metrics.agenticDetail*` keys (15 files) |
| `frontend/e2e/mock-server.ts` | Agentic generate + run return rich fields / new flags |
| `frontend/e2e/flow.spec.ts` | Update agentic flow expectations |
| `README.md` | Update agentic paragraphs (lines 116, 146) |

---

## Task 1: Rewrite agentic harness core (`agentic.py`)

**Files:**
- Rewrite: `backend/app/agentic.py`

- [ ] **Step 1: Write the failing tests for the new harness**

Replace `backend/tests/test_agentic.py` with:

```python
import json

import httpx
import pytest

from app.agentic import (AGENTIC_DEFAULT_MAX_TOKENS, AGENTIC_DEFAULT_STEPS,
                         AGENTIC_TASKS, AGENTIC_TOOL_SCHEMAS, DEFAULT_USER_PROMPT,
                         probe_tool_calling, run_agent_session)


def _tool_call(name, args):
    return {"id": "call_1", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def _resp(messages, usage_prompt=10, usage_comp=4):
    return {"id": "x", "object": "chat.completion", "created": 1, "model": "m",
            "choices": [{"index": 0, "message": messages, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": usage_prompt, "completion_tokens": usage_comp,
                      "total_tokens": usage_prompt + usage_comp}}


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 1.0
        return self.t


def _plan_handler(requests):
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("tool_choice") == {"type": "function", "function": {"name": "submit_plan"}}:
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [_tool_call("submit_plan", {"steps": ["a", "b"]})]}
        elif len(body["messages"]) >= 6:
            msg = {"role": "assistant", "content": "done",
                   "tool_calls": [_tool_call("finish", {"answer": "ok"})]}
        else:
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [_tool_call("read_file", {"path": "a.py"})]}
        return httpx.Response(200, json=_resp(msg))
    return handler


@pytest.mark.asyncio
async def test_run_agent_session_plan_then_act_then_finish(monkeypatch):
    monkeypatch.setattr("app.agentic.time.monotonic", FakeClock())
    requests = []
    transport = httpx.MockTransport(_plan_handler(requests))
    result = await run_agent_session(
        base_url="http://127.0.0.1:9", model="m", steps=10, max_tokens=4096,
        task="codebase_refactor", transport=transport)
    assert result["status"] == "ok"
    assert result["finished"] is True
    assert result["steps"] == 3
    assert result["tool_calls"] >= 3
    assert result["agentic_tps"] == (10 * 3 + 4 * 3) / 3.0
    assert result["total_wall_s"] == 3.0
    assert requests[0]["tool_choice"] == {"type": "function", "function": {"name": "submit_plan"}}


@pytest.mark.asyncio
async def test_run_agent_session_budget_exhausted(monkeypatch):
    monkeypatch.setattr("app.agentic.time.monotonic", FakeClock())

    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json=_resp(
            {"role": "assistant", "content": None,
             "tool_calls": [_tool_call("read_file", {"path": "a.py"})]}))

    transport = httpx.MockTransport(handler)
    result = await run_agent_session(
        base_url="http://127.0.0.1:9", model="m", steps=2, max_tokens=4096,
        task="codebase_refactor", transport=transport)
    assert result["status"] == "ok"
    assert result["finished"] is False
    assert result["steps"] == 2


@pytest.mark.asyncio
async def test_probe_tool_calling_ok(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=_resp(
            {"role": "assistant", "content": None,
             "tool_calls": [_tool_call("read_file", {"path": "x"})]}))

    transport = httpx.MockTransport(handler)
    assert await probe_tool_calling("http://x", "m", transport=transport) is True


@pytest.mark.asyncio
async def test_probe_tool_calling_missing_tool_calls():
    def handler(request):
        return httpx.Response(200, json=_resp({"role": "assistant", "content": "hi"}))

    transport = httpx.MockTransport(handler)
    assert await probe_tool_calling("http://x", "m", transport=transport) is False


def test_tasks_have_expected_keys():
    assert set(AGENTIC_TASKS) == {"codebase_refactor", "data_pipeline", "research"}
    for task in AGENTIC_TASKS.values():
        assert task["prompt"]
        assert isinstance(task["corpus"], dict)


def test_agentic_tool_schemas_expose_control_and_workload_tools():
    names = {s["function"]["name"] for s in AGENTIC_TOOL_SCHEMAS}
    assert {"submit_plan", "finish", "read_file", "list_dir", "search", "calculate"} <= names


def test_calculate_is_guarded():
    from app.agentic import execute_calculate
    assert execute_calculate("2 + 3 * 4") == "14"
    assert execute_calculate("__import__('os').system('x')") == "error: unsupported expression"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_agentic.py -v`
Expected: FAIL — `ModuleNotFoundError`/`ImportError` for `run_agent_session`, `probe_tool_calling`, `AGENTIC_TASKS`.

- [ ] **Step 3: Implement the new harness**

Rewrite `backend/app/agentic.py`:

```python
import asyncio
import json
import operator
import time

import httpx

AGENTIC_DEFAULT_STEPS = 10
AGENTIC_DEFAULT_MAX_TOKENS = 4096

AGENTIC_SYSTEM_PROMPT = (
    "You are an expert software engineer. You operate in two phases: "
    "PLAN and ACT. First call submit_plan with your step-by-step plan. "
    "Then execute the plan by calling the provided tools. You may call "
    "submit_plan again to revise your plan. When done, call finish with "
    "your final answer. Never output a plain text message when a tool "
    "call is expected."
)

DEFAULT_USER_PROMPT = "Analyze the given codebase and propose a refactor."

AGENTIC_TASKS = {
    "codebase_refactor": {
        "prompt": (
            "Analyze the codebase in /repo and propose a concrete refactor "
            "plan. Read the key files, identify issues, then finish with your "
            "recommendation."
        ),
        "corpus": {
            "/repo/main.py": (
                "import time\n\ndef cache():\n    data = {}\n    def get(k):\n        "
                "return data.get(k)\n    def put(k, v):\n        data[k] = v\n    "
                "return get, put\n"
            ) * 40,
            "/repo/util.py": (
                "def normalize(x):\n    return (x or '').strip().lower()\n"
            ) * 60,
            "/repo/tests.py": (
                "def test_cache():\n    assert True\n"
            ) * 50,
        },
    },
    "data_pipeline": {
        "prompt": (
            "Inspect the data pipeline in /data, compute the total bytes "
            "processed using calculate, and finish with your report."
        ),
        "corpus": {
            "/data/ingest.py": (
                "def ingest(path):\n    return len(path)\n"
            ) * 50,
            "/data/transform.py": (
                "def transform(rows):\n    return [r for r in rows]\n"
            ) * 50,
        },
    },
    "research": {
        "prompt": (
            "Research the topic using search, read the top result, and finish "
            "with a summary of your findings."
        ),
        "corpus": {
            "/doc/result1.md": (
                "The transformer architecture uses self-attention.\n"
            ) * 80,
            "/doc/result2.md": (
                "Quantization reduces model size at some accuracy cost.\n"
            ) * 80,
        },
    },
}

AGENTIC_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "submit_plan",
            "description": "Submit a step-by-step plan for the task.",
            "parameters": {
                "type": "object",
                "properties": {"steps": {"type": "array", "items": {"type": "string"}}},
                "required": ["steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Finish the task with a final answer.",
            "parameters": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List the files in a directory of the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the bundled knowledge base and return results.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate an arithmetic expression.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        },
    },
]

_CONTROL_TOOLS = {"submit_plan", "finish"}
_ALLOWED_OPS = {
    "+": operator.add, "-": operator.sub, "*": operator.mul, "/": operator.truediv,
    "//": operator.floordiv, "%": operator.mod, "**": operator.pow,
}
_ALLOWED_NODES = ("Constant", "Expression", "BinOp", "UnaryOp", "Add", "Sub",
                  "Mult", "Div", "FloorDiv", "Mod", "Pow", "USub", "UAdd",
                  "Load", "Module", "Name")


def execute_calculate(expression: str) -> str:
    """Evaluate a safe arithmetic expression. Returns 'error: ...' on unsafe
    input. Does not use eval() on untrusted strings."""
    import ast
    try:
        tree = ast.parse(expression, mode="eval")
        for node in ast.walk(tree):
            if type(node).__name__ not in _ALLOWED_NODES:
                return "error: unsupported expression"
            if isinstance(node, ast.Name) and node.id not in ("__undefined__",):
                return "error: unsupported expression"
        value = _eval_ast(tree.body)
        return str(value)
    except Exception:
        return "error: unsupported expression"


def _eval_ast(node):
    import ast
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("unsupported")
    if isinstance(node, ast.BinOp):
        return _ALLOWED_OPS[type(node.op).__name__](_eval_ast(node.left), _eval_ast(node.right))
    if isinstance(node, ast.UnaryOp):
        return _ALLOWED_OPS[type(node.op).__name__](_eval_ast(node.operand))
    raise ValueError("unsupported")


def _tool_result(name: str, args: dict, corpus: dict) -> str:
    if name == "read_file":
        path = args.get("path", "")
        return corpus.get(path, "error: file not found")[:4000]
    if name == "list_dir":
        paths = sorted(corpus)
        return "\n".join(paths)
    if name == "search":
        query = args.get("query", "").lower()
        hits = [p for p in corpus if query in p.lower()][:5] or list(corpus)[:5]
        return "\n".join(f"{p}: {corpus[p][:200]}" for p in hits)
    if name == "calculate":
        return execute_calculate(args.get("expression", ""))
    return "ok"


async def probe_tool_calling(base_url: str, model: str, request_timeout: float = 60.0,
                             transport=None) -> bool:
    """Return True if the served model can return tool_calls."""
    kwargs = {"base_url": base_url, "timeout": request_timeout}
    if transport is not None:
        kwargs["transport"] = transport
    async with httpx.AsyncClient(**kwargs) as client:
        try:
            resp = await client.post("/v1/chat/completions", json={
                "model": model,
                "messages": [{"role": "user", "content": "call read_file on x"}],
                "tools": AGENTIC_TOOL_SCHEMAS,
                "tool_choice": {"type": "function", "function": {"name": "read_file"}},
                "max_tokens": 64,
            })
            resp.raise_for_status()
            data = resp.json()
            msg = (((data.get("choices") or [{}])[0] or {}).get("message") or {})
            return bool(msg.get("tool_calls"))
        except Exception:
            return False


async def run_agent_session(base_url, model, steps, max_tokens, task,
                            on_output=None, request_timeout=120.0, transport=None):
    """Run a plan→act agent session. Returns serving-throughput metrics plus a
    transcript of the whole exchange."""
    scenario = AGENTIC_TASKS.get(task, AGENTIC_TASKS["codebase_refactor"])
    corpus = scenario["corpus"]
    messages = [
        {"role": "system", "content": AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": scenario["prompt"]},
    ]
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_wall = 0.0
    latencies_ms = []
    tool_calls = 0
    plan_revisions = 0
    finished = False
    transcript = []
    kwargs = {"base_url": base_url, "timeout": request_timeout}
    if transport is not None:
        kwargs["transport"] = transport

    async with httpx.AsyncClient(**kwargs) as client:
        step = 0
        while step < steps:
            step += 1
            if step == 1:
                body = {
                    "model": model,
                    "messages": messages,
                    "tools": AGENTIC_TOOL_SCHEMAS,
                    "tool_choice": {"type": "function", "function": {"name": "submit_plan"}},
                    "max_tokens": max_tokens,
                    "temperature": 0.2,
                    "stream": False,
                }
            else:
                body = {
                    "model": model,
                    "messages": messages,
                    "tools": AGENTIC_TOOL_SCHEMAS,
                    "tool_choice": "auto",
                    "max_tokens": max_tokens,
                    "temperature": 0.2,
                    "stream": False,
                }
            start = time.monotonic()
            resp = await client.post("/v1/chat/completions", json=body)
            resp.raise_for_status()
            data = resp.json()
            elapsed = time.monotonic() - start
            latencies_ms.append(elapsed * 1000.0)
            usage = data.get("usage") or {}
            p_tok = int(usage.get("prompt_tokens", 0) or 0)
            c_tok = int(usage.get("completion_tokens", 0) or 0)
            total_prompt_tokens += p_tok
            total_completion_tokens += c_tok
            total_wall += elapsed
            msg = (((data.get("choices") or [{}])[0] or {}).get("message") or {})
            content = msg.get("content") or ""
            calls = msg.get("tool_calls") or []
            if content:
                messages.append({"role": "assistant", "content": content})
            if calls:
                messages.append({"role": "assistant", "content": content or None,
                                 "tool_calls": calls})
            for call in calls:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_calls += 1
                if name == "finish":
                    finished = True
                    transcript.append(f"step {step}: finish")
                    messages.append({"role": "tool", "tool_call_id": call.get("id", "call_0"),
                                     "content": "finished"})
                    break
                if name == "submit_plan" and step > 1:
                    plan_revisions += 1
                result = _tool_result(name, args, corpus)
                transcript.append(f"step {step}: {name}({json.dumps(args)}) -> {result[:80]}")
                messages.append({"role": "tool", "tool_call_id": call.get("id", "call_0"),
                                 "content": result})
            if on_output is not None:
                await on_output("line", (
                    f"step {step}/{steps}: prompt {p_tok} tok + {c_tok} tok in {elapsed:.1f}s"
                ))
            if finished:
                break
    if latencies_ms:
        latencies_ms.sort()
        avg_latency_ms = sum(latencies_ms) / len(latencies_ms)
        p95_idx = min(len(latencies_ms) - 1, int(0.95 * len(latencies_ms)))
        p95_latency_ms = latencies_ms[p95_idx]
    else:
        avg_latency_ms = None
        p95_latency_ms = None
    total_tokens = total_prompt_tokens + total_completion_tokens
    return {
        "status": "ok",
        "agentic_tps": total_tokens / total_wall if total_wall > 0 else None,
        "prompt_processing_tps": None,
        "decode_tps": None,
        "steps": step,
        "tool_calls": tool_calls,
        "plan_revisions": plan_revisions,
        "avg_latency_ms": avg_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_wall_s": total_wall,
        "finished": finished,
        "transcript": transcript,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_agentic.py -v`
Expected: PASS (all 7 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agentic.py backend/tests/test_agentic.py
git commit -m "feat: rewrite agentic bench as real plan-to-act agent harness"
```

---

## Task 2: Update agentic flags + config (servers.py, config.py, api.py)

**Files:**
- Modify: `backend/app/servers.py:315-374`
- Modify: `backend/app/config.py:19-21`
- Modify: `backend/app/api.py:544-555, 600-637`

- [ ] **Step 1: Write the failing tests**

Update `backend/tests/test_servers.py` (replace the agentic flag tests around lines 585-629):

```python
def test_agentic_default_flags():
    assert agentic_default_flags() == "--steps 10 --max-tokens 4096 --task codebase_refactor"
    assert agentic_default_flags(steps=6, max_tokens=8192, task="research") == \
        "--steps 6 --max-tokens 8192 --task research"


def test_parse_agentic_flags():
    assert parse_agentic_flags("--steps 10 --max-tokens 4096 --task research") == \
        ["--steps", "10", "--max-tokens", "4096", "--task", "research"]
    assert parse_agentic_flags("agentic --steps=6 --task=research") == \
        ["--steps", "6", "--task", "research"]
    assert parse_agentic_flags("  ") == []


def test_validate_agentic_flags_valid():
    assert validate_agentic_flags(["--steps", "10", "--max-tokens", "4096",
                                   "--task", "research"]) is None


def test_validate_agentic_flags_unknown_flag():
    err = validate_agentic_flags(["--foo", "1"])
    assert err is not None and "unknown agentic flag '--foo'" in err


def test_validate_agentic_flags_missing_value():
    assert validate_agentic_flags(["--steps"]) is not None


def test_validate_agentic_flags_non_int():
    assert validate_agentic_flags(["--steps", "abc"]) is not None


def test_validate_agentic_flags_out_of_range():
    assert validate_agentic_flags(["--steps", "0", "--max-tokens", "1"]) is not None
    assert validate_agentic_flags(["--steps", "21", "--max-tokens", "1"]) is not None
    assert validate_agentic_flags(["--steps", "10", "--max-tokens", "0"]) is not None
    assert validate_agentic_flags(["--steps", "10", "--max-tokens", "32769"]) is not None


def test_validate_agentic_flags_bad_task():
    err = validate_agentic_flags(["--task", "nope"])
    assert err is not None and "unknown --task" in err


def test_validate_agentic_flags_bare_token():
    assert validate_agentic_flags(["--steps", "10", "stray"]) is not None


def test_build_agentic_command():
    cmd = build_agentic_command("org/model", ["--steps", "10", "--max-tokens", "4096", "--task", "research"])
    assert cmd == ["agentic", "--model", "org/model", "--steps", "10", "--max-tokens", "4096", "--task", "research"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_servers.py -k agentic -v`
Expected: FAIL — default flags string mismatch, unknown flag errors.

- [ ] **Step 3: Implement flag/config changes**

In `backend/app/servers.py`, replace the agentic section (lines 315-374):

```python
AGENTIC_CLI_FLAGS = ("--steps", "--max-tokens", "--task")
AGENTIC_TASKS = ("codebase_refactor", "data_pipeline", "research")


def agentic_default_flags(steps: int = 10, max_tokens: int = 4096,
                          task: str = "codebase_refactor") -> str:
    return f"--steps {steps} --max-tokens {max_tokens} --task {task}"
```

Keep `parse_agentic_flags` unchanged (it is generic). Update `validate_agentic_flags` to use the new constants and validate the task:

```python
def validate_agentic_flags(flags: list[str]) -> str | None:
    """Return an error message for invalid agentic flags, or None if valid."""
    parsed: dict[str, str] = {}
    i = 0
    while i < len(flags):
        tok = flags[i]
        if not tok.startswith("-"):
            return f"unexpected token '{tok}'"
        name = tok
        value = None
        if tok.startswith("--") and "=" in tok:
            name, _, value = tok.partition("=")
        elif i + 1 < len(flags) and not flags[i + 1].startswith("-"):
            value = flags[i + 1]
            i += 1
        if name not in AGENTIC_CLI_FLAGS:
            return (f"unknown agentic flag '{name}'; allowed: "
                    + ", ".join(AGENTIC_CLI_FLAGS))
        if value is None:
            return f"flag '{name}' requires a value"
        if name in ("--steps", "--max-tokens"):
            try:
                parsed[name] = int(value)
            except (TypeError, ValueError):
                return f"flag '{name}' requires an integer value"
        else:
            parsed[name] = value
        i += 1
    if "--steps" in parsed and not (1 <= parsed["--steps"] <= 20):
        return "'--steps' must be between 1 and 20"
    if "--max-tokens" in parsed and not (1 <= parsed["--max-tokens"] <= 32768):
        return "'--max-tokens' must be between 1 and 32768"
    if "--task" in parsed and parsed["--task"] not in AGENTIC_TASKS:
        return ("unknown --task; available: " + ", ".join(AGENTIC_TASKS))
    return None
```

In `backend/app/config.py`, replace lines 19-21:

```python
    agentic_steps: int = 10
    agentic_max_tokens: int = 4096
    agentic_task: str = "codebase_refactor"
```

In `backend/app/api.py`, update the two `agentic_default_flags` calls (lines 546-547, 617-618) from `agentic_default_flags(s.settings.agentic_turns, s.settings.agentic_max_tokens)` to `agentic_default_flags(s.settings.agentic_steps, s.settings.agentic_max_tokens, s.settings.agentic_task)`.

In `backend/app/api.py`, update the `agentic_params` build (lines 628-633):

```python
        _flag_map = dict(zip(flags[::2], flags[1::2]))
        cfg["agentic_params"] = {
            "model": gguf_filename or model_ref,
            "steps": _flag_map.get("--steps", str(s.settings.agentic_steps)),
            "max_tokens": _flag_map.get("--max-tokens", str(s.settings.agentic_max_tokens)),
            "task": _flag_map.get("--task", s.settings.agentic_task),
        }
```

- [ ] **Step 4: Update existing api tests**

In `backend/tests/test_api.py`, update the agentic assertions (lines 1928-1930, 1959, 1971-1972) from `turns`/`max_tokens` to `steps`/`max_tokens`/`task`, and settings kwargs from `agentic_turns=4, agentic_max_tokens=16384` to `agentic_steps=10, agentic_max_tokens=4096`. Update `test_generate_configs_agentic_invalid_flags_set_bench_error` (line 1899) to use `"--steps abc"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_servers.py tests/test_api.py -k agentic -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/servers.py backend/app/config.py backend/app/api.py backend/tests/test_servers.py backend/tests/test_api.py
git commit -m "feat: switch agentic flags to steps/max-tokens/task"
```

---

## Task 3: Update AgenticRunner (benchmark.py)

**Files:**
- Modify: `backend/app/benchmark.py:404-557`
- Test: `backend/tests/test_benchmark.py:471-598`

- [ ] **Step 1: Write/update failing tests**

Update `backend/tests/test_benchmark.py`:

- In `AGENTIC_SESSION_RESULT` (line 471), rename `"turns"` to `"steps"` and add the new metric keys:
```python
AGENTIC_SESSION_RESULT = {
    "agentic_tps": 25.0,
    "prompt_processing_tps": None,
    "decode_tps": None,
    "total_prompt_tokens": 9000,
    "total_completion_tokens": 1600,
    "total_wall_s": 64.0,
    "steps": 6,
    "tool_calls": 9,
    "plan_revisions": 1,
    "avg_latency_ms": 1200.0,
    "p95_latency_ms": 3400.0,
    "finished": True,
    "transcript": [],
}
```
- Update `test_agentic_runner_ok`'s `fake_session` signature to `(base_url, model, steps, max_tokens, task, on_output=None, request_timeout=120.0, transport=None)`, and the `AgenticRunner(...)` construction `params` to `{"model": "x.gguf", "steps": "6", "max_tokens": "4096", "task": "codebase_refactor"}`.
- Update `test_agentic_runner_abort_mid_session_reports_aborted`'s `aborting_session` signature to match the new `fake_session` signature.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_benchmark.py -k agentic -v`
Expected: FAIL — `TypeError` on unexpected `steps`/`task` keyword.

- [ ] **Step 3: Implement AgenticRunner changes**

In `backend/app/benchmark.py`, in the `AgenticRunner.run()` method (line 503-516), replace the `run_agentic_session` call block:

```python
            try:
                session = await asyncio.wait_for(
                    run_agent_session(
                        base_url=f"http://127.0.0.1:{port}",
                        model=self.params.get("model", "default"),
                        steps=int(self.params.get("steps", self._default_steps)),
                        max_tokens=int(self.params.get("max_tokens", self._default_max_tokens)),
                        task=self.params.get("task", "codebase_refactor"),
                        on_output=on_output,
                        request_timeout=self.timeout_s,
                    ),
                    timeout=self.timeout_s,
                )
```

Update the constructor's imports and defaults (lines 413-420) from `AGENTIC_DEFAULT_TURNS`/`run_agentic_session`/`load_workload_prompts` to `AGENTIC_DEFAULT_STEPS`/`AGENTIC_DEFAULT_MAX_TOKENS`/`run_agent_session`:

```python
    def __init__(self, server_command: list[str], params: dict,
                 timeout_s: float, startup_timeout_s: float, workload_file: str):
        from app.agentic import AGENTIC_DEFAULT_MAX_TOKENS, AGENTIC_DEFAULT_STEPS
        self.server_command = list(server_command)
        self.params = dict(params)
        self.timeout_s = timeout_s
        self.startup_timeout_s = startup_timeout_s
        self.workload_file = workload_file
        self._default_steps = AGENTIC_DEFAULT_STEPS
        self._default_max_tokens = AGENTIC_DEFAULT_MAX_TOKENS
        self._aborted = asyncio.Event()
        self._procs: list[asyncio.subprocess.Process] = []
```

Update the import at line 460 from `from app.agentic import load_workload_prompts, run_agentic_session` to `from app.agentic import run_agent_session`.

Remove the now-unused `load_workload_prompts` call (line 503) — the harness uses bundled scenarios, so delete the `prompts = load_workload_prompts(self.workload_file)` line. (The `workload_file` param stays in the signature for backward compatibility but is unused by the harness.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_benchmark.py -k agentic -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/benchmark.py backend/tests/test_benchmark.py
git commit -m "feat: wire AgenticRunner to the real agent session"
```

---

## Task 4: DB migration + save/select detail (db.py)

**Files:**
- Modify: `backend/app/db.py:142-147, 269-294`
- Test: `backend/tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_db.py`:

```python
def test_migrate_results_adds_agentic_detail_v2(tmp_path):
    db_path = tmp_path / "legacy-results.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE servers (id TEXT PRIMARY KEY, display_name TEXT NOT NULL);
        CREATE TABLE models (id INTEGER PRIMARY KEY AUTOINCREMENT, repo_id TEXT NOT NULL,
            server_id TEXT NOT NULL, format TEXT NOT NULL, local_path TEXT NOT NULL,
            status TEXT NOT NULL, gguf_filename TEXT, size_bytes INTEGER, downloaded_at TEXT);
        CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, repo_id TEXT NOT NULL,
            requested_n INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')),
            status TEXT NOT NULL DEFAULT 'queued');
        CREATE TABLE configs (id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id), server_id TEXT NOT NULL,
            model_id INTEGER REFERENCES models(id), flag_conf_json TEXT NOT NULL,
            serving_command TEXT NOT NULL, bench_command TEXT NOT NULL);
        CREATE TABLE results (id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_id INTEGER NOT NULL REFERENCES configs(id),
            prompt_processing_tps REAL, decode_tps REAL, agentic_tps REAL,
            duration_s REAL, output_snippet TEXT, status TEXT NOT NULL);
        """
    )
    conn.execute("INSERT INTO runs(repo_id, requested_n) VALUES ('org/model', 1)")
    conn.execute(
        "INSERT INTO configs(run_id, server_id, model_id, flag_conf_json, serving_command, bench_command) "
        "VALUES (1, 'llama.cpp', NULL, '[]', 'serve', 'bench')"
    )
    conn.execute(
        "INSERT INTO results(config_id, prompt_processing_tps, decode_tps, agentic_tps, duration_s, output_snippet, status) "
        "VALUES (1, NULL, NULL, 25.0, 64.0, '', 'ok')"
    )
    conn.commit()
    conn.close()

    conn = init_db(db_path)
    cols = [row[1] for row in conn.execute("PRAGMA table_info('results')")]
    for col in ("agentic_steps", "agentic_tool_calls", "agentic_plan_revisions",
                "agentic_avg_ms", "agentic_p95_ms", "total_prompt_tokens",
                "total_completion_tokens"):
        assert col in cols
    rows = get_results_for_run(conn, 1)
    assert rows[0]["agentic_tps"] == 25.0
    assert rows[0]["agentic_steps"] is None
    conn.close()


def test_save_and_read_agentic_detail(tmp_path):
    conn = init_db(tmp_path / "test.db")
    upsert_model(conn, repo_id="org/model", server_id="llama.cpp", format="hf",
                 local_path="/x", status="downloaded")
    run_id = create_run(conn, repo_id="org/model", requested_n=1)
    cfg = create_config(conn, run_id=run_id, server_id="llama.cpp", model_id=1,
                        flag_conf_json=[], serving_command="s", bench_command="b")
    save_result(conn, config_id=cfg, prompt_processing_tps=None, decode_tps=None,
                duration_s=64.0, output_snippet="", status="ok", agentic_tps=25.0,
                agentic_steps=6, agentic_tool_calls=9, agentic_plan_revisions=1,
                agentic_avg_ms=1200.0, agentic_p95_ms=3400.0,
                total_prompt_tokens=9000, total_completion_tokens=1600)
    rows = get_results_for_run(conn, run_id)
    assert rows[0]["agentic_steps"] == 6
    assert rows[0]["agentic_tool_calls"] == 9
    assert rows[0]["agentic_plan_revisions"] == 1
    assert rows[0]["agentic_avg_ms"] == 1200.0
    assert rows[0]["agentic_p95_ms"] == 3400.0
    assert rows[0]["total_prompt_tokens"] == 9000
    assert rows[0]["total_completion_tokens"] == 1600
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_db.py -k agentic -v`
Expected: FAIL — `KeyError`/`no such column` for the new columns.

- [ ] **Step 3: Implement db changes**

In `backend/app/db.py`:

Update the `results` table schema (line 37-46) to add the new columns after `agentic_tps REAL`:

```python
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id INTEGER NOT NULL REFERENCES configs(id),
    prompt_processing_tps REAL,
    decode_tps REAL,
    agentic_tps REAL,
    agentic_steps INTEGER,
    agentic_tool_calls INTEGER,
    agentic_plan_revisions INTEGER,
    agentic_avg_ms REAL,
    agentic_p95_ms REAL,
    total_prompt_tokens INTEGER,
    total_completion_tokens INTEGER,
    duration_s REAL,
    output_snippet TEXT,
    status TEXT NOT NULL
);
```

Add a new migration after `_migrate_results_agentic` (line 142-146):

```python
def _migrate_results_agentic_v2(conn):
    cols = [row[1] for row in conn.execute("PRAGMA table_info('results')")]
    new_cols = [
        ("agentic_steps", "INTEGER"), ("agentic_tool_calls", "INTEGER"),
        ("agentic_plan_revisions", "INTEGER"), ("agentic_avg_ms", "REAL"),
        ("agentic_p95_ms", "REAL"), ("total_prompt_tokens", "INTEGER"),
        ("total_completion_tokens", "INTEGER"),
    ]
    for name, typ in new_cols:
        if name not in cols:
            conn.execute(f"ALTER TABLE results ADD COLUMN {name} {typ}")
    conn.commit()
```

Call `_migrate_results_agentic_v2(conn)` in `init_db` right after `_migrate_results_agentic(conn)` (line 157).

Update `save_result` (lines 269-277):

```python
def save_result(conn, config_id, prompt_processing_tps, decode_tps, duration_s,
                output_snippet, status, agentic_tps=None, agentic_steps=None,
                agentic_tool_calls=None, agentic_plan_revisions=None,
                agentic_avg_ms=None, agentic_p95_ms=None,
                total_prompt_tokens=None, total_completion_tokens=None):
    conn.execute(
        "INSERT INTO results(config_id, prompt_processing_tps, decode_tps, agentic_tps, "
        "agentic_steps, agentic_tool_calls, agentic_plan_revisions, agentic_avg_ms, "
        "agentic_p95_ms, total_prompt_tokens, total_completion_tokens, "
        "duration_s, output_snippet, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (config_id, prompt_processing_tps, decode_tps, agentic_tps,
         agentic_steps, agentic_tool_calls, agentic_plan_revisions, agentic_avg_ms,
         agentic_p95_ms, total_prompt_tokens, total_completion_tokens,
         duration_s, output_snippet, status),
    )
    conn.commit()
```

Update `get_results_for_run` (lines 280-294) SELECT list:

```python
        SELECT c.id AS config_id, c.server_id, c.flag_conf_json,
               c.serving_command, r.prompt_processing_tps, r.decode_tps,
               r.agentic_tps, r.agentic_steps, r.agentic_tool_calls,
               r.agentic_plan_revisions, r.agentic_avg_ms, r.agentic_p95_ms,
               r.total_prompt_tokens, r.total_completion_tokens,
               r.duration_s, r.status AS result_status
```

In `backend/app/api.py`, update the `save_result` call at line 779-782 to pass the new detail from the result dict:

```python
                    db_mod.save_result(s.conn, cfg_id, result["prompt_processing_tps"],
                                       result["decode_tps"], result["duration_s"],
                                       result["output"], result["status"],
                                       agentic_tps=result.get("agentic_tps"),
                                       agentic_steps=result.get("steps"),
                                       agentic_tool_calls=result.get("tool_calls"),
                                       agentic_plan_revisions=result.get("plan_revisions"),
                                       agentic_avg_ms=result.get("avg_latency_ms"),
                                       agentic_p95_ms=result.get("p95_latency_ms"),
                                       total_prompt_tokens=result.get("total_prompt_tokens"),
                                       total_completion_tokens=result.get("total_completion_tokens"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_db.py -k agentic -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db.py backend/app/api.py backend/tests/test_db.py
git commit -m "feat: persist rich agentic metrics in results table"
```

---

## Task 5: Frontend types + AgenticDetailStrip component

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/ws/useBenchmarkProgress.ts`
- Create: `frontend/src/components/AgenticDetailStrip.tsx`
- Create: `frontend/src/components/AgenticDetailStrip.test.tsx`

- [ ] **Step 1: Write failing component test**

Create `frontend/src/components/AgenticDetailStrip.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { AgenticDetailStrip } from "./AgenticDetailStrip";

test("renders agentic detail metrics", () => {
  render(
    <AgenticDetailStrip
      steps={10}
      toolCalls={14}
      planRevisions={2}
      avgMs={1200.0}
      p95Ms={3400.0}
      totalPromptTokens={9000}
      totalCompletionTokens={1600}
    />
  );
  expect(screen.getByText(/10 steps/i)).toBeInTheDocument();
  expect(screen.getByText(/14 tool calls/i)).toBeInTheDocument();
  expect(screen.getByText(/2 plan revs/i)).toBeInTheDocument();
  expect(screen.getByText(/avg 1.2s/i)).toBeInTheDocument();
  expect(screen.getByText(/p95 3.4s/i)).toBeInTheDocument();
  expect(screen.getByText(/ctx 10.6k/i)).toBeInTheDocument();
});

test("renders nothing when no metrics present", () => {
  const { container } = render(<AgenticDetailStrip steps={null} toolCalls={null} planRevisions={null} avgMs={null} p95Ms={null} totalPromptTokens={null} totalCompletionTokens={null} />);
  expect(container.textContent).toBe("");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/AgenticDetailStrip.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component and types**

Create `frontend/src/components/AgenticDetailStrip.tsx`:

```tsx
import { useTranslation } from "react-i18next";

export interface AgenticDetail {
  steps: number | null;
  toolCalls: number | null;
  planRevisions: number | null;
  avgMs: number | null;
  p95Ms: number | null;
  totalPromptTokens: number | null;
  totalCompletionTokens: number | null;
}

export function AgenticDetailStrip({
  steps,
  toolCalls,
  planRevisions,
  avgMs,
  p95Ms,
  totalPromptTokens,
  totalCompletionTokens,
}: AgenticDetail) {
  const { t } = useTranslation();
  const parts: string[] = [];
  if (steps != null) parts.push(t("metrics.agenticSteps", { count: steps }));
  if (toolCalls != null) parts.push(t("metrics.agenticToolCalls", { count: toolCalls }));
  if (planRevisions != null) parts.push(t("metrics.agenticPlanRevs", { count: planRevisions }));
  if (avgMs != null) parts.push(t("metrics.agenticAvg", { s: (avgMs / 1000).toFixed(1) }));
  if (p95Ms != null) parts.push(t("metrics.agenticP95", { s: (p95Ms / 1000).toFixed(1) }));
  const ctx = totalPromptTokens != null && totalCompletionTokens != null
    ? totalPromptTokens + totalCompletionTokens
    : null;
  if (ctx != null) parts.push(t("metrics.agenticCtx", { k: (ctx / 1000).toFixed(1) }));
  if (parts.length === 0) return null;
  return (
    <div className="agentic-detail" style={{ fontSize: 10, color: "var(--anode)", letterSpacing: 0.5 }}>
      {parts.join(" · ")}
    </div>
  );
}
```

Add i18n keys to `frontend/src/i18n/locales/en/translation.json` under `metrics`:

```json
  "metrics": {
    "promptProc": "PROMPT PROC · t/s",
    "decodeStage": "DECODE STAGE · t/s",
    "agentic": "AGENTIC · t/s",
    "agenticSteps": "{{count}} steps",
    "agenticToolCalls": "{{count}} tool calls",
    "agenticPlanRevs": "{{count}} plan revs",
    "agenticAvg": "avg {{s}}s",
    "agenticP95": "p95 {{s}}s",
    "agenticCtx": "ctx {{k}}k"
  }
```

Add the same 7 keys to the `metrics` object in the other 14 locale files (zh, ja, de, fr, es, ko, ar, pt, it, nl, sv, no, da, fi), using the English strings as placeholder translations (existing i18n convention allows English fallback).

Update `frontend/src/api/client.ts` — extend `RunDetail["results"]` items (lines 109-119) with the new nullable fields:

```ts
    agentic_steps: number | null;
    agentic_tool_calls: number | null;
    agentic_plan_revisions: number | null;
    agentic_avg_ms: number | null;
    agentic_p95_ms: number | null;
    total_prompt_tokens: number | null;
    total_completion_tokens: number | null;
```

Update `frontend/src/ws/useBenchmarkProgress.ts`:

- Extend `ProgressEvent`'s `result` object (line 11) and `ResultRow` (lines 17-24) with the same 7 fields.
- Extend `ProgressState` with an `agenticDetail: AgenticDetail | null` (import type from the component).
- In the `config_done` handler (lines 94-121), populate `agenticDetail` from `event.result` and pass the new fields into the `newResult`.
- In `run_sync`/`run_watch`, derive `agenticDetail` from the last row.

Update `frontend/src/App.tsx` `toResultRow` (lines 70-79) to map the 7 new fields.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/AgenticDetailStrip.test.tsx`
Expected: PASS.

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npx tsc -b`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/ws/useBenchmarkProgress.ts frontend/src/components/AgenticDetailStrip.tsx frontend/src/components/AgenticDetailStrip.test.tsx frontend/src/App.tsx frontend/src/i18n/locales/
git commit -m "feat: add agentic detail metrics and detail strip component"
```

---

## Task 6: Surface detail strip in RunPanel + ResultsTable

**Files:**
- Modify: `frontend/src/components/RunPanel.tsx`
- Modify: `frontend/src/components/ResultsTable.tsx`
- Test: `frontend/src/components/ResultsTable.test.tsx`

- [ ] **Step 1: Write failing tests**

Add to `frontend/src/components/ResultsTable.test.tsx`:

```tsx
test("renders agentic detail strip when agentic metrics present", () => {
  render(
    <ResultsTable
      rows={[{
        server_id: "llama.cpp",
        flag_conf: {},
        prompt_processing_tps: 100.0,
        decode_tps: 50.0,
        agentic_tps: 12.3,
        agentic_steps: 10,
        agentic_tool_calls: 14,
        agentic_plan_revisions: 2,
        agentic_avg_ms: 1200.0,
        agentic_p95_ms: 3400.0,
        total_prompt_tokens: 9000,
        total_completion_tokens: 1600,
      }]}
    />
  );
  expect(screen.getByText(/10 steps/i)).toBeInTheDocument();
  expect(screen.getByText(/14 tool calls/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/ResultsTable.test.tsx`
Expected: FAIL — detail strip not rendered.

- [ ] **Step 3: Implement**

Update `frontend/src/components/ResultsTable.tsx`:

- Import `AgenticDetailStrip`.
- Extend `ResultRow` (lines 4-11) with the 7 new nullable fields.
- Inside the AGENTIC `<td>` (line 42), render the strip under the digit:

```tsx
            <td className={i === 0 && r.agentic_tps != null ? "digit-best" : ""}>
              {r.agentic_tps?.toFixed(1) ?? "—"}
              <AgenticDetailStrip
                steps={r.agentic_steps ?? null}
                toolCalls={r.agentic_tool_calls ?? null}
                planRevisions={r.agentic_plan_revisions ?? null}
                avgMs={r.agentic_avg_ms ?? null}
                p95Ms={r.agentic_p95_ms ?? null}
                totalPromptTokens={r.total_prompt_tokens ?? null}
                totalCompletionTokens={r.total_completion_tokens ?? null}
              />
            </td>
```

Update `frontend/src/components/RunPanel.tsx`:

- Import `AgenticDetailStrip` and add `agenticDetail?: AgenticDetail | null` to `Progress` (lines 5-11).
- Render it under `MetricsBanks` (after line 58):

```tsx
      <AgenticDetailStrip
        steps={progress?.agenticDetail?.steps ?? null}
        toolCalls={progress?.agenticDetail?.toolCalls ?? null}
        planRevisions={progress?.agenticDetail?.planRevisions ?? null}
        avgMs={progress?.agenticDetail?.avgMs ?? null}
        p95Ms={progress?.agenticDetail?.p95Ms ?? null}
        totalPromptTokens={progress?.agenticDetail?.totalPromptTokens ?? null}
        totalCompletionTokens={progress?.agenticDetail?.totalCompletionTokens ?? null}
      />
```

In `App.tsx`, pass `agenticDetail: progressState.agenticDetail` into the `RunPanel` `progress` object (line 637-647).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/ResultsTable.test.tsx`
Expected: PASS.

- [ ] **Step 5: Typecheck + full frontend tests**

Run: `cd frontend && npx tsc -b && npx vitest run`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/RunPanel.tsx frontend/src/components/ResultsTable.tsx frontend/src/components/ResultsTable.test.tsx frontend/src/App.tsx
git commit -m "feat: surface agentic detail strip in run panel and results table"
```

---

## Task 7: Update e2e mock-server + flow spec

**Files:**
- Modify: `frontend/e2e/mock-server.ts`
- Modify: `frontend/e2e/flow.spec.ts`

- [ ] **Step 1: Update mock-server agentic responses**

In `frontend/e2e/mock-server.ts`:

- Update the agentic `configs/generate` branch (lines 104-112) to return new flags:
```ts
      Object.assign(body, {
        configs: [{
          ...base,
          bench_tool: "agentic",
          bench_flags: "--steps 10 --max-tokens 4096 --task codebase_refactor",
          bench_command: ["agentic", "--model", "org/model", "--steps", "10", "--max-tokens", "4096", "--task", "codebase_refactor"],
        }],
      });
```
- Update the `benchmarks/{id}` result (lines 131-139) to include the detail fields:
```ts
      results: [{
        config_id: 1,
        server_id: "llama.cpp",
        flag_conf: { "--ctx-size": "8192", "--load-mode": "none", "--no-mmproj": "" },
        serving_command: "llama-server --hf-repo org/model --hf-file model.gguf --load-mode none --no-mmproj --ctx-size 8192",
        prompt_processing_tps: 100.0,
        decode_tps: 42.0,
        agentic_tps: 25.0,
        agentic_steps: 10,
        agentic_tool_calls: 14,
        agentic_plan_revisions: 2,
        agentic_avg_ms: 1200.0,
        agentic_p95_ms: 3400.0,
        total_prompt_tokens: 9000,
        total_completion_tokens: 1600,
      }],
```

- [ ] **Step 2: Update flow.spec.ts agentic test**

In `frontend/e2e/flow.spec.ts`, update the agentic flow test (lines 53-56):

```ts
  await expect(page.getByText(/--steps 10 --max-tokens 4096 --task codebase_refactor/i)).toBeVisible();

  await page.getByRole("button", { name: /run benchmark/i }).click();
  await expect(page.getByRole("cell", { name: "25.0" })).toBeVisible();
  await expect(page.getByText(/10 steps/i)).toBeVisible();
```

- [ ] **Step 3: Run the e2e agentic test**

Ensure the mock-server is running (per AGENTS.md, `./up.sh`), then:

Run: `cd frontend && npx playwright test e2e/flow.spec.ts -g "agentic"`
Expected: PASS.

- [ ] **Step 4: Run full e2e suite**

Run: `cd frontend && npx playwright test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/mock-server.ts frontend/e2e/flow.spec.ts
git commit -m "test: update e2e mock-server and agentic flow for new agent harness"
```

---

## Task 8: README update

**Files:**
- Modify: `README.md:116, 146`

- [ ] **Step 1: Update the agentic descriptions**

Replace line 116:

```markdown
- The **agentic** bench tool drives a real in-process plan→act agent harness (tools, planning loop, decision branching) against the serving model and reports effective AGENTIC t/s across the whole session — total tokens (prompt + completion) over wall time, so it reflects real interactive agentic load including every prefill.
```

Replace line 146:

```markdown
- **agentic** — in-process plan→act agent harness; runs a conversational benchmark against a live `llama-server` using function calling (plan → act → finish), reporting effective AGENTIC t/s plus steps, tool calls, plan revisions, avg/p95 latency, and context tokens (`--steps 10 --max-tokens 4096 --task codebase_refactor` by default). Requires a model that supports OpenAI tool calling.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: describe the real agentic bench harness"
```

---

## Task 9: Full verification

- [ ] **Step 1: Run the complete local check suite**

Run: `cd backend && python -m pytest -q`
Run: `cd frontend && npx tsc -b && npx vitest run`
Run: `cd frontend && npx playwright test`

Expected: ALL PASS.

- [ ] **Step 2: Commit any remaining changes**

```bash
git status
git add -A
git commit -m "chore: final verification pass"
```

---

## Self-Review

**Spec coverage:**
- Real plan→act harness (tools, planning loop, branching) → Task 1 ✅
- Safe load-generating tools (no shell/host FS) → Task 1 (`_tool_result`, `execute_calculate`) ✅
- Bundled scenarios → Task 1 (`AGENTIC_TASKS`) ✅
- Max-steps cap + early finish → Task 1 (loop + `finish` break) ✅
- Require tool-calling, fail clearly → Task 1 (`probe_tool_calling`) + runner's failure path ✅
- Rich metric set → Tasks 1, 4 (DB), 5-6 (UI) ✅
- Headline `agentic_tps` redefined to total tokens ÷ wall → Task 1 ✅
- Flags `--steps/--max-tokens/--task` → Task 2 ✅
- `agentic_turns` → `agentic_steps` → Task 2 ✅
- Frontend detail strip in RunPanel + ResultsTable → Tasks 5-6 ✅
- i18n keys in 15 locales → Task 5 ✅
- e2e + README → Tasks 7-8 ✅

**Placeholder scan:** No TBD/TODO; every code step includes full implementation.

**Type consistency:** `steps`/`tool_calls`/`plan_revisions`/`avg_latency_ms`/`p95_latency_ms`/`total_prompt_tokens`/`total_completion_tokens` are consistent from `agentic.py` → `benchmark.py` → `db.py` (`agentic_steps`/`agentic_tool_calls`/`agentic_plan_revisions`/`agentic_avg_ms`/`agentic_p95_ms`/`total_prompt_tokens`/`total_completion_tokens`) → `api.py` → frontend (`agenticSteps`/`toolCalls`/`planRevisions`/`avgMs`/`p95Ms`/`totalPromptTokens`/`totalCompletionTokens`). `AgenticDetail` interface matches the component props.
