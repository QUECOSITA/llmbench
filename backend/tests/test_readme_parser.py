from app.readme_parser import (
    detect_serving_programs,
    extract_flags,
    has_serving_command,
    top_serving_program,
)


def test_detect_llamacpp_by_gguf():
    scores = detect_serving_programs("Use the GGUF below.", has_gguf=True)
    assert scores == {"llama.cpp": 3}


def test_vllm_only_readme_is_not_detected():
    """A README proposing only vllm/sglang is not a supported server anymore."""
    text = (
        "python -m sglang.launch_server --model-path Qwen/Qwen3.6-27B\n"
        "vllm serve Qwen/Qwen3.6-27B --tensor-parallel-size 8\n"
    )
    scores = detect_serving_programs(text, has_gguf=False)
    assert scores == {"llama.cpp": 0}
    assert top_serving_program(scores) is None


def test_extract_flags():
    text = "Run:\n```\nllama-server -m model.gguf -c 4096 --n-gpu-layers 999\n```"
    flags = extract_flags(text, ["llama.cpp"])
    assert flags["-c"] == "4096"
    assert flags["--n-gpu-layers"] == "999"


def test_extract_flags_backslash_line_continuation_is_bare_flag():
    text = "Run:\n```\nllama-server -m model.gguf --no-mmap \\\n--jinja \\\n--fit on\n```"
    flags = extract_flags(text, ["llama.cpp"])
    assert flags["--no-mmap"] == ""
    assert flags["--jinja"] == ""
    assert flags["--fit"] == "on"


def test_extract_flags_ansi_c_quoted_value():
    text = (
        "Run:\n```\n"
        "llama-server -m model.gguf -c 4096 "
        "--reasoning-budget-message $'\\n\\nConsidering the limited time available.\\n'\n"
        "```"
    )
    flags = extract_flags(text, ["llama.cpp"])
    assert flags["--reasoning-budget-message"] == "\n\nConsidering the limited time available.\n"


def test_extract_flags_double_quoted_value_with_spaces():
    text = "```\nllama-server -m x.gguf --prompt-file \"my prompts file.txt\"\n```"
    flags = extract_flags(text, ["llama.cpp"])
    assert flags["--prompt-file"] == "my prompts file.txt"


def test_extract_flags_unterminated_quote_drops_flag():
    text = "```\nllama-server -m x.gguf --reasoning-budget-message $'never closed\n```"
    flags = extract_flags(text, ["llama.cpp"])
    assert "--reasoning-budget-message" not in flags


def test_extract_flags_does_not_bleed_other_servers_flags():
    """A README documenting multiple servers must not leak other servers' flags
    into the requested server's extraction (regression: full-text fallback)."""
    text = (
        "# MTP model\n"
        "```bash\nllama-server -m model.gguf -c 4096 -ngl 999 --spec-type draft-mtp\n```\n"
        "```bash\nvllm serve Qwen/Qwen3.6-27B --tensor-parallel-size 8 --max-model-len 1010000\n```\n"
        "```bash\nsglang.launch_server --model-path Qwen/Qwen3.6-27B --tp-size 8 --context-length 1010000\n```\n"
    )
    llama = extract_flags(text, ["llama.cpp"])
    assert llama["-c"] == "4096"
    assert llama["--spec-type"] == "draft-mtp"
    assert "--tensor-parallel-size" not in llama
    assert "--max-model-len" not in llama
    assert "--tp-size" not in llama
    assert "--context-length" not in llama
    assert "--model-path" not in llama


def test_extract_flags_ignores_build_install_commands():
    """Build/install instructions in a README (cmake/git/apt) must not leak
    their flags into the serving command extraction, even when the build block
    mentions llama.cpp/llama-cli (regression: unsloth/Qwen3.5-4B-MTP-GGUF)."""
    text = (
        "# Build\n"
        "```bash\n"
        "apt-get install -y git cmake\n"
        "git clone https://github.com/ggml-org/llama.cpp\n"
        "cmake -B llama.cpp/build -DBUILD_SHARED_LIBS OFF -DGGML_CUDA ON\n"
        "cmake --build llama.cpp/build --config Release -j --clean-first --target llama-cli\n"
        "```\n"
        "```bash\n"
        "llama-server -hf unsloth/Qwen3.5-4B-MTP-GGUF --hf-file Qwen3.5-4B-UD-Q8_K_XL.gguf "
        "--ctx-size 8192 --n-gpu-layers 99 --batch-size 512 --spec-type draft-mtp "
        "--spec-draft-n-max 6 -fa on\n"
        "```\n"
    )
    flags = extract_flags(text, ["llama.cpp"])
    assert flags["-hf"] == "unsloth/Qwen3.5-4B-MTP-GGUF"
    assert flags["--hf-file"] == "Qwen3.5-4B-UD-Q8_K_XL.gguf"
    assert flags["--ctx-size"] == "8192"
    assert flags["--spec-type"] == "draft-mtp"
    assert flags["-fa"] == "on"
    for bad in ("-y", "-B", "-DBUILD_SHARED_LIBS", "-DGGML_CUDA",
                "--build", "--config", "-j", "--clean-first", "--target"):
        assert bad not in flags, f"build flag {bad} leaked into serving flags"


def test_has_serving_command_matches_command_tokens():
    assert has_serving_command("Run: llama-server -m x.gguf", "llama.cpp")
    assert has_serving_command("benchmark with speed-bench", "llama.cpp")
    assert has_serving_command("llama-cli -m x", "llama.cpp")
    assert has_serving_command("llama-bench -m x", "llama.cpp")


def test_has_serving_command_ignores_bare_project_mention():
    assert not has_serving_command("we recommend llama.cpp for inference", "llama.cpp")


def test_has_serving_command_false_when_absent():
    assert not has_serving_command("pip install transformers", "llama.cpp")


def test_has_serving_command_is_case_insensitive():
    assert has_serving_command("LLAMA-SERVER -m x.gguf", "llama.cpp")
    assert has_serving_command("Llama-Bench -m x", "llama.cpp")


def test_has_serving_command_unknown_server_is_false():
    assert not has_serving_command("llama-server -m x.gguf", "vllm")


def test_has_serving_command_does_not_fuzzy_match():
    assert not has_serving_command("use llama-benchmark for evals", "llama.cpp")
