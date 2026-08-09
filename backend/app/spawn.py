import os


def spawn_env() -> dict[str, str]:
    """Environment for spawned server/bench subprocesses."""
    return dict(os.environ)
