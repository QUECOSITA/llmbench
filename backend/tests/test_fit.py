from app.fit import config_fit, arch_from_config, DEFAULT_ARCH, fit_verdict

ARCH = {"layers": 32, "heads": 32, "hidden": 4096, "max_ctx": 8192}


def test_fits_in_vram():
    verdict = fit_verdict(weights_bytes=10_000_000_000, vram_gb=24.0, ram_gb=64.0, ctx=8192, layers=32, heads=32, hidden=4096)
    assert verdict["stage"] == "gpu"


def test_offload_to_ram():
    verdict = fit_verdict(weights_bytes=40_000_000_000, vram_gb=24.0, ram_gb=64.0, ctx=8192, layers=32, heads=32, hidden=4096)
    assert verdict["stage"] == "ram_offload"


def test_warns_when_does_not_fit():
    verdict = fit_verdict(weights_bytes=100_000_000_000, vram_gb=24.0, ram_gb=64.0, ctx=8192, layers=32, heads=32, hidden=4096)
    assert verdict["stage"] == "no_fit"
    assert verdict["warning"] is True


def test_cpu_only_arch():
    verdict = fit_verdict(weights_bytes=10_000_000_000, vram_gb=0.0, ram_gb=64.0, ctx=8192, layers=32, heads=32, hidden=4096)
    assert verdict["stage"] == "ram"


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


def test_config_fit_vllm_uses_gpu_utilization():
    assert config_fit("vllm", {"--gpu-memory-utilization": "0.9"}, 10e9, 24.0, 64.0, ARCH)["stage"] == "gpu"
    assert config_fit("vllm", {"--gpu-memory-utilization": "0.9"}, 40e9, 24.0, 64.0, ARCH)["stage"] == "no_fit"


def test_config_fit_sglang_uses_mem_fraction():
    f = config_fit("sglang", {"--context-length": "4096", "--mem-fraction-static": "0.85"}, 15e9, 24.0, 64.0, ARCH)
    assert f["stage"] == "gpu"
    assert f["fits_vram"] is True


def test_config_fit_ctx_flag_scales_kv():
    low = config_fit("vllm", {"--max-model-len": "2048"}, 15e9, 24.0, 64.0, ARCH)
    high = config_fit("vllm", {"--max-model-len": "16384"}, 15e9, 24.0, 64.0, ARCH)
    assert high["kv_gb"] > low["kv_gb"]
    assert low["stage"] == "gpu"
    assert high["stage"] == "no_fit"


def test_config_fit_defaults_arch_and_ctx():
    f = config_fit("vllm", {}, 10e9, 24.0, 64.0)
    assert f["stage"] == "gpu"
    assert f["needed_gb"] > 10.0
