import asyncio
import json
import operator
import time

import httpx

AGENTIC_DEFAULT_STEPS = 10
AGENTIC_DEFAULT_MAX_TOKENS = 4096
AGENTIC_DEFAULT_TIER = "medium"

# Conservative throughput assumptions (tokens/second) used only to size the
# per-request timeout so a heavy tier's prefill is not killed by a flat read
# timeout. Actual hardware is usually faster; these are lower bounds.
_ESTIMATED_PREFILL_TPUT = 20.0
_ESTIMATED_DECODE_TPUT = 20.0
_HEADROOM_FACTOR = 3.0
_TIMEOUT_FLOOR_S = 60.0


def agentic_request_timeout(tier: str, max_tokens: int) -> int:
    """Estimate a per-request wall-clock budget (seconds) large enough for ONE
    model call at the given tier: fill_tokens of prefill + max_tokens of decode,
    at conservative throughputs, with generous headroom. The per-request httpx
    timeout must never fire on a legitimate in-flight request, so it is derived
    from the workload rather than a flat constant."""
    spec = AGENTIC_TIERS.get(tier, AGENTIC_TIERS[AGENTIC_DEFAULT_TIER])
    fill = int(spec.get("fill_tokens", 0))
    prefill_s = fill / _ESTIMATED_PREFILL_TPUT
    decode_s = max(0, int(max_tokens)) / _ESTIMATED_DECODE_TPUT
    return int((prefill_s + decode_s) * _HEADROOM_FACTOR + _TIMEOUT_FLOOR_S)


def agentic_session_timeout(tier: str, steps: int, max_tokens: int) -> int:
    """Estimate a whole-session model-call budget (seconds): up to ``steps``
    requests, each potentially as heavy as the first (the transcript grows, so
    later prefills are no smaller), plus headroom. Excludes user-decision wait
    time (that is handled separately and not billed against this budget)."""
    per_request = agentic_request_timeout(tier, max_tokens)
    return per_request * max(1, int(steps))

