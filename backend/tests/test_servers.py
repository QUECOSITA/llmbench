from app.servers import SERVERS, detect_binaries, build_bench_command, resolve_bench_binary, README_FLAG_MAP


def test_detect_finds_llama_bench(monkeypatch):
    monkeypatch.setattr("app.servers.shutil.which", lambda name: "/usr/bin/llama-bench" if name == "llama-bench" else None)
    assert detect_binaries()["llama.cpp"] is True


def test_detect_missing(monkeypatch):
    monkeypatch.setattr("app.servers.shutil.which", lambda name: None)
    assert detect_binaries() == {"llama.cpp": False, "vllm": False, "sglang": False}


def test_resolve_bench_binary_uses_bin_dir(tmp_path):
    fake = tmp_path / "llama-bench"
    fake.write_text("#!/bin/sh\n")
    assert resolve_bench_binary("llama.cpp", bin_dir=str(tmp_path)) == str(fake)


def test_resolve_bench_binary_falls_back_to_path(monkeypatch):
    monkeypatch.setattr("app.servers.shutil.which",
                        lambda name: "/usr/bin/llama-bench" if name == "llama-bench" else None)
    assert resolve_bench_binary("llama.cpp") == "/usr/bin/llama-bench"
    assert resolve_bench_binary("llama.cpp", bin_dir="/nonexistent") == "/usr/bin/llama-bench"


def test_build_bench_command_llama(tmp_path):
    workload = tmp_path / "p.jsonl"
    workload.write_text('{"prompt": "hello world"}\n')
    cmd = build_bench_command("llama.cpp", model_ref="/models/x.gguf",
                              flags={"--ctx-size": "4096", "--n-gpu-layers": "999", "-hf": "org/model"},
                              workload=str(workload), timeout_s=60)
    assert cmd[0] == "llama-bench"
    assert cmd[cmd.index("-m") + 1] == "/models/x.gguf"
    assert cmd[cmd.index("--fit-ctx") + 1] == "4096"
    assert "-c" not in cmd
    assert "-hf" not in cmd
    assert cmd[cmd.index("-p") + 1] == "6"
    assert cmd[cmd.index("-n") + 1] == "128"
    assert cmd[-4:] == ["-r", "2", "-o", "csv"]


def test_build_bench_command_llama_resolved_binary(tmp_path):
    (tmp_path / "llama-bench").write_text("#!/bin/sh\n")
    cmd = build_bench_command("llama.cpp", "/models/x.gguf", {"--ctx-size": "2048"},
                              workload="/nonexistent/prompts.jsonl", timeout_s=60, bin_dir=str(tmp_path))
    assert cmd[0] == str(tmp_path / "llama-bench")
    assert cmd[cmd.index("--fit-ctx") + 1] == "2048"
    assert cmd[cmd.index("-p") + 1] == "512"


def test_build_bench_command_llama_bare_bool_flag(tmp_path):
    cmd = build_bench_command("llama.cpp", "/models/x.gguf", {"--enforce-eager": ""},
                              workload="/nonexistent/prompts.jsonl", timeout_s=60)
    idx = cmd.index("--enforce-eager")
    assert idx != -1
    assert idx == len(cmd) - 1 or cmd[idx + 1] != "--enforce-eager"
    assert cmd[cmd.index("-p") + 1] == "512"
    assert cmd[-4:] == ["-r", "2", "-o", "csv"]


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


def test_build_bench_command_sglang_empty_max_running_requests():
    cmd = build_bench_command("sglang", "org/model", {"--max-running-requests": ""},
                              workload="/tmp/p.jsonl", timeout_s=60)
    assert cmd[cmd.index("--batch-size") + 1] == "16"
