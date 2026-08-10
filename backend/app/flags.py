KEY_FLAGS = {
    "llama.cpp": ["--ctx-size", "--n-gpu-layers", "--batch-size", "--spec-type", "--spec-draft-n-max"],
}

VALUE_POOLS = {
    "llama.cpp": {
        "--ctx-size": [2048, 4096, 8192, 16384],
        "--n-gpu-layers": [999, 40, 0],
        "--batch-size": [512, 2048],
        "--spec-type": ["draft-mtp", "none"],
        "--spec-draft-n-max": [2, 3],
    },
}

DEFAULTS = {
    "llama.cpp": {"--ctx-size": 4096, "--n-gpu-layers": 999, "--batch-size": 512,
                  "--spec-type": "draft-mtp", "--spec-draft-n-max": 2},
}


_SPEC_TYPE_ALIASES = {"mtp": "draft-mtp", "draft-mtp": "draft-mtp"}

_LLAMA_MODEL_FLAGS = {"-m", "-hf", "-hfr", "--hf-repo", "-hff", "--hf-file", "-hft", "--hf-token"}


def _baseline(server_id: str, readme_flags: dict[str, str], vram_gb: float) -> dict[str, str]:
    flags: dict[str, str] = {}
    for key, default in DEFAULTS[server_id].items():
        flags[key] = str(default)
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


def build_serving_command(server_id: str, repo_id: str, flags: dict[str, str],
                          gguf_filename: str | None = None,
                          gguf_path: str | None = None) -> str:
    if server_id == "llama.cpp":
        cmd = ["llama-server"]
        if gguf_filename:
            cmd += ["--hf-repo", repo_id, "--hf-file", gguf_filename]
        elif gguf_path:
            cmd += ["-m", gguf_path]
        if gguf_filename or gguf_path:
            flags = {k: v for k, v in flags.items() if k not in _LLAMA_MODEL_FLAGS}
        cmd += _flag_tokens(flags)
        return " ".join(cmd)
    raise ValueError(f"unknown server {server_id}")