from app.readme_parser import detect_serving_programs, extract_flags, top_serving_program


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
