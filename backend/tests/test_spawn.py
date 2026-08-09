from app.spawn import spawn_env


def test_spawn_env_includes_wsl2_pin_memory(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/home/test")
    env = spawn_env()
    assert env["VLLM_WSL2_ENABLE_PIN_MEMORY"] == "1"
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/home/test"


def test_spawn_env_preserves_existing_value(monkeypatch):
    monkeypatch.setenv("VLLM_WSL2_ENABLE_PIN_MEMORY", "0")
    assert spawn_env()["VLLM_WSL2_ENABLE_PIN_MEMORY"] == "1"
