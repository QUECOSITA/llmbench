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

    async def emit(*lines: str) -> None:
        await _emit_lines(on_output, *lines)

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
            choice = "forced submit_plan" if step == 1 else "auto"
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
            if content:
                await emit("THINK " + content[:200])
            if calls:
                branch = calls[0].get("function") or {}
                await emit(f"BRANCH → {branch.get('name', '?')}")
            else:
                await emit("THINK (tool call only)")
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
        "avg_latency_ms": avg_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_wall_s": total_wall,
        "finished": finished,
        "transcript": transcript,
    }
