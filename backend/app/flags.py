KEY_FLAGS = {
    "llama.cpp": ["--ctx-size", "--n-gpu-layers", "--batch-size", "--spec-type", "--spec-draft-n-max"],
    "vllm": ["--max-model-len", "--max-num-seqs", "--gpu-memory-utilization", "--enforce-eager"],
    "sglang": ["--context-length", "--max-running-requests", "--mem-fraction-static", "--tp-size"],
}

VALUE_POOLS = {
    "llama.cpp": {
        "--ctx-size": [2048, 4096, 8192, 16384],
        "--n-gpu-layers": [999, 40, 0],
        "--batch-size": [512, 2048],
        "--spec-type": ["draft-mtp", "none"],
        "--spec-draft-n-max": [2, 3],
    },
    "vllm": {
        "--max-model-len": [4096, 8192, 16384],
        "--max-num-seqs": [16, 32, 64],
        "--gpu-memory-utilization": [0.85, 0.9, 0.95],
        "--enforce-eager": ["", "--enforce-eager"],
    },
    "sglang": {
        "--context-length": [4096, 8192, 16384],
        "--max-running-requests": [16, 32, 64],
        "--mem-fraction-static": [0.85, 0.9],
        "--tp-size": [1],
    },
}

DEFAULTS = {
    "llama.cpp": {"--ctx-size": 4096, "--n-gpu-layers": 999, "--batch-size": 512,
                  "--spec-type": "draft-mtp", "--spec-draft-n-max": 2},
    "vllm": {"--max-model-len": 8192, "--max-num-seqs": 32, "--gpu-memory-utilization": 0.9, "--enforce-eager": ""},
    "sglang": {"--context-length": 8192, "--max-running-requests": 32, "--mem-fraction-static": 0.9, "--tp-size": 1},
}


def _gpu_util_for_vram(server_id: str, vram_gb: float) -> str:
    if server_id == "vllm":
        return str(round(min(0.95, max(0.5, 1.0 - 2.0 / vram_gb)), 2)) if vram_gb else "0.9"
    if server_id == "sglang":
        return str(round(min(0.9, max(0.5, 1.0 - 2.0 / vram_gb)), 2)) if vram_gb else "0.9"
    return ""


_SPEC_TYPE_ALIASES = {"mtp": "draft-mtp", "draft-mtp": "draft-mtp"}


def _baseline(server_id: str, readme_flags: dict[str, str], vram_gb: float) -> dict[str, str]:
    flags: dict[str, str] = {}
    for key, default in DEFAULTS[server_id].items():
        flags[key] = str(default)
    if server_id == "vllm":
        flags["--gpu-memory-utilization"] = _gpu_util_for_vram("vllm", vram_gb)
    if server_id == "sglang":
        flags["--mem-fraction-static"] = _gpu_util_for_vram("sglang", vram_gb)
    for flag, value in readme_flags.items():
        if flag == "--spec-type":
            value = _SPEC_TYPE_ALIASES.get(value, value)
        if flag in KEY_FLAGS[server_id] or flag not in DEFAULTS[server_id]:
            flags[flag] = value
    return flags


def generate_configs(server_id: str, readme_flags: dict[str, str], n: int, vram_gb: float) -> list[dict]:
    if server_id not in KEY_FLAGS:
        raise ValueError(f"unknown server {server_id}")
    base = _baseline(server_id, readme_flags, vram_gb)
    configs = [{"flags": dict(base)}]
    seen = {tuple(sorted(base.items()))}
    for key in KEY_FLAGS[server_id]:
        base_val = base[key]
        for val in VALUE_POOLS[server_id][key]:
            sv = str(val)
            if sv == base_val:
                continue
            cfg = dict(base)
            cfg[key] = sv
            signature = tuple(sorted(cfg.items()))
            if signature in seen:
                continue
            seen.add(signature)
            configs.append({"flags": cfg})
    return configs[:n]


def _flag_tokens(flags: dict[str, str]) -> list[str]:
    tokens: list[str] = []
    for flag, value in flags.items():
        tokens.append(flag)
        if value and value != flag:
            tokens.append(value)
    return tokens


def build_serving_command(server_id: str, repo_id: str, flags: dict[str, str], gguf_path: str | None = None) -> str:
    if server_id == "llama.cpp":
        cmd = ["llama-server"]
        if gguf_path:
            cmd += ["-m", gguf_path]
        cmd += _flag_tokens(flags)
        return " ".join(cmd)
    if server_id == "vllm":
        return "vllm serve " + repo_id + " " + " ".join(_flag_tokens(flags))
    if server_id == "sglang":
        return "python -m sglang.launch_server --model-path " + repo_id + " " + " ".join(_flag_tokens(flags))
    raise ValueError(f"unknown server {server_id}")
