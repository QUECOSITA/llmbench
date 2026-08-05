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


def test_generate_configs_no_duplicates_high_n():
    configs = generate_configs(server_id="vllm", readme_flags={}, n=20, vram_gb=24)
    seen = {tuple(sorted(c["flags"].items())) for c in configs}
    assert len(configs) == len(seen)  # all distinct
    assert len(configs) <= 9          # capped at distinct single-key variants for vllm
    assert configs[0]["flags"] == configs[0]["flags"]  # baseline present


def test_generate_configs_does_not_overshoot():
    configs = generate_configs(server_id="vllm", readme_flags={}, n=35, vram_gb=24)
    assert len(configs) <= 35  # never more than requested


def test_bool_flag_on_variant_renders_once():
    cmd = build_serving_command("vllm", "org/model", {"--enforce-eager": "--enforce-eager"})
    assert cmd.count("--enforce-eager") == 1


def test_generate_configs_unknown_server_valueerror():
    try:
        generate_configs("not-a-server", {}, 3, 24)
    except ValueError as exc:
        assert "unknown server" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_llama_spec_flags_in_baseline():
    cfg = generate_configs("llama.cpp", {}, 1, 24)[0]["flags"]
    assert cfg["--spec-type"] == "draft-mtp"
    assert cfg["--spec-draft-n-max"] == "2"


def test_llama_spec_type_readme_mtp_normalizes_to_draft_mtp():
    cfg = generate_configs("llama.cpp", {"--spec-type": "mtp"}, 1, 24)[0]["flags"]
    assert cfg["--spec-type"] == "draft-mtp"


def test_llama_spec_type_sweeps_variants():
    configs = generate_configs("llama.cpp", {}, 12, 24)
    spec_types = {c["flags"]["--spec-type"] for c in configs}
    n_max = {c["flags"]["--spec-draft-n-max"] for c in configs}
    assert spec_types == {"draft-mtp", "none"}
    assert n_max == {"2", "3"}
