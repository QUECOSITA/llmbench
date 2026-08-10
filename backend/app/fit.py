_ONE_GB = 1024 ** 3

# KV-cache bytes ≈ 2 bytes × 2 (K+V) × ctx × layers × heads × hidden-per-head
_KV_PER_TOKEN_BYTES = 4.0

DEFAULT_ARCH = {"layers": 32, "heads": 32, "hidden": 4096, "max_ctx": 8192}

# Reference parameter count DEFAULT_ARCH represents (~7B). Used to scale the KV
# estimate when the real architecture is unknown (GGUF repos usually ship no
# config.json): assume fp16 weights (~2 bytes/param) to back out a param count,
# then scale DEFAULT_ARCH's KV cache by (params / 7B)**(2/3), matching how layer
# count and hidden width grow with model size.
_REF_PARAMS = 7_000_000_000

_CTX_FLAGS = {
    "llama.cpp": "--ctx-size",
}


def _kv_cache_bytes(ctx: int, layers: int, heads: int, hidden: int) -> float:
    per_head = hidden / heads
    return _KV_PER_TOKEN_BYTES * ctx * layers * heads * per_head


def _estimate_kv_bytes(weights_bytes: float, ctx: int) -> float:
    """Estimate KV-cache bytes for an unknown architecture.

    The fixed 7B-scale default would otherwise dwarf small models (e.g. ~4 GB KV
    vs. a 350M model's 0.7 GB of weights). Scale it with the model's own size.
    """
    params = max(weights_bytes / 2.0, 1.0)
    scale = (params / _REF_PARAMS) ** (2.0 / 3.0)
    return _kv_cache_bytes(
        ctx, DEFAULT_ARCH["layers"], DEFAULT_ARCH["heads"], DEFAULT_ARCH["hidden"]
    ) * scale


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
                ctx: int = DEFAULT_ARCH["max_ctx"], arch: dict | None = None) -> dict:
    if arch is not None:
        kv = _kv_cache_bytes(arch["max_ctx"], arch["layers"], arch["heads"], arch["hidden"])
    else:
        kv = _estimate_kv_bytes(weights_bytes, ctx)
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
    if arch is not None:
        ctx = _to_int(flags.get(_CTX_FLAGS.get(server_id, "")), arch["max_ctx"])
        layers = arch["layers"]
        heads = arch["heads"]
        hidden = arch["hidden"]
        kv = _kv_cache_bytes(ctx, layers, heads, hidden)
    else:
        ctx = _to_int(flags.get(_CTX_FLAGS.get(server_id, "")), DEFAULT_ARCH["max_ctx"])
        layers = DEFAULT_ARCH["layers"]
        heads = DEFAULT_ARCH["heads"]
        hidden = DEFAULT_ARCH["hidden"]
        kv = _estimate_kv_bytes(weights_bytes, ctx)
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