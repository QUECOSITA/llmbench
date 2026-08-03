import shutil

SERVERS = {
    "llama.cpp": {
        "display": "llama.cpp",
        "bench_binaries": ["llama-bench"],
        "serving_binaries": ["llama-server"],
    },
    "vllm": {
        "display": "vLLM",
        "bench_binaries": ["python"],
        "serving_binaries": ["vllm"],
    },
    "sglang": {
        "display": "sglang",
        "bench_binaries": ["python"],
        "serving_binaries": ["sglang"],
    },
}

# README flag name -> canonical flag name per server
README_FLAG_MAP = {
    "llama.cpp": {
        "-c": "--ctx-size", "-n": "--predict", "-t": "--threads", "-b": "--batch-size",
        "-ngl": "--n-gpu-layers", "-m": "-m",
    },
    "vllm": {"--max-model-len": "--max-model-len", "--max-num-seqs": "--max-num-seqs",
             "--gpu-memory-utilization": "--gpu-memory-utilization", "--enforce-eager": "--enforce-eager",
             "--tensor-parallel-size": "--tensor-parallel-size"},
    "sglang": {"--context-length": "--context-length", "--max-running-requests": "--max-running-requests",
               "--mem-fraction-static": "--mem-fraction-static", "--tp-size": "--tp-size"},
}


def detect_binaries() -> dict[str, bool]:
    out: dict[str, bool] = {}
    for server_id, meta in SERVERS.items():
        out[server_id] = any(shutil.which(b) for b in meta["bench_binaries"])
    return out


def _canonical_flags(server_id: str, flags: dict[str, str]) -> dict[str, str]:
    mapping = README_FLAG_MAP[server_id]
    out: dict[str, str] = {}
    for flag, value in flags.items():
        canon = mapping.get(flag, flag)
        out[canon] = value
    return out


def _flag_tokens(flags: dict[str, str]) -> list[str]:
    tokens: list[str] = []
    for flag, value in flags.items():
        if flag.startswith("--") and not value:
            tokens.append(flag)
        else:
            tokens.append(flag)
            tokens.append(value)
    return tokens


def build_bench_command(server_id: str, model_ref: str, flags: dict[str, str],
                        workload: str, timeout_s: int) -> list[str]:
    flags = _canonical_flags(server_id, flags)
    if server_id == "llama.cpp":
        cmd = ["llama-bench", "-m", model_ref]
        mapped = {"--ctx-size": "-c", "--n-gpu-layers": "-ngl", "--batch-size": "-b", "--threads": "-t"}
        for flag, value in flags.items():
            bench_flag = mapped.get(flag, flag)
            if value:
                cmd += [bench_flag, value]
        cmd += ["-p", workload, "-o", "csv", "-r", "2"]
        return cmd
    if server_id == "vllm":
        cmd = ["python", "-m", "vllm.benchmarks.benchmark_throughput",
               "--model", model_ref, "--input-len", "512", "--output-len", "128",
               "--num-prompts", "20", "--trust-remote-code", "--output-json", "/dev/stdout"]
        for flag, value in flags.items():
            if value:
                cmd += [flag, value]
        return cmd
    if server_id == "sglang":
        cmd = ["python", "-m", "sglang.bench_one_batch_server",
               "--model-path", model_ref, "--input-len", "512", "--output-len", "128",
               "--batch-size", flags.get("--max-running-requests", "16")]
        return cmd
    raise ValueError(f"unknown server {server_id}")
