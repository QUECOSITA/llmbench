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
