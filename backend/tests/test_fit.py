from app.fit import config_fit, arch_from_config, DEFAULT_ARCH, fit_verdict

ARCH = {"layers": 32, "heads": 32, "hidden": 4096, "max_ctx": 8192}


def test_fits_in_vram():
    verdict = fit_verdict(weights_bytes=10_000_000_000, vram_gb=24.0, ram_gb=64.0, arch=ARCH)
    assert verdict["stage"] == "gpu"


def test_offload_to_ram():
    verdict = fit_verdict(weights_bytes=40_000_000_000, vram_gb=24.0, ram_gb=64.0, arch=ARCH)
    assert verdict["stage"] == "ram_offload"


def test_warns_when_does_not_fit():
    verdict = fit_verdict(weights_bytes=100_000_000_000, vram_gb=24.0, ram_gb=64.0, arch=ARCH)
    assert verdict["stage"] == "no_fit"
    assert verdict["warning"] is True


def test_cpu_only_arch():
    verdict = fit_verdict(weights_bytes=10_000_000_000, vram_gb=0.0, ram_gb=64.0, arch=ARCH)
    assert verdict["stage"] == "ram"


def test_fit_verdict_unknown_arch_scales_kv_with_model_size():
    """Without a config.json (typical GGUF repos) the KV estimate must scale
    with the model's own size instead of assuming a 7B-scale default, whose
    ~4 GB KV cache dwarfs small models."""
    small = fit_verdict(weights_bytes=711_483_104, vram_gb=24.0, ram_gb=64.0)  # ~350M F16
    assert small["needed_gb"] < 2.0, f"small model showed {small['needed_gb']} GB needed"
    assert small["stage"] == "gpu"

    big = fit_verdict(weights_bytes=12_500_000_000, vram_gb=24.0, ram_gb=64.0)  # ~6B fp16
    assert 14.0 < big["needed_gb"] < 17.0, f"7B-scale model showed {big['needed_gb']} GB needed"


def test_fit_verdict_unknown_arch_kv_scales_with_ctx():
    low = fit_verdict(weights_bytes=711_483_104, vram_gb=24.0, ram_gb=64.0)
    high = fit_verdict(weights_bytes=711_483_104, vram_gb=24.0, ram_gb=64.0, ctx=32768)
    assert high["needed_gb"] > low["needed_gb"]


def test_arch_from_config():
    arch = arch_from_config({"num_hidden_layers": 40, "num_attention_heads": 64,
                             "hidden_size": 8192, "max_position_embeddings": 32768})
    assert arch == {"layers": 40, "heads": 64, "hidden": 8192, "max_ctx": 32768}


def test_arch_from_config_defaults():
    assert arch_from_config(None) == DEFAULT_ARCH
    assert arch_from_config({"num_hidden_layers": 40}) == {
        "layers": 40, "heads": 32, "hidden": 4096, "max_ctx": 8192}


def test_config_fit_llama_full_gpu():
    f = config_fit("llama.cpp", {"--ctx-size": "8192", "--n-gpu-layers": "999"}, 10e9, 24.0, 64.0, ARCH)
    assert f["stage"] == "gpu"
    assert f["fits_vram"] is True
    assert f["offloaded"] is False
    assert f["label"] == "FITS VRAM"


def test_config_fit_llama_full_gpu_no_fit():
    f = config_fit("llama.cpp", {"--n-gpu-layers": "999"}, 40e9, 24.0, 64.0, ARCH)
    assert f["stage"] == "no_fit"
    assert f["label"] == "NO FIT"


def test_config_fit_llama_cpu_only():
    f = config_fit("llama.cpp", {"--n-gpu-layers": "0"}, 10e9, 24.0, 64.0, ARCH)
    assert f["stage"] == "cpu"
    assert f["label"] == "CPU ONLY"


def test_config_fit_llama_partial_offload():
    f = config_fit("llama.cpp", {"--n-gpu-layers": "16"}, 30e9, 24.0, 64.0, ARCH)
    assert f["stage"] == "offload"
    assert f["offloaded"] is True
    assert f["label"] == "OFFLOADED"


def test_config_fit_llama_partial_no_fit():
    f = config_fit("llama.cpp", {"--n-gpu-layers": "16"}, 60e9, 24.0, 64.0, ARCH)
    assert f["stage"] == "no_fit"