# Agentic option tiers: low / medium / heavy. Each maps to a context-window
# size (used as the serving --ctx-size), a --max-tokens default, and a filler
# (injected context) size. The filler is 50% of the tier's ctx value: heavy
# enough to make the prefill genuinely heavy, but small enough to leave headroom
# for the transcript + thinking + decode so a run completes instead of
# guaranteeing context overflow (the earlier 2x sizing overflowed by design).
AGENTIC_TIERS = {
    "low": {"ctx_size": 16384, "max_tokens": 4096, "fill_tokens": 16384 // 2},
    "medium": {"ctx_size": 65536, "max_tokens": 8192, "fill_tokens": 65536 // 2},
    "heavy": {"ctx_size": 131072, "max_tokens": 65728, "fill_tokens": 131072 // 2},
}

# Per-tier bounded thinking intensity. The heavier the tier the larger the
# reasoning trace the model is asked to produce each step (measured in tokens),
# so decode is genuinely heavy but bounded — a runaway "very long" trace that
# fills the whole --max-tokens budget is avoided.
AGENTIC_THINKING_TOKENS = {
    "low": "Keep your reasoning concise, ~80 tokens per step.",
    "medium": "Provide a step-by-step reasoning trace of ~160 tokens per step.",
    "heavy": ("Produce an exhaustive reasoning trace of ~320 tokens per step, "
              "spelling out every consideration before each tool call."),
}

# A single deterministic filler paragraph, repeated to build the injected
# context. 4 chars ~ 1 token is a conservative approximation.
_FILLER_UNIT = (
    "This is a synthetic filler context block used to stress the prefill "
    "path of the serving backend under a real agentic workload. "
)


def _build_filler(fill_tokens: int) -> str:
    """Return a deterministic filler blob of roughly ``fill_tokens`` tokens
    (approx 4 chars/token). Large enough to dominate the prefill."""
    target_chars = max(0, int(fill_tokens) * 4)
    unit = _FILLER_UNIT
    repeats = target_chars // len(unit) + 1
    return (unit * repeats)[:target_chars]


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

_ALLOWED_OPS = {
    "Add": operator.add, "Sub": operator.sub, "Mult": operator.mul,
    "Div": operator.truediv, "FloorDiv": operator.floordiv, "Mod": operator.mod,
    "Pow": operator.pow, "USub": operator.neg, "UAdd": operator.pos,
}
_ALLOWED_NODES = ("Constant", "Expression", "BinOp", "UnaryOp", "Load", "Module",
                  "Name", "Add", "Sub", "Mult", "Div", "FloorDiv", "Mod", "Pow",
                  "USub", "UAdd")


def execute_calculate(expression: str) -> str:
    """Evaluate a safe arithmetic expression. Returns 'error: ...' on unsafe
    input. Does not use eval() on untrusted strings."""
    import ast
    try:
        tree = ast.parse(expression, mode="eval")
        for node in ast.walk(tree):
            if type(node).__name__ not in _ALLOWED_NODES:
                return "error: unsupported expression"
            if isinstance(node, ast.Name):
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
        op = _ALLOWED_OPS.get(type(node.op).__name__)
        if op is None:
            raise ValueError("unsupported")
        return op(_eval_ast(node.left), _eval_ast(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _ALLOWED_OPS.get(type(node.op).__name__)
        if op is None:
            raise ValueError("unsupported")
        return op(_eval_ast(node.operand))
    raise ValueError("unsupported")


def _tool_result(name: str, args: dict, corpus: dict) -> str:
    if name == "read_file":
        path = args.get("path", "")
        return corpus.get(path, "error: file not found")[:4000]
    if name == "list_dir":
        return "\n".join(sorted(corpus))
    if name == "search":
        query = args.get("query", "").lower()
        hits = [p for p in corpus if query in p.lower()][:5] or list(corpus)[:5]
        return "\n".join(f"{p}: {corpus[p][:200]}" for p in hits)
    if name == "calculate":
        return execute_calculate(args.get("expression", ""))
    return "ok"


async def _emit_lines(on_output, *lines: str) -> None:
    """Await on_output for each line, skipping empty/None entries."""
    if on_output is None:
        return
    for line in lines:
        if line:
            await on_output("line", line)


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
                "tool_choice": "required",
                "max_tokens": 64,
            })
            resp.raise_for_status()
            data = resp.json()
            msg = (((data.get("choices") or [{}])[0] or {}).get("message") or {})
            return bool(msg.get("tool_calls"))
        except Exception:
            return False


async def run_agent_session(base_url, model, steps, max_tokens, task,
                            on_output=None, request_timeout=120.0, transport=None,
                            tier="medium", fill_tokens=0, decide=None,
                            session_timeout_s=None):
    """Run a plan→act agent session. Returns serving-throughput metrics plus a
    transcript of the whole exchange.

    ``fill_tokens`` injects a deterministic filler blob into the initial prompt
    so the prefill is genuinely heavy for the chosen ctx tier. ``tier`` selects
    the thinking intensity (low/medium/heavy).

    ``decide`` is an optional async callable invoked before each Phase-2 ACT
    branch: ``await decide(step, proposed_tool, proposed_args, tool_options) ->
    (tool, args)``. When provided, the harness pauses and waits for the caller
    (the user) to pick the branch; otherwise it executes the model's own
    recommendation (legacy auto behaviour).

    ``session_timeout_s`` is a wall-clock budget for the model calls only. User
    decision wait time is intentionally NOT counted against it, so an
    interactive run can wait as long as the user needs without the harness
    cutting the session short."""
    scenario = AGENTIC_TASKS.get(task, AGENTIC_TASKS["codebase_refactor"])
    corpus = scenario["corpus"]
    thinking = AGENTIC_THINKING_TOKENS.get(tier, AGENTIC_THINKING_TOKENS["medium"])
    system_prompt = AGENTIC_SYSTEM_PROMPT + "\n" + thinking
    messages = [{"role": "system", "content": system_prompt}]
    if fill_tokens:
        messages.append({"role": "user", "content": _build_filler(fill_tokens)})
    messages.append({"role": "user", "content": scenario["prompt"]})
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_wall = 0.0
    latencies_ms = []
    tool_calls = 0
    plan_revisions = 0
    plan_retries = 0
    user_decisions = 0
    finished = False
    transcript = []
    kwargs = {"base_url": base_url, "timeout": request_timeout}
    if transport is not None:
        kwargs["transport"] = transport

    async def emit(*lines: str) -> None:
        await _emit_lines(on_output, *lines)

    async with httpx.AsyncClient(**kwargs) as client:
        step = 0
        while step < steps:
            if session_timeout_s is not None and total_wall >= session_timeout_s:
                break
            step += 1
            if step == 1:
                body = {
                    "model": model,
                    "messages": messages,
                    "tools": AGENTIC_TOOL_SCHEMAS,
                    "tool_choice": "required",
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
            choice = "forced submit_plan" if step == 1 else "ask user"
            await emit(f"── step {step}/{steps} ──",
                 f"CHOICE {choice}",
                 f"PROMPT {messages[-1]['content']}")
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
                await emit("THINK " + content[:200])
            # Resolve the branch to execute: the model recommends, the user (via
            # `decide`) may override it. Phase 1 forces a tool call via
            # tool_choice="required" and, if the model does not return
            # submit_plan on the first attempt, executes whatever it did return
            # and re-asks it to submit the plan (llama.cpp cannot force a
            # specific function by name).
            if step == 1:
                fn = (calls[0].get("function") or {}) if calls else {}
                proposed_name = fn.get("name") or "finish"
                try:
                    proposed_args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    proposed_args = {}
                if calls and proposed_name != "submit_plan":
                    await emit(f"PLAN RETRY → model returned {proposed_name}, "
                               "asking for submit_plan")
                    for call in calls:
                        cfn = call.get("function") or {}
                        cname = cfn.get("name") or "finish"
                        try:
                            cargs = json.loads(cfn.get("arguments") or "{}")
                        except json.JSONDecodeError:
                            cargs = {}
                        tool_calls += 1
                        result = _tool_result(cname, cargs, corpus)
                        await emit(f"TOOL {cname}({json.dumps(cargs)})",
                             f"RESULT {result[:200]}")
                        transcript.append(f"step {step}: {cname}({json.dumps(cargs)}) "
                                          f"-> {result[:80]}")
                        messages.append({"role": "tool",
                                         "tool_call_id": call.get("id", "call_0"),
                                         "content": result})
                    messages.append({"role": "user", "content": (
                        "Your first action was not submit_plan. Please call "
                        "submit_plan now with your step-by-step plan.")})
                    plan_retries += 1
                    body = {
                        "model": model,
                        "messages": messages,
                        "tools": AGENTIC_TOOL_SCHEMAS,
                        "tool_choice": "required",
                        "max_tokens": max_tokens,
                        "temperature": 0.2,
                        "stream": False,
                    }
                    await emit(f"PLAN RETRY PROMPT {messages[-1]['content']}")
                    rstart = time.monotonic()
                    rresp = await client.post("/v1/chat/completions", json=body)
                    rresp.raise_for_status()
                    rdata = rresp.json()
                    relapsed = time.monotonic() - rstart
                    latencies_ms.append(relapsed * 1000.0)
                    rusage = rdata.get("usage") or {}
                    total_prompt_tokens += int(rusage.get("prompt_tokens", 0) or 0)
                    total_completion_tokens += int(rusage.get("completion_tokens", 0) or 0)
                    total_wall += relapsed
                    rmsg = (((rdata.get("choices") or [{}])[0] or {}).get("message") or {})
                    rcontent = rmsg.get("content") or ""
                    rcalls = rmsg.get("tool_calls") or []
                    if rcontent:
                        messages.append({"role": "assistant", "content": rcontent})
                        await emit("THINK " + rcontent[:200])
                    rfn = (rcalls[0].get("function") or {}) if rcalls else {}
                    proposed_name = rfn.get("name") or "finish"
                    try:
                        proposed_args = json.loads(rfn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        proposed_args = {}
                    calls = rcalls
                    content = rcontent
                name, args = proposed_name, proposed_args
            elif calls:
                fn = calls[0].get("function") or {}
                proposed_name = fn.get("name") or "finish"
                try:
                    proposed_args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    proposed_args = {}
                tool_options = [s["function"]["name"] for s in AGENTIC_TOOL_SCHEMAS]
                if decide is not None:
                    await emit(f"DECISION NEEDED → recommended {proposed_name}")
                    name, args = await decide(step, proposed_name, proposed_args, tool_options)
                    user_decisions += 1
                    await emit(f"DECISION → {name}({json.dumps(args)})")
                else:
                    name, args = proposed_name, proposed_args
                calls = [{"id": "call_user", "type": "function",
                          "function": {"name": name, "arguments": json.dumps(args)}}]
                content = None
            else:
                name, args = "finish", {"answer": content or "done"}
                calls = [{"id": "call_finish", "type": "function",
                          "function": {"name": "finish", "arguments": json.dumps(args)}}]
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
                    await emit("FINISH " + str(args.get("answer", "")))
                    transcript.append(f"step {step}: finish")
                    messages.append({"role": "tool", "tool_call_id": call.get("id", "call_0"),
                                     "content": "finished"})
                    break
                result = _tool_result(name, args, corpus)
                if name == "submit_plan":
                    if step > 1:
                        plan_revisions += 1
                        await emit(f"PLAN revised: {json.dumps(args.get('steps', []))}")
                    else:
                        await emit(f"PLAN submitted: {json.dumps(args.get('steps', []))}")
                else:
                    await emit(f"TOOL {name}({json.dumps(args)})",
                         f"RESULT {result[:200]}")
                transcript.append(f"step {step}: {name}({json.dumps(args)}) -> {result[:80]}")
                messages.append({"role": "tool", "tool_call_id": call.get("id", "call_0"),
                                 "content": result})
            await emit(f"BRANCH → {name}")
            await emit(f"step {step}/{steps}: prompt {p_tok} tok + {c_tok} tok in {elapsed:.1f}s")
            if finished:
                break
    if not finished:
        await emit(f"BUDGET exhausted after {step} steps")
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
        "plan_retries": plan_retries,
        "user_decisions": user_decisions,
        "avg_latency_ms": avg_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_wall_s": total_wall,
        "finished": finished,
        "transcript": transcript,
    }
