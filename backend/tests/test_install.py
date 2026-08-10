import pytest

from app.install import (server_detection, verify_system, requirements_for,
                         install_commands, main)


def test_server_detection_unknown_server():
    with pytest.raises(ValueError):
        server_detection("nope")


def test_server_detection_llama_uses_binary(monkeypatch):
    monkeypatch.setattr("app.install._module_importable", lambda name: True)
    monkeypatch.setattr("app.install.resolve_bench_binary",
                        lambda server_id: "/usr/bin/llama-bench" if server_id == "llama.cpp" else None)
    d = server_detection("llama.cpp")
    assert d["installed"] is True


def test_verify_system_returns_expected_keys(monkeypatch):
    monkeypatch.setattr("app.install.detect_hardware", lambda: {
        "os": "Linux", "arch": "x86_64", "gpu_name": "NVIDIA GeForce RTX 5080",
        "gpu_vram_gb": 16.0, "cpu_cores": 16, "ram_total_gb": 64.0,
    })
    monkeypatch.setattr("app.install._nvidia_driver_version", lambda: "610.88")
    monkeypatch.setattr("app.install._disk_free_gb", lambda: 123.4)
    s = verify_system("llama.cpp")
    assert s["python_version"].split(".")[0] == "3"
    assert s["pip_available"] is True
    assert s["gpu_name"] == "NVIDIA GeForce RTX 5080"
    assert s["nvidia_driver"] == "610.88"
    assert s["disk_free_gb"] == 123.4
    assert isinstance(s["requirements"], list)


def test_verify_system_no_gpu(monkeypatch):
    monkeypatch.setattr("app.install.detect_hardware", lambda: {
        "os": "Linux", "arch": "x86_64", "gpu_name": None, "gpu_vram_gb": 0.0,
    })
    monkeypatch.setattr("app.install._nvidia_driver_version", lambda: None)
    monkeypatch.setattr("app.install._disk_free_gb", lambda: 50.0)
    s = verify_system("llama.cpp")
    assert s["gpu_name"] is None
    assert any("CUDA" in r or "llama.cpp" in r for r in s["requirements"])


def test_requirements_for_llama_no_gpu():
    reqs = requirements_for("llama.cpp", {"gpu_name": None, "gpu_vram_gb": 0.0})
    assert any("CPU-only build is fine" in r and "CUDA" in r for r in reqs)
    assert not any("NVIDIA GPU required" in r for r in reqs)


def test_install_commands_llama():
    cmds = install_commands("llama.cpp")
    assert any("cmake" in c for c in cmds)
    assert any("llama.cpp" in c for c in cmds)


def test_install_commands_unknown():
    with pytest.raises(ValueError):
        install_commands("nope")


def test_main_unknown_server(capsys):
    assert main(["nope"]) == 2
    assert "unknown server" in capsys.readouterr().out


def test_main_prints_llama_detection_and_commands(capsys, monkeypatch):
    monkeypatch.setattr("app.install._module_importable", lambda name: False)
    monkeypatch.setattr("app.install.resolve_bench_binary",
                        lambda server_id, bin_dir=None: None)
    monkeypatch.setattr("app.install.detect_hardware", lambda: {
        "os": "Linux", "arch": "x86_64", "gpu_name": None, "gpu_vram_gb": 0.0,
    })
    monkeypatch.setattr("app.install._nvidia_driver_version", lambda: None)
    monkeypatch.setattr("app.install._disk_free_gb", lambda: 50.0)
    rc = main(["llama.cpp"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "NOT installed" in out
    assert "cmake" in out and "llama.cpp" in out
