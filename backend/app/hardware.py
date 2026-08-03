import os
import platform
import re
import subprocess

_GPU_RE = re.compile(r"GPU\s+\d+:\s+([^(\n]+)")


def _run_nvidia_smi() -> str | None:
    try:
        r = subprocess.run(["nvidia-smi", "-q"], capture_output=True, text=True, timeout=5)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def parse_nvidia_smi(smi_output: str) -> tuple[str | None, float]:
    name = None
    vram = 0.0
    m = _GPU_RE.search(smi_output)
    if m:
        name = m.group(1).strip()
    m = re.search(r"Total\s+:\s+(\d+)MiB", smi_output)
    if m:
        vram = int(m.group(1)) / 1024.0
    return name, vram


def _ram_total_gb() -> float:
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb / (1024 * 1024)
    except OSError:
        pass
    return 0.0


def _cpu_cores() -> int:
    return os.cpu_count() or 0


def detect_hardware() -> dict:
    smi = _run_nvidia_smi()
    gpu_name, gpu_vram = parse_nvidia_smi(smi) if smi else (None, 0.0)
    return {
        "arch": platform.machine(),
        "os": platform.system(),
        "cpu_name": platform.processor() or "",
        "cpu_cores": _cpu_cores(),
        "ram_total_gb": _ram_total_gb(),
        "gpu_name": gpu_name,
        "gpu_vram_gb": gpu_vram,
    }
