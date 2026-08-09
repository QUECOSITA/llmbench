import importlib.metadata
import shutil
import subprocess
import sys
from pathlib import Path

from app.hardware import detect_hardware
from app.servers import SERVERS, _module_importable, resolve_bench_binary

_USAGE = "usage: python -m app.install llama.cpp"


def server_detection(server_id: str) -> dict:
    """Report whether a serving server is installed and its version. This is a
    side-effect-free probe: it never installs anything."""
    if server_id not in SERVERS:
        raise ValueError(f"unknown server '{server_id}'; known: {', '.join(SERVERS)}")
    module = SERVERS[server_id].get("module")
    if module:
        installed = _module_importable(module)
    else:
        installed = resolve_bench_binary(server_id) is not None
    version = None
    if module and installed:
        try:
            version = importlib.metadata.version(module)
        except importlib.metadata.PackageNotFoundError:
            version = None
    return {"server_id": server_id, "installed": installed, "version": version}


def _nvidia_driver_version() -> str | None:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0].strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _disk_free_gb() -> float:
    try:
        return shutil.disk_usage(str(Path.home())).free / (1024 ** 3)
    except OSError:
        return 0.0


def requirements_for(server_id: str, hardware: dict) -> list[str]:
    """Human-readable conditions the system must meet to install/run a server."""
    out: list[str] = []
    gpu = hardware.get("gpu_name")
    driver = hardware.get("nvidia_driver")
    if server_id == "llama.cpp":
        if not gpu:
            out.append("CPU-only build is fine; a CUDA build requires an NVIDIA GPU")
        elif not driver:
            out.append("NVIDIA driver version not detected — install a CUDA-capable driver for the CUDA build")
    return out


def verify_system(server_id: str) -> dict:
    """Collect system facts relevant to installing server_id. Read-only."""
    if server_id not in SERVERS:
        raise ValueError(f"unknown server '{server_id}'; known: {', '.join(SERVERS)}")
    hw = detect_hardware()
    pip = shutil.which("pip") is not None or shutil.which("pip3") is not None
    driver = _nvidia_driver_version()
    facts = dict(hw)
    facts["nvidia_driver"] = driver
    return {
        "server_id": server_id,
        "os": hw["os"],
        "arch": hw["arch"],
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_ok": sys.version_info >= (3, 11),
        "pip_available": pip,
        "gpu_name": hw["gpu_name"],
        "gpu_vram_gb": hw["gpu_vram_gb"],
        "nvidia_driver": driver,
        "disk_free_gb": _disk_free_gb(),
        "requirements": requirements_for(server_id, facts),
    }


def install_commands(server_id: str) -> list[str]:
    """The commands that install server_id. These are printed, never executed by
    the app; the agent runs them after the user approves."""
    if server_id == "llama.cpp":
        return [
            "git clone https://github.com/ggml-org/llama.cpp $HOME/llama.cpp",
            "cmake -B $HOME/llama.cpp/build -S $HOME/llama.cpp -DGGML_CUDA=on",
            "cmake --build $HOME/llama.cpp/build --config Release -j",
        ]
    raise ValueError(f"unknown server '{server_id}'; known: {', '.join(SERVERS)}")


def verify_install(server_id: str) -> dict:
    d = server_detection(server_id)
    d["verified"] = d["installed"]
    return d


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    server_id = args[0]
    if server_id not in SERVERS:
        print(f"unknown server '{server_id}'; known: {', '.join(SERVERS)}")
        return 2
    det = server_detection(server_id)
    state = f"installed (version {det['version']})" if det["installed"] else "NOT installed"
    print(f"[detect] {server_id}: {state}")
    info = verify_system(server_id)
    print(f"[system] {info['os']} {info['arch']} · python {info['python_version']}"
          f" · pip {'yes' if info['pip_available'] else 'no'} ·"
          f" gpu {info['gpu_name'] or 'none'}"
          f"{f' ({info['gpu_vram_gb']:.0f}GB)' if info['gpu_vram_gb'] else ''}"
          f" · driver {info['nvidia_driver'] or 'none'}"
          f" · free disk {info['disk_free_gb']:.1f}GB")
    if info["requirements"]:
        print("[requirements]")
        for req in info["requirements"]:
            print(f"  - {req}")
    print("[install] (review with the user before running)")
    for cmd in install_commands(server_id):
        print(f"  {cmd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
