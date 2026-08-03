from app.readme_parser import detect_serving_programs, extract_flags


def test_detect_vllm_by_command():
    text = "Quickstart:\n```bash\nvllm serve Org/Model --max-model-len 8192\n```"
    scores = detect_serving_programs(text, has_gguf=False)
    assert scores["vllm"] > scores["llama.cpp"]
    assert scores["vllm"] > scores["sglang"]


def test_detect_llamacpp_by_gguf():
    scores = detect_serving_programs("Use the GGUF below.", has_gguf=True)
    assert scores["llama.cpp"] > scores["vllm"]


def test_detect_sglang():
    text = "python -m sglang.launch_server --model-path Org/Model --port 30000"
    scores = detect_serving_programs(text, has_gguf=False)
    assert scores["sglang"] == max(scores.values())


def test_extract_flags():
    text = "Run:\n```\nllama-server -m model.gguf -c 4096 --n-gpu-layers 999\n```"
    flags = extract_flags(text, ["llama.cpp"])
    assert flags["-c"] == "4096"
    assert flags["--n-gpu-layers"] == "999"


def test_extract_flag_equals_form():
    text = "vllm serve M --max-model-len=16384 --enforce-eager"
    flags = extract_flags(text, ["vllm"])
    assert flags["--max-model-len"] == "16384"
    assert flags["--enforce-eager"] == ""
