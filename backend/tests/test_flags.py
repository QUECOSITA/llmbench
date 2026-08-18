from app.flags import KEY_FLAGS, build_serving_command, generate_configs


def test_generate_configs_count_and_baseline():
    readme_flags = {"--ctx-size": "8192", "--spec-type": "mtp"}
    configs = generate_configs(server_id="llama.cpp", readme_flags=readme_flags, n=3, vram_gb=24)
    assert len(configs) == 3
    baseline = configs[0]
    assert baseline["flags"]["--ctx-size"] == "8192"
    assert baseline["flags"]["--spec-type"] == "draft-mtp"
    assert "--n-gpu-layers" in baseline["flags"]
    for cfg in configs[1:]:
        diffs = [k for k in KEY_FLAGS["llama.cpp"] if cfg["flags"].get(k) != baseline["flags"].get(k)]
        assert len(diffs) == 1, diffs


def test_gguf_llama_command():
    cmd = build_serving_command("llama.cpp", "org/model", {"-c": "4096", "-ngl": "999"},
                                gguf_filename="x.gguf")
    assert "--hf-repo org/model" in cmd
    assert "--hf-file x.gguf" in cmd
    assert "-m" not in cmd


def test_gguf_llama_command_falls_back_to_path():
    cmd = build_serving_command("llama.cpp", "org/model", {"-c": "4096"},
                                gguf_path="/models/x.gguf")
    assert "-m /models/x.gguf" in cmd


def test_llama_serving_command_includes_spec_flags():
    cmd = build_serving_command("llama.cpp", "org/model",
                                {"--spec-type": "draft-mtp", "--spec-draft-n-max": "2"},
                                gguf_filename="x.gguf")
    assert "--hf-repo org/model" in cmd
    assert "--hf-file x.gguf" in cmd
    assert "--spec-type draft-mtp" in cmd
    assert "--spec-draft-n-max 2" in cmd


def test_deterministic():
    a = generate_configs("llama.cpp", {}, 3, 24)
    b = generate_configs("llama.cpp", {}, 3, 24)
    assert a == b


def test_generate_configs_no_duplicates_high_n():
    configs = generate_configs(server_id="llama.cpp", readme_flags={}, n=20, vram_gb=24)
    seen = {tuple(sorted(c["flags"].items())) for c in configs}
    assert len(configs) == len(seen)  # all distinct
    assert configs[0]["flags"] == configs[0]["flags"]  # baseline present


def test_generate_configs_does_not_overshoot():
    configs = generate_configs(server_id="llama.cpp", readme_flags={}, n=35, vram_gb=24)
    assert len(configs) <= 35  # never more than requested


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


def test_llama_serving_command_strips_readme_m_when_hf_file_given():
    cmd = build_serving_command(
        "llama.cpp", "org/model",
        {"-m": "Qwen.gguf", "--hf-repo": "org/model", "--hf-file": "Qwen.gguf",
         "--spec-type": "draft-mtp", "-c": "4096"},
        gguf_filename="Qwen.gguf")
    assert "--hf-repo org/model" in cmd
    assert "--hf-file Qwen.gguf" in cmd
    assert "-m" not in cmd.split()
    assert "--spec-type draft-mtp" in cmd
    assert "-c 4096" in cmd


def test_build_serving_command_quotes_value_with_spaces():
    import shlex

    cmd = build_serving_command(
        "llama.cpp", "org/model",
        {"--reasoning-budget-message": "\n\nConsidering the limited time available.\n", "-c": "4096"},
        gguf_filename="x.gguf")
    tokens = shlex.split(cmd)
    assert tokens[tokens.index("--reasoning-budget-message") + 1] == "\n\nConsidering the limited time available.\n"
    assert tokens[tokens.index("-c") + 1] == "4096"


def test_build_serving_command_roundtrips_special_values():
    import shlex

    flags = {"--reasoning-budget-message": "line one\nline 'two' \"three\" $five", "-c": "4096"}
    cmd = build_serving_command("llama.cpp", "org/model", flags, gguf_filename="x.gguf")
    tokens = shlex.split(cmd)
    i = tokens.index("--reasoning-budget-message")
    assert tokens[i + 1] == flags["--reasoning-budget-message"]


