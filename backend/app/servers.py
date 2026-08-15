import importlib.util
import os
import re
import shlex
import shutil
import sys
import threading
from pathlib import Path

import httpx

SERVERS = {
    "llama.cpp": {
        "display": "llama.cpp",
        "bench_binaries": ["llama-bench"],
        "serving_binaries": ["llama-server"],
    },
}

# README flag name -> canonical flag name per server
README_FLAG_MAP = {
    "llama.cpp": {
        "-c": "--ctx-size", "-n": "--predict", "-t": "--threads", "-b": "--batch-size",
        "-ngl": "--n-gpu-layers", "-m": "-m",
    },
}


def _module_importable(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _binary_candidates(name: str) -> list[str]:
    return [name, f"{name}.exe"]


def resolve_bench_binary(server_id: str, bin_dir: str | None = None) -> str | None:
    """Resolve the executable that runs a server's benchmark. llama.cpp resolves
    the llama-bench binary from bin_dir or PATH."""
    if server_id == "llama.cpp" and bin_dir:
        for cand in _binary_candidates("llama-bench"):
            candidate = Path(bin_dir) / cand
            if candidate.is_file():
                return str(candidate)
    for b in SERVERS[server_id]["bench_binaries"]:
        found = shutil.which(b)
        if found:
            return found
    return None


def speed_bench_deps_available() -> bool:
    """True when the current interpreter (the one speed-bench would be spawned
    with) can import the speed_bench.py client's third-party deps."""
    return all(importlib.util.find_spec(m) is not None for m in _SPEED_BENCH_DEPS)


def detect_binaries(bin_dir: str | None = None,
                    data_dir: str | None = None) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for server_id in SERVERS:
        out[server_id] = resolve_bench_binary(server_id, bin_dir) is not None
    out["speed-bench"] = (resolve_speed_bench_script(bin_dir, data_dir=data_dir) is not None
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
        for cand in _binary_candidates("llama-server"):
            candidate = Path(bin_dir) / cand
            if candidate.is_file():
                return str(candidate)
    for b in meta["serving_binaries"]:
        found = shutil.which(b)
        if found:
            return found
    return None


def resolve_speed_bench_script(bin_dir: str | None = None,
                               configured: str | Path | None = None,
                               data_dir: str | Path | None = None) -> str | None:
    """Locate speed_bench.py. Honors an explicitly configured path, otherwise
    auto-discovers it in the llama.cpp source tree that contains the resolved
    llama-server binary, then falls back to a copy previously provisioned into
    data_dir/speed-bench/."""
    if configured:
        p = Path(configured)
        if p.is_file():
            return str(p)
    server = resolve_serving_binary("llama.cpp", bin_dir)
    if server:
        bin_path = Path(server).parent
        for parent in [bin_path, *bin_path.parents[:3]]:
            candidate = parent / "tools" / "server" / "bench" / "speed-bench" / "speed_bench.py"
            if candidate.is_file():
                return str(candidate)
    if data_dir:
        provisioned = Path(data_dir) / "speed-bench" / "speed_bench.py"
        if provisioned.is_file():
            return str(provisioned)
    return None


SPEED_BENCH_SCRIPT_URL = (
    "https://raw.githubusercontent.com/ggml-org/llama.cpp/master/"
    "tools/server/bench/speed-bench/speed_bench.py"
)

_provision_lock = threading.Lock()
_provision_attempted: set[str] = set()


def ensure_speed_bench_script(bin_dir: str | None = None,
                              configured: str | Path | None = None,
                              data_dir: str | Path | None = None) -> str | None:
    """Like resolve_speed_bench_script, but if the script is missing (and no
    explicit configured path is set) it best-effort downloads the client from
    the llama.cpp repo into data_dir/speed-bench/ once per process. Never
    raises; returns the script path or None."""
    script = resolve_speed_bench_script(bin_dir, configured, data_dir)
    if script:
        return script
    if configured:
        return None
    if not data_dir:
        return None
    target = Path(data_dir) / "speed-bench" / "speed_bench.py"
    key = str(target)
    with _provision_lock:
        if key in _provision_attempted:
            return None
        _provision_attempted.add(key)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        resp = httpx.get(SPEED_BENCH_SCRIPT_URL, timeout=20)
        resp.raise_for_status()
        target.write_text(resp.text, encoding="utf-8")
    except Exception:
        return None
    return str(target) if target.is_file() else None


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


def speed_bench_default_flags(osl: int = 528) -> str:
    return f"--bench qualitative --category all --limit 1 --osl {osl}"


def _split_windows(text: str) -> list[str]:
    """Split a command line the way Windows treats it: backslashes are literal
    (so C:\\Users\\... survives intact), double and single quotes group
    whitespace and are stripped, and an unclosed quote raises ValueError.
    Separates tokens on whitespace (spaces, tabs, and CR/LF)."""
    args: list[str] = []
    cur: list[str] = []
    quote: str | None = None
    for ch in text:
        if quote is not None:
            if ch == quote:
                quote = None
            else:
                cur.append(ch)
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch in " \t\r\n":
            if cur:
                args.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if quote is not None:
        raise ValueError("No closing quotation")
    if cur:
        args.append("".join(cur))
    return args


def _has_windows_path(text: str) -> bool:
    """True when the text contains a Windows drive-letter path (X:\\...), which
    cannot be a valid POSIX path, so it is tokenized with Windows rules on any
    OS."""
    return re.search(r"[A-Za-z]:\\", text) is not None


def _split_command(text: str, windows: bool | None = None) -> list[str]:
    """Tokenize a command string. With windows=True backslashes are kept literal
    and quotes group whitespace; otherwise it delegates to shlex.split (POSIX).
    Defaults to the current OS, except that a Windows drive-letter path anywhere
    in the text forces Windows tokenization on any platform."""
    if windows is None:
        windows = os.name == "nt" or _has_windows_path(text)
    if windows:
        return _split_windows(text)
    return shlex.split(text)


def parse_speed_bench_flags(text: str) -> list[str]:
    """Split the user-edited flags string into tokens. Drop any leading bare
    tokens (so pasting the full command works) and normalize --flag=value."""
    tokens = _split_command(text)
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
    try:
        tokens = _split_command(serving_command)
    except ValueError as exc:
        raise ValueError(f"invalid serving command: {exc}") from exc
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
    try:
        tokens = _split_command(command)
    except ValueError as exc:
        raise ValueError(f"invalid serving command: {exc}") from exc
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
    raise ValueError(f"unknown server {server_id}")
