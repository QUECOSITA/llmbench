import json
import time
from pathlib import Path

import httpx

AGENTIC_DEFAULT_TURNS = 4
AGENTIC_DEFAULT_MAX_TOKENS = 16384

AGENTIC_SYSTEM_PROMPT = (
    "You are an expert software engineer working on a complex coding task. "
    "Think step by step, produce a complete and correct solution, and stop "
    "only when the task is fully solved."
)

DEFAULT_USER_PROMPT = (
    "Write a complete Python module that implements an in-memory LRU cache "
    "with thread safety, a type-hinted public API, and unit tests."
)


def load_workload_prompts(workload_file: str | Path) -> list[str]:
    prompts = []
    try:
        with open(workload_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    prompts.append(json.loads(line)["prompt"])
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        return []
    return prompts


async def run_agentic_session(base_url, model, turns, max_tokens, prompts,
                              on_output=None, request_timeout=120.0,
                              transport=None):
    """Run a multi-turn chat session that grows the conversation each turn.
    Returns effective tokens/sec across the whole session (includes every
    prefill), plus per-turn token/timing data."""
    messages = [{"role": "system", "content": AGENTIC_SYSTEM_PROMPT}]
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_wall = 0.0
    per_turn = []
    kwargs = {"base_url": base_url, "timeout": request_timeout}
    if transport is not None:
        kwargs["transport"] = transport
    async with httpx.AsyncClient(**kwargs) as client:
        for i in range(turns):
            user = prompts[i % len(prompts)] if prompts else DEFAULT_USER_PROMPT
            messages.append({"role": "user", "content": user})
            start = time.monotonic()
            resp = await client.post("/v1/chat/completions", json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.2,
                "stream": False,
            })
            resp.raise_for_status()
            data = resp.json()
            elapsed = time.monotonic() - start
            usage = data.get("usage") or {}
            p_tok = int(usage.get("prompt_tokens", 0) or 0)
            c_tok = int(usage.get("completion_tokens", 0) or 0)
            content = (((data.get("choices") or [{}])[0] or {}).get("message") or {}).get("content") or ""
            messages.append({"role": "assistant", "content": content})
            total_prompt_tokens += p_tok
            total_completion_tokens += c_tok
            total_wall += elapsed
            per_turn.append({
                "turn": i + 1,
                "prompt_tokens": p_tok,
                "completion_tokens": c_tok,
                "elapsed_s": elapsed,
            })
            if on_output is not None:
                await on_output("line", (
                    f"turn {i + 1}/{turns}: prompt {p_tok} tok + "
                    f"{c_tok} tok in {elapsed:.1f}s"
                ))
    return {
        "agentic_tps": total_completion_tokens / total_wall if total_wall > 0 else None,
        "prompt_processing_tps": None,
        "decode_tps": None,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_wall_s": total_wall,
        "turns": turns,
        "per_turn": per_turn,
    }
