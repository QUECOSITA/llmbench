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


class StepClock:
    """Monotonic clock that advances by a fixed increment each call, so a
    cooperative session budget can be exercised deterministically."""

    def __init__(self, inc=1.0):
        self.inc = inc
        self.t = 0.0

    def __call__(self):
        self.t += self.inc
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
async def test_run_agent_session_returns_partial_metrics_on_timeout(monkeypatch):
    monkeypatch.setattr("app.agentic.time.monotonic", StepClock(inc=1.0))

    def handler(request):
        return httpx.Response(200, json=_resp(
            {"role": "assistant", "content": None,
             "tool_calls": [_tool_call("read_file", {"path": "a.py"})]}))

    transport = httpx.MockTransport(handler)
    result = await run_agent_session(
        base_url="http://127.0.0.1:9", model="m", steps=10, max_tokens=4096,
        task="codebase_refactor", timeout_s=3.0, transport=transport)
    assert result["status"] == "ok"
    assert result["finished"] is False
    assert result["timed_out"] is True
    assert result["steps"] == 1
    assert result["tool_calls"] == 1
    assert result["total_prompt_tokens"] == 10
    assert result["total_completion_tokens"] == 4
    assert result["agentic_tps"] is not None


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
