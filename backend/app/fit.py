_ONE_GB = 1024 ** 3

# KV-cache bytes ≈ 2 bytes × 2 (K+V) × ctx × layers × heads × hidden-per-head
_KV_PER_TOKEN_BYTES = 4.0


def _kv_cache_bytes(ctx: int, layers: int, heads: int, hidden: int) -> float:
    per_head = hidden / heads
    return _KV_PER_TOKEN_BYTES * ctx * layers * heads * per_head


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
