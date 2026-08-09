import importlib.util
import shutil
import sys
from pathlib import Path

SERVERS = {
    "llama.cpp": {
        "display": "llama.cpp",
        "bench_binaries": ["llama-bench"],
        "serving_binaries": ["llama-server"],
    },
    "vllm": {
        "display": "vLLM",
        "module": "vllm",
        "bench_binaries": [],
        "serving_binaries": ["vllm"],
    },
    "sglang": {
        "display": "sglang",
        "module": "sglang",
        "bench_binaries": [],
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


def _module_importable(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def resolve_bench_binary(server_id: str, bin_dir: str | None = None) -> str | None:
    """Resolve the executable that runs a server's benchmark. Module-based servers
    (vLLM, sglang) are ready only when their module is importable in the current
    interpreter; the returned value is that interpreter, matching how the bench is
    spawned. Binary servers resolve like llama.cpp."""
    meta = SERVERS[server_id]
    if server_id == "llama.cpp" and bin_dir:
        candidate = Path(bin_dir) / "llama-bench"
        if candidate.is_file():
            return str(candidate)
    if meta.get("module"):
        return sys.executable if _module_importable(meta["module"]) else None
    for b in meta["bench_binaries"]:
        found = shutil.which(b)
        if found:
            return found
    return None


def speed_bench_deps_available() -> bool:
    """True when the current interpreter (the one speed-bench would be spawned
    with) can import the speed_bench.py client's third-party deps."""
    return all(importlib.util.find_spec(m) is not None for m in _SPEED_BENCH_DEPS)


def detect_binaries(bin_dir: str | None = None) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for server_id in SERVERS:
        out[server_id] = resolve_bench_binary(server_id, bin_dir) is not None
    out["speed-bench"] = (resolve_speed_bench_script(bin_dir) is not None
                          and speed_bench_deps_available())
    return out


_SPEED_BENCH_DEPS = ("requests", "datasets", "tqdm")


_SPEC_DECODING_FLAGS = {
    "--spec-type", "-md", "--model-draft", "--model-mtp", "-mtmd",
    "--draft-max", "--draft-min", "--draft-p-min",
    "--spec-draft-n-max", "--spec-draft-n-min", "--spec-raw-logits",
    "--spec-heuristics", "--spec-heuristic-acc", "--spec-heuristic-min-tokens",
}


def is_spec_decoding_model(repo_id: str, gguf_filename: str | None = None,
                           readme_flags: dict[str, str] | None = None) -> bool:
    """True when a model should be benchmarked with speed-bench: the repo/GGUF
    name contains MTP, or the README proposes a speculative-decoding flag."""
    if "mtp" in f"{repo_id} {gguf_filename or ''}".lower():
        return True
    return any(flag in _SPEC_DECODING_FLAGS for flag in (readme_flags or {}))


def resolve_serving_binary(server_id: str, bin_dir: str | None = None) -> str | None:
    meta = SERVERS[server_id]
    if server_id == "llama.cpp" and bin_dir:
        candidate = Path(bin_dir) / "llama-server"
        if candidate.is_file():
            return str(candidate)
    for b in meta["serving_binaries"]:
        found = shutil.which(b)
        if found:
            return found
    return None


def resolve_speed_bench_script(bin_dir: str | None = None,
                               configured: str | Path | None = None) -> str | None:
    """Locate speed_bench.py. Honors an explicitly configured path, otherwise
    auto-discovers it in the llama.cpp source tree that contains the resolved
    llama-server binary."""
    if configured:
        p = Path(configured)
        if p.is_file():
            return str(p)
    server = resolve_serving_binary("llama.cpp", bin_dir)
    if not server:
        return None
    bin_path = Path(server).parent
    for parent in [bin_path, *bin_path.parents[:3]]:
        candidate = parent / "tools" / "server" / "bench" / "speed-bench" / "speed_bench.py"
        if candidate.is_file():
            return str(candidate)
    return None


SPEED_BENCH_CLI_FLAGS = ("--url", "--model", "--bench", "--category", "--osl",
                         "--extra-inputs", "--concurrency", "--limit", "--timeout", "--output")

SPEED_BENCH_BENCHES = ("qualitative", "throughput_1k", "throughput_2k",
                       "throughput_8k", "throughput_16k", "throughput_32k")

SPEED_BENCH_CATEGORIES = {
    "qualitative": ("coding", "humanities", "math", "qa", "rag", "reasoning",
                    "stem", "writing", "multilingual", "summarization", "roleplay"),
    "throughput_1k": ("high_entropy", "mixed", "low_entropy"),
    "throughput_2k": ("high_entropy", "mixed", "low_entropy"),
    "throughput_8k": ("high_entropy", "mixed", "low_entropy"),
    "throughput_16k": ("high_entropy", "mixed", "low_entropy"),
    "throughput_32k": ("high_entropy", "mixed", "low_entropy"),
}


def speed_bench_default_flags(osl: int = 128) -> str:
    return f"--bench throughput_1k --category all --limit 1 --osl {osl}"


def parse_speed_bench_flags(text: str) -> list[str]:
    """Split the user-edited flags string into tokens. Drop any leading bare
    tokens (so pasting the full command works) and normalize --flag=value."""
    import shlex
    tokens = shlex.split(text)
    while tokens and not tokens[0].startswith("-"):
        tokens = tokens[1:]
    out: list[str] = []
    for tok in tokens:
        if tok.startswith("--") and "=" in tok:
            name, _, value = tok.partition("=")
            if value.startswith("-"):
                out.append(tok)
            else:
                out.extend([name, value])
        else:
            out.append(tok)
    return out


def _speed_bench_categories(bench: str | None) -> set[str]:
    if bench:
        return set(SPEED_BENCH_CATEGORIES.get(bench, ()))
    union: set[str] = set()
    for cats in SPEED_BENCH_CATEGORIES.values():
        union.update(cats)
    return union


def validate_speed_bench_flags(flags: list[str]) -> str | None:
    """Return an error message for invalid speed-bench flags, or None if valid."""
    parsed: dict[str, list[str]] = {}
    i = 0
    while i < len(flags):
        tok = flags[i]
        if not tok.startswith("-"):
            return f"unexpected token '{tok}'"
        name = tok
        value = None
        if tok.startswith("--") and "=" in tok:
            name, _, value = tok.partition("=")
        elif i + 1 < len(flags) and not flags[i + 1].startswith("-"):
            value = flags[i + 1]
            i += 1
        if name not in SPEED_BENCH_CLI_FLAGS:
            return f"unknown speed-bench flag '{name}'; allowed: " + ", ".join(SPEED_BENCH_CLI_FLAGS)
        if name in ("--url", "--output"):
            return f"{name} is managed by the app; remove it from the speed-bench flags"
        if value is None:
            return f"flag '{name}' requires a value"
        parsed.setdefault(name, []).append(value)
        i += 1
    for b in parsed.get("--bench", []):
        if b not in SPEED_BENCH_BENCHES:
            return f"unknown --bench '{b}'; available benches: " + ", ".join(SPEED_BENCH_BENCHES)
    bench = parsed["--bench"][0] if parsed.get("--bench") else None
    cats = _speed_bench_categories(bench)
    for c in parsed.get("--category", []):
        if c != "all" and c not in cats:
            avail = "all, " + ", ".join(sorted(cats))
            return f"unknown --category '{c}' for bench '{bench}'; available: {avail}"
    return None


def build_speed_bench_command(script: str, flags: list[str], url: str = "localhost:8080",
                              output: str = "speed-bench.json") -> list[str]:
    return [sys.executable, script, *flags, "--url", url, "--output", output]


def build_server_command(serving_command: str, bin_dir: str | None = None) -> list[str]:
    """Turn the editable llama-server serving command into an executable token
    list: swap in the resolved binary and drop --port/--host (the runner injects
    its own). -p (--parallel) is left alone."""
    import shlex
    tokens = shlex.split(serving_command)
    if not tokens:
        return []
    resolved = resolve_serving_binary("llama.cpp", bin_dir)
    if resolved:
        tokens[0] = resolved
    out: list[str] = []
    skip_next = False
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if tok in ("--port", "--host"):
            skip_next = True
            continue
        out.append(tok)
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


def parse_serving_command(server_id: str, command: str) -> dict[str, str]:
    """Extract flag/value pairs from an edited serving command. Bare boolean
    flags parse to value "", and positional tokens (binary names, repo ids)
    are ignored. The result can be fed back into build_bench_command."""
    import shlex
    tokens = shlex.split(command)
    flags: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("-"):
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                flags[tok] = tokens[i + 1]
                i += 2
            else:
                flags[tok] = ""
                i += 1
        else:
            i += 1
    return flags


def model_ref_from_flags(server_id: str, flags: dict[str, str],
                         fallback_repo: str) -> tuple[str, str | None]:
    """Resolve the model reference (and optional gguf filename) used by
    build_bench_command from flags parsed out of a serving command."""
    if server_id == "llama.cpp":
        repo = flags.get("--hf-repo") or flags.get("-hfr")
        file = flags.get("--hf-file") or flags.get("-hff")
        if file:
            return (repo or fallback_repo), file
        model = flags.get("-m")
        if model:
            return model, None
        return fallback_repo, None
    if server_id == "sglang":
        ref = flags.get("--model-path") or fallback_repo
        return ref, None
    return fallback_repo, None


def build_bench_command(server_id: str, model_ref: str, flags: dict[str, str],
                        workload: str, timeout_s: int, bin_dir: str | None = None,
                        gguf_filename: str | None = None) -> list[str]:
    flags = _canonical_flags(server_id, flags)
    if server_id == "llama.cpp":
        bench = resolve_bench_binary("llama.cpp", bin_dir) or "llama-bench"
        if gguf_filename:
            cmd = [bench, "-hfr", model_ref, "-hff", gguf_filename]
        else:
            cmd = [bench, "-m", model_ref]
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
        cmd = [sys.executable, "-m", "vllm.benchmarks.benchmark_throughput",
               "--model", model_ref, "--input-len", "512", "--output-len", "128",
               "--num-prompts", "20", "--trust-remote-code", "--output-json", "/dev/stdout"]
        for flag, value in flags.items():
            if value:
                cmd += [flag, value]
            elif flag.startswith("--"):
                cmd += [flag]
        return cmd
    if server_id == "sglang":
        cmd = [sys.executable, "-m", "sglang.bench_one_batch_server",
               "--model-path", model_ref, "--input-len", "512", "--output-len", "128",
               "--batch-size", (flags.get("--max-running-requests") or "16")]
        return cmd
    raise ValueError(f"unknown server {server_id}")
