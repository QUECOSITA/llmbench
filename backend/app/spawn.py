import os

# The hf CLI auto-detects agent mode from these universal env vars at import
# time and then globally disables tqdm progress bars, so `hf download` emits
# no streaming output. Strip them so spawned subprocesses (download, prune,
# serving, bench) always run in human mode with progress bars.
_AGENT_DETECTION_ENV_VARS = ("AGENT", "AI_AGENT")


def spawn_env() -> dict[str, str]:
    """Environment for spawned server/bench subprocesses."""
    env = dict(os.environ)
    for var in _AGENT_DETECTION_ENV_VARS:
        env.pop(var, None)
    return env
