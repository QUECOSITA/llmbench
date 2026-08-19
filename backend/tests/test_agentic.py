import json

import httpx
import pytest

from app.agentic import (AGENTIC_DEFAULT_MAX_TOKENS, AGENTIC_DEFAULT_TURNS,
                         AGENTIC_SYSTEM_PROMPT, DEFAULT_USER_PROMPT,
                         load_workload_prompts, run_agentic_session)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 1.0
        return self.t


def _handler(requests):
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        n_msgs = len(body["messages"])
        return httpx.Response(200, json={
            "id": "x",
            "object": "chat.completion",
            "created": 1,
            "model": body.get("model"),
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": f"step {n_msgs}"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": n_msgs * 10, "completion_tokens": 4,
                      "total_tokens": n_msgs * 10 + 4},
        })
    return handler


@pytest.mark.asyncio
async def test_run_agentic_session_reports_effective_tps(monkeypatch):
    monkeypatch.setattr("app.agentic.time.monotonic", FakeClock())
    requests = []
    transport = httpx.MockTransport(_handler(requests))
    result = await run_agentic_session(
        base_url="http://127.0.0.1:9", model="model.gguf",
        turns=4, max_tokens=16384, prompts=["task a", "task b"],
        transport=transport)
    assert result["agentic_tps"] == 4.0
    assert result["total_completion_tokens"] == 16
    assert result["total_wall_s"] == 4.0
    assert result["turns"] == 4
    assert result["prompt_processing_tps"] is None
    assert result["decode_tps"] is None
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_run_agentic_session_grows_conversation(monkeypatch):
    requests = []
    transport = httpx.MockTransport(_handler(requests))
    await run_agentic_session("http://x", "m", 3, 128,
                              ["t1", "t2", "t3"], transport=transport)
    assert requests[0]["messages"][0]["role"] == "system"
    assert requests[0]["messages"][0]["content"] == AGENTIC_SYSTEM_PROMPT
    assert len(requests[0]["messages"]) == 2
    assert len(requests[1]["messages"]) == 4
    assert len(requests[2]["messages"]) == 6
    assert requests[1]["messages"][-1]["role"] == "user"


@pytest.mark.asyncio
async def test_run_agentic_session_empty_workload_uses_default(monkeypatch):
    requests = []
    transport = httpx.MockTransport(_handler(requests))
    await run_agentic_session("http://x", "m", 1, 128, [], transport=transport)
    assert requests[0]["messages"][-1]["content"] == DEFAULT_USER_PROMPT
    assert requests[0]["max_tokens"] == 128


@pytest.mark.asyncio
async def test_run_agentic_session_emits_per_turn_output(monkeypatch):
    lines = []
    transport = httpx.MockTransport(_handler([]))

    async def on_output(kind, text):
        lines.append((kind, text))

    await run_agentic_session("http://x", "m", 4, 128,
                              ["a", "b", "c", "d"], on_output=on_output,
                              transport=transport)
    assert len(lines) == 4
    assert lines[0][0] == "line"
    assert "turn 1/4" in lines[0][1]


def test_load_workload_prompts_reads_jsonl(tmp_path):
    p = tmp_path / "p.jsonl"
    p.write_text('{"prompt": "a"}\n\n{"prompt": "b"}\nnot-json\n{"other": "x"}\n')
    assert load_workload_prompts(p) == ["a", "b"]


def test_load_workload_prompts_missing_file_returns_empty(tmp_path):
    assert load_workload_prompts(tmp_path / "nope.jsonl") == []
