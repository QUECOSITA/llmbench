import platform
from app.hardware import detect_hardware, parse_nvidia_smi


def test_parse_nvidia_smi():
    sample = (
        "GPU 0: NVIDIA GeForce RTX 4090 (UUID: GPU-xxx)\n"
        "    Memory Usage\n"
        "    Utilization\n"
    )
    name, vram = parse_nvidia_smi(sample)
    assert name == "NVIDIA GeForce RTX 4090"
    assert vram == 0  # not parsed from this fixture


def test_detect_hardware_shape():
    hw = detect_hardware()
    assert "arch" in hw and "cpu_cores" in hw and "ram_total_gb" in hw
    assert "gpu_name" in hw and "gpu_vram_gb" in hw
    assert isinstance(hw["ram_total_gb"], float)


def test_detect_no_gpu(monkeypatch):
    monkeypatch.setattr("app.hardware._run_nvidia_smi", lambda: None)
    hw = detect_hardware()
    assert hw["gpu_name"] is None
    assert hw["gpu_vram_gb"] == 0.0
