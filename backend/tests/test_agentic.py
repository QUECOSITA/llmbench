import json

import httpx
import pytest

from app.agentic import (AGENTIC_DEFAULT_MAX_TOKENS, AGENTIC_DEFAULT_STEPS,
                         AGENTIC_TASKS, AGENTIC_TOOL_SCHEMAS, DEFAULT_USER_PROMPT,
                         agentic_request_timeout, agentic_session_timeout,
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
        if body.get("tool_choice") == "required":
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
    assert requests[0]["tool_choice"] == "required"


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
        if body.get("tool_choice") == "required":
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


def _workload_handler():
    def handler(request):
        body = json.loads(request.content)
        if body.get("tool_choice") == "required":
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [_tool_call("submit_plan", {"steps": ["a"]})]}
        else:
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [_tool_call("search", {"query": "x"})]}
        return httpx.Response(200, json=_resp(msg))
    return handler


@pytest.mark.asyncio
async def test_run_agent_session_decide_overrides_branch(monkeypatch):
    monkeypatch.setattr("app.agentic.time.monotonic", FakeClock())
    decisions = []

    async def decide(step, proposed_tool, proposed_args, tool_options):
        decisions.append((step, proposed_tool))
        return ("read_file", {"path": "/repo/main.py"})

    transport = httpx.MockTransport(_workload_handler())
    result = await run_agent_session(
        base_url="http://127.0.0.1:9", model="m", steps=3, max_tokens=4096,
        task="codebase_refactor", transport=transport, decide=decide)
    assert result["status"] == "ok"
    assert decisions, "decide should have been called on Phase-2 branches"
    assert all(step >= 2 for step, _ in decisions)
    assert result["user_decisions"] == len(decisions)


@pytest.mark.asyncio
async def test_run_agent_session_injects_filler_and_thinking(monkeypatch):
    monkeypatch.setattr("app.agentic.time.monotonic", FakeClock())
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("tool_choice") == "required":
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [_tool_call("submit_plan", {"steps": ["a"]})]}
        else:
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [_tool_call("finish", {"answer": "ok"})]}
        return httpx.Response(200, json=_resp(msg))

    transport = httpx.MockTransport(handler)
    await run_agent_session(
        base_url="http://127.0.0.1:9", model="m", steps=3, max_tokens=4096,
        task="codebase_refactor", transport=transport, tier="heavy",
        fill_tokens=65536)  # heavy ctx 131072 // 2
    first = requests[0]["messages"]
    sys_prompt = first[0]["content"]
    # Filler is a one-time user message, NOT the system prompt.
    assert "synthetic filler" not in sys_prompt
    assert any("synthetic filler" in (m.get("content") or "")
               for m in first if m["role"] == "user")
    # Bounded heavy thinking target present in the system prompt.
    assert "~320 tokens" in sys_prompt
    # Filler sent once on step 1, not re-injected on later steps.
    def filler_chars(body):
        return sum(len(m.get("content") or "")
                   for m in body["messages"]
                   if "synthetic filler" in (m.get("content") or ""))
    assert filler_chars(requests[0]) > 100000
    # Filler stays a single message in the growing context — it is not duplicated
    # or re-appended on later steps (constant size, not growing with each step).
    assert filler_chars(requests[1]) == filler_chars(requests[0])


def test_fill_tokens_half_ctx():
    from app.agentic import AGENTIC_TIERS
    for tier, spec in AGENTIC_TIERS.items():
        assert spec["fill_tokens"] == spec["ctx_size"] // 2


def test_agentic_request_timeout_scales_with_tier():
    # Medium tier injects 32k filler tokens; at a conservative 20 tps prefill
    # that alone is ~1600s, so the derived per-request timeout must comfortably
    # exceed the flat 300s default that caused the original failure.
    t = agentic_request_timeout("medium", 8192)
    assert t >= 3600
    # Heavier tier => larger workload => larger per-request timeout.
    assert agentic_request_timeout("heavy", 8192) > t
    assert agentic_request_timeout("low", 4096) < t
    # Unknown tier falls back to the default (medium) sizing.
    assert agentic_request_timeout("bogus", 8192) == t


def test_agentic_session_timeout_scales_with_steps():
    per = agentic_request_timeout("medium", 8192)
    assert agentic_session_timeout("medium", 1, 8192) == per
    assert agentic_session_timeout("medium", 10, 8192) == per * 10


@pytest.mark.asyncio
async def test_run_agent_session_session_budget_excludes_decide(monkeypatch):
    monkeypatch.setattr("app.agentic.time.monotonic", FakeClock())
    # Each model call advances the fake clock by 1s; budget of 1.0 should allow
    # only a couple of model calls but the decide wait is free.

    async def decide(step, proposed_tool, proposed_args, tool_options):
        return ("read_file", {"path": "a.py"})

    def handler(request):
        body = json.loads(request.content)
        if body.get("tool_choice") == "required":
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [_tool_call("submit_plan", {"steps": ["a"]})]}
        else:
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [_tool_call("read_file", {"path": "a.py"})]}
        return httpx.Response(200, json=_resp(msg))

    transport = httpx.MockTransport(handler)
    result = await run_agent_session(
        base_url="http://127.0.0.1:9", model="m", steps=10, max_tokens=4096,
        task="codebase_refactor", transport=transport, decide=decide,
        session_timeout_s=1.0)
    # With a 1s budget and 1s/model call, only the forced plan step should run
    # before the budget is exhausted at the next loop check.
    assert result["steps"] == 1


@pytest.mark.asyncio
async def test_run_agent_session_step1_retries_until_submit_plan(monkeypatch):
    monkeypatch.setattr("app.agentic.time.monotonic", FakeClock())
    requests = []
    attempts = {"n": 0}

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        attempts["n"] += 1
        if attempts["n"] == 1:
            # Step 1 first returns a non-plan tool; harness must retry to force submit_plan.
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [_tool_call("read_file", {"path": "/repo/main.py"})]}
        elif body.get("tool_choice") == "required":
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [_tool_call("submit_plan", {"steps": ["a"]})]}
        else:
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [_tool_call("finish", {"answer": "ok"})]}
        return httpx.Response(200, json=_resp(msg))

    transport = httpx.MockTransport(handler)
    result = await run_agent_session(
        base_url="http://127.0.0.1:9", model="m", steps=10, max_tokens=4096,
        task="codebase_refactor", transport=transport)
    assert result["status"] == "ok"
    assert result["finished"] is True
    assert result["steps"] == 2
    assert result["plan_retries"] == 1
    # The stray read_file from the failed step-1 attempt was executed (its tool
    # result is fed back into the retry) rather than silently dropped.
    assert requests[0]["tool_choice"] == "required"
    assert requests[1]["tool_choice"] == "required"
    retry_messages = requests[1]["messages"]
    assert retry_messages[-2]["role"] == "tool"
    assert "Your first action was not submit_plan" in retry_messages[-1]["content"]
