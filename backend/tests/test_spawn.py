from app.spawn import spawn_env


def test_spawn_env_returns_environment_copy(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/home/test")
    env = spawn_env()
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/home/test"


def test_spawn_env_does_not_set_vllm_pin_memory(monkeypatch):
    monkeypatch.delenv("VLLM_WSL2_ENABLE_PIN_MEMORY", raising=False)
    env = spawn_env()
    assert "VLLM_WSL2_ENABLE_PIN_MEMORY" not in env


def test_spawn_env_strips_agent_detection_vars(monkeypatch):
    monkeypatch.setenv("AGENT", "1")
    monkeypatch.setenv("AI_AGENT", "claude")
    monkeypatch.setenv("HOME", "/home/test")
    env = spawn_env()
    assert "AGENT" not in env
    assert "AI_AGENT" not in env
    assert env["HOME"] == "/home/test"


def test_spawn_env_keeps_unrelated_vars(monkeypatch):
    monkeypatch.setenv("AGENT", "1")
    monkeypatch.setenv("LLMBENCH_SOMETHING", "kept")
    env = spawn_env()
    assert env["LLMBENCH_SOMETHING"] == "kept"
