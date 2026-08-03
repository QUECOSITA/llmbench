from app.servers import SERVERS, detect_binaries, build_bench_command, README_FLAG_MAP


def test_detect_finds_llama_bench(monkeypatch):
    monkeypatch.setattr("app.servers.shutil.which", lambda name: "/usr/bin/llama-bench" if name == "llama-bench" else None)
    assert detect_binaries()["llama.cpp"] is True


def test_detect_missing(monkeypatch):
    monkeypatch.setattr("app.servers.shutil.which", lambda name: None)
    assert detect_binaries() == {"llama.cpp": False, "vllm": False, "sglang": False}


def test_build_bench_command_llama():
    cmd = build_bench_command("llama.cpp", model_ref="/models/x.gguf", flags={"-c": "4096", "-ngl": "999"},
                              workload="/tmp/prompts.jsonl", timeout_s=60)
    assert cmd[0] == "llama-bench"
    assert "-m" in cmd and cmd[cmd.index("-m") + 1] == "/models/x.gguf"
    assert cmd[cmd.index("-c") + 1] == "4096"


def test_build_bench_command_vllm():
    cmd = build_bench_command("vllm", model_ref="org/model", flags={"--max-num-seqs": "32"},
                              workload="/tmp/p.jsonl", timeout_s=60)
    assert cmd[0].startswith("python")
    assert any("benchmark_throughput" in tok for tok in cmd)


def test_readme_flag_map_aliases():
    assert README_FLAG_MAP["llama.cpp"]["-c"] == "--ctx-size"
    assert README_FLAG_MAP["vllm"]["--max-model-len"] == "--max-model-len"


def test_build_bench_command_vllm_bare_bool_flag():
    cmd = build_bench_command("vllm", "org/model", {"--enforce-eager": ""},
                              workload="/tmp/p.jsonl", timeout_s=60)
    assert cmd[0].startswith("python")
    idx = cmd.index("--enforce-eager")
    assert idx != -1
    assert cmd[idx] == "--enforce-eager"
    assert idx == len(cmd) - 1 or cmd[idx + 1] != "--enforce-eager"
    assert any("benchmark_throughput" in tok for tok in cmd)


def test_build_bench_command_llama_bare_bool_flag():
    cmd = build_bench_command("llama.cpp", "/models/x.gguf", {"--enforce-eager": ""},
                              workload="/tmp/prompts.jsonl", timeout_s=60)
    idx = cmd.index("--enforce-eager")
    assert idx != -1
    assert idx == len(cmd) - 1 or cmd[idx + 1] != "--enforce-eager"
    assert cmd[cmd.index("-p") + 1] == "/tmp/prompts.jsonl"
    assert cmd[-4:] == ["-o", "csv", "-r", "2"]


def test_build_bench_command_sglang_empty_max_running_requests():
    cmd = build_bench_command("sglang", "org/model", {"--max-running-requests": ""},
                              workload="/tmp/p.jsonl", timeout_s=60)
    assert cmd[cmd.index("--batch-size") + 1] == "16"