def test_baseline_readme_short_alias_is_canonicalized():
    cfg = generate_configs("llama.cpp", {"-c": "8192"}, 1, 24)[0]["flags"]
    assert cfg["--ctx-size"] == "8192"
    assert "-c" not in cfg


def test_baseline_long_form_wins_over_short_alias():
    cfg = generate_configs("llama.cpp", {"-c": "57344", "--ctx-size": "4096"}, 1, 24)[0]["flags"]
    assert cfg["--ctx-size"] == "4096"
    assert "-c" not in cfg


def test_baseline_other_aliases_canonicalized():
    cfg = generate_configs(
        "llama.cpp", {"-ngl": "40", "-b": "2048", "-t": "8"}, 1, 24
    )[0]["flags"]
    assert cfg["--n-gpu-layers"] == "40"
    assert cfg["--batch-size"] == "2048"
    assert "--threads" in cfg
    assert "-ngl" not in cfg
    assert "-b" not in cfg
    assert "-t" not in cfg


def test_build_serving_command_strips_duplicate_alias():
    cmd = build_serving_command(
        "llama.cpp", "org/model",
        {"--ctx-size": "4096", "-c": "8192"},
        gguf_filename="x.gguf",
    )
    tokens = cmd.split()
    assert "-c" not in tokens
    assert "--ctx-size 4096" in cmd


def test_baseline_pins_load_mode_and_no_mmproj():
    cfg = generate_configs("llama.cpp", {}, 1, 24)[0]["flags"]
    assert cfg["--load-mode"] == "none"
    assert cfg["--no-mmproj"] == ""


def test_pinned_flags_present_in_every_generated_config():
    for cfg in generate_configs("llama.cpp", {}, 12, 24):
        assert cfg["flags"]["--load-mode"] == "none"
        assert cfg["flags"]["--no-mmproj"] == ""


def test_serving_command_prioritizes_pinned_flags():
    cfg = generate_configs("llama.cpp", {}, 1, 24)[0]
    cmd = build_serving_command("llama.cpp", "org/model", cfg["flags"], gguf_filename="x.gguf")
    assert "--load-mode none" in cmd
    assert "--no-mmproj" in cmd
    assert cmd.index("--load-mode") < cmd.index("--ctx-size")
    assert cmd.index("--no-mmproj") < cmd.index("--ctx-size")


def test_readme_deprecated_memory_flags_dropped():
    cfg = generate_configs(
        "llama.cpp",
        {"--no-mmap": "", "--mlock": "", "--direct-io": "", "--defrag-thold": "0", "-dt": "0"},
        1, 24,
    )[0]["flags"]
    for bad in ("--no-mmap", "--mlock", "--direct-io", "--defrag-thold", "-dt"):
        assert bad not in cfg
    assert cfg["--load-mode"] == "none"


def test_readme_mmproj_auto_flags_dropped():
    cfg = generate_configs("llama.cpp", {"--mmproj-auto": "", "--no-mmproj-auto": ""}, 1, 24)[0]["flags"]
    assert "--mmproj-auto" not in cfg
    assert "--no-mmproj-auto" not in cfg
    assert cfg["--no-mmproj"] == ""


def test_readme_modern_load_mode_overridden():
    cfg = generate_configs("llama.cpp", {"--load-mode": "mlock"}, 1, 24)[0]["flags"]
    assert cfg["--load-mode"] == "none"


def test_readme_removed_draft_flags_mapped():
    cfg = generate_configs("llama.cpp", {"--draft-max": "3", "--draft-min": "1"}, 1, 24)[0]["flags"]
    assert cfg["--spec-draft-n-max"] == "3"
    assert cfg["--spec-draft-n-min"] == "1"
    assert "--draft-max" not in cfg
    assert "--draft-min" not in cfg


def test_readme_removed_draft_short_aliases_mapped():
    for alias, val in (("--draft", "2"), ("--draft-n", "4")):
        cfg = generate_configs("llama.cpp", {alias: val}, 1, 24)[0]["flags"]
        assert cfg["--spec-draft-n-max"] == val
        assert alias not in cfg
