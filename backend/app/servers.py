import shutil
from pathlib import Path

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


def resolve_bench_binary(server_id: str, bin_dir: str | None = None) -> str | None:
    meta = SERVERS[server_id]
    if server_id == "llama.cpp" and bin_dir:
        candidate = Path(bin_dir) / "llama-bench"
        if candidate.is_file():
            return str(candidate)
    for b in meta["bench_binaries"]:
        found = shutil.which(b)
        if found:
            return found
    return None


def detect_binaries(bin_dir: str | None = None) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for server_id in SERVERS:
        out[server_id] = resolve_bench_binary(server_id, bin_dir) is not None
    return out


_LLAMA_HF_FLAGS = {"-hf", "-hfr", "--hf-repo", "-hff", "--hf-file", "-hft", "--hf-token"}

# llama-bench accepts a small subset of llama-server flags; anything else
# extracted from a model card (e.g. --fit, --spec-type, --jinja, --no-mmap)
# is server-only and must not leak into the bench invocation.
_LLAMA_BENCH_FLAGS = {
    "--ctx-size", "--n-gpu-layers", "--batch-size", "--threads",
    "-fa", "--flash-attn", "-ctk", "--cache-type-k", "-ctv", "--cache-type-v",
    "-ub", "--ubatch-size", "-d", "--n-depth",
}


def _llama_token_counts(workload: str) -> tuple[int, int]:
    prompt = 512
    try:
        with open(workload, "r", encoding="utf-8") as fh:
            lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    except OSError:
        lines = []
    if lines:
        prompt = max(1, sum(len(ln) for ln in lines) // 4)
    return prompt, 128


def _canonical_flags(server_id: str, flags: dict[str, str]) -> dict[str, str]:
    mapping = README_FLAG_MAP[server_id]
    out: dict[str, str] = {}
    for flag, value in flags.items():
        canon = mapping.get(flag, flag)
        # Generated knobs (ctx/batch/gpu-layers) are inserted before readme
        # aliases, so first-wins keeps them from being clobbered by e.g. -c.
        if canon not in out:
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
                        workload: str, timeout_s: int, bin_dir: str | None = None) -> list[str]:
    flags = _canonical_flags(server_id, flags)
    if server_id == "llama.cpp":
        cmd = [resolve_bench_binary("llama.cpp", bin_dir) or "llama-bench", "-m", model_ref]
        mapped = {"--ctx-size": "--fit-ctx", "--n-gpu-layers": "-ngl", "--batch-size": "-b", "--threads": "-t"}
        for flag, value in flags.items():
            if flag in _LLAMA_HF_FLAGS or flag == "-m":
                continue
            if flag not in _LLAMA_BENCH_FLAGS:
                continue
            bench_flag = mapped.get(flag, flag)
            if value:
                cmd += [bench_flag, value]
            elif flag.startswith("--"):
                cmd += [bench_flag]
        prompt, gen = _llama_token_counts(workload)
        cmd += ["-p", str(prompt), "-n", str(gen), "-r", "2", "-o", "csv"]
        return cmd
    if server_id == "vllm":
        cmd = ["python", "-m", "vllm.benchmarks.benchmark_throughput",
               "--model", model_ref, "--input-len", "512", "--output-len", "128",
               "--num-prompts", "20", "--trust-remote-code", "--output-json", "/dev/stdout"]
        for flag, value in flags.items():
            if value:
                cmd += [flag, value]
            elif flag.startswith("--"):
                cmd += [flag]
        return cmd
    if server_id == "sglang":
        cmd = ["python", "-m", "sglang.bench_one_batch_server",
               "--model-path", model_ref, "--input-len", "512", "--output-len", "128",
               "--batch-size", (flags.get("--max-running-requests") or "16")]
        return cmd
    raise ValueError(f"unknown server {server_id}")
