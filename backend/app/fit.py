_ONE_GB = 1024 ** 3

# KV-cache bytes ≈ 2 bytes × 2 (K+V) × ctx × layers × heads × hidden-per-head
_KV_PER_TOKEN_BYTES = 4.0

DEFAULT_ARCH = {"layers": 32, "heads": 32, "hidden": 4096, "max_ctx": 8192}

_CTX_FLAGS = {
    "llama.cpp": "--ctx-size",
    "vllm": "--max-model-len",
    "sglang": "--context-length",
}


def _kv_cache_bytes(ctx: int, layers: int, heads: int, hidden: int) -> float:
    per_head = hidden / heads
    return _KV_PER_TOKEN_BYTES * ctx * layers * heads * per_head


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fit_verdict(weights_bytes: float, vram_gb: float, ram_gb: float,
                ctx: int = 8192, layers: int = 32, heads: int = 32, hidden: int = 4096) -> dict:
    kv = _kv_cache_bytes(ctx, layers, heads, hidden)
    needed = weights_bytes + kv
    vram = vram_gb * _ONE_GB
    ram = ram_gb * _ONE_GB
    if vram <= 0:
        stage = "ram"
        warning = needed > ram * 0.8
    elif needed <= vram:
        stage = "gpu"
        warning = False
    elif needed <= vram + ram:
        stage = "ram_offload"
        warning = False
    else:
        stage = "no_fit"
        warning = True
    return {"stage": stage, "warning": warning, "needed_gb": round(needed / _ONE_GB, 1)}


def arch_from_config(config: dict | None) -> dict:
    arch = dict(DEFAULT_ARCH)
    if not config:
        return arch
    arch["layers"] = _to_int(config.get("num_hidden_layers"), arch["layers"])
    arch["heads"] = _to_int(config.get("num_attention_heads"), arch["heads"])
    arch["hidden"] = _to_int(config.get("hidden_size"), arch["hidden"])
    arch["max_ctx"] = _to_int(config.get("max_position_embeddings"), arch["max_ctx"])
    return arch


def config_fit(server_id: str, flags: dict[str, str], weights_bytes: float,
               vram_gb: float, ram_gb: float, arch: dict | None = None) -> dict:
    arch = arch or DEFAULT_ARCH
    ctx = _to_int(flags.get(_CTX_FLAGS.get(server_id, "")), arch["max_ctx"])
    layers = arch["layers"]
    heads = arch["heads"]
    hidden = arch["hidden"]
    kv = _kv_cache_bytes(ctx, layers, heads, hidden)
    needed = weights_bytes + kv
    weights_gb = round(weights_bytes / _ONE_GB, 1)
    kv_gb = round(kv / _ONE_GB, 1)
    needed_gb = round(needed / _ONE_GB, 1)
    vram = vram_gb * _ONE_GB
    ram = ram_gb * _ONE_GB

    stage = "no_fit"
    if server_id == "llama.cpp":
        ngl = _to_int(flags.get("--n-gpu-layers"), layers)
        if ngl >= layers:
            stage = "gpu" if needed <= vram else "no_fit"
        elif ngl <= 0:
            stage = "cpu" if needed <= ram else "no_fit"
        else:
            gpu_share = weights_bytes * (ngl / layers) + kv
            if gpu_share <= vram and needed <= vram + ram:
                stage = "offload"
    elif server_id in ("vllm", "sglang"):
        fraction = _to_float(
            flags.get("--gpu-memory-utilization" if server_id == "vllm" else "--mem-fraction-static"),
            0.9,
        )
        if needed <= vram * fraction:
            stage = "gpu"

    labels = {
        "gpu": "FITS VRAM",
        "offload": "OFFLOADED",
        "cpu": "CPU ONLY",
        "no_fit": "NO FIT",
    }
    return {
        "stage": stage,
        "label": labels[stage],
        "fits_vram": stage == "gpu",
        "offloaded": stage == "offload",
        "needed_gb": needed_gb,
        "kv_gb": kv_gb,
        "weights_gb": weights_gb,
    }
