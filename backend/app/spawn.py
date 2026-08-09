import os


def spawn_env() -> dict[str, str]:
    """Environment for spawned server/bench subprocesses.

    vLLM's V1 engine needs pinned-memory-backed UVA buffers; on WSL2 pinned
    memory is supported but disabled by default, so engine init fails with
    "RuntimeError: UVA is not available". The flag is a no-op outside WSL2,
    so set it unconditionally.
    """
    return {**os.environ, "VLLM_WSL2_ENABLE_PIN_MEMORY": "1"}
