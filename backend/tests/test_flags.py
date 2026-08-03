from app.flags import KEY_FLAGS, build_serving_command, generate_configs


def test_generate_configs_count_and_baseline():
    readme_flags = {"--max-model-len": "8192", "--enforce-eager": ""}
    configs = generate_configs(server_id="vllm", readme_flags=readme_flags, n=3, vram_gb=24)
    assert len(configs) == 3
    baseline = configs[0]
    assert baseline["flags"]["--max-model-len"] == "8192"
    assert baseline["flags"]["--enforce-eager"] == ""
    # key perf flags present with defaults
    assert "--gpu-memory-utilization" in baseline["flags"]
    # each non-baseline config differs in exactly one key flag
    for cfg in configs[1:]:
        diffs = [k for k in KEY_FLAGS["vllm"] if cfg["flags"].get(k) != baseline["flags"].get(k)]
        assert len(diffs) == 1, diffs


def test_build_serving_command_vllm():
    cmd = build_serving_command("vllm", "org/model", {
        "--max-model-len": "8192", "--enforce-eager": "", "--max-num-seqs": "32",
    })
    assert cmd.startswith("vllm serve org/model")
    assert "--max-model-len 8192" in cmd
    assert "--max-num-seqs 32" in cmd
    assert "--enforce-eager" in cmd


def test_gguf_llama_command():
    cmd = build_serving_command("llama.cpp", "org/model", {"-c": "4096", "-ngl": "999"},
                                gguf_path="/models/x.gguf")
    assert "-m /models/x.gguf" in cmd


def test_deterministic():
    a = generate_configs("vllm", {}, 3, 24)
    b = generate_configs("vllm", {}, 3, 24)
    assert a == b
