import re

_SERVERS = ("llama.cpp", "vllm", "sglang")

_COMMAND_PATTERNS = {
    "llama.cpp": [
        r"\bllama-server\b", r"\bllama-cli\b", r"\bllama-bench\b", r"\bllama\.cpp\b",
    ],
    "vllm": [
        r"\bvllm\s+serve\b", r"\bfrom\s+vllm\b", r"\bapi_server\b",
        r"\bfrom\s+vllm\.entrypoints\b",
    ],
    "sglang": [
        r"\bsglang\.launch_server\b", r"\bsglang\s+serve\b", r"\bimport\s+sglang\b",
    ],
}

_FLAG_RE = re.compile(r"(?<![A-Za-z0-9])(-{1,2}[a-z][\w-]*)(?:\s*=\s*(\S+)|(?:\s+(\S+)))?", re.IGNORECASE)

_VALUE_TERMINATORS = {"--", "-m", "-c", "-t", "-b", "-ngl", "&&", "|", ";"}


def detect_serving_programs(readme: str, has_gguf: bool) -> dict[str, int]:
    scores = {"llama.cpp": 0, "vllm": 0, "sglang": 0}
    if has_gguf:
        scores["llama.cpp"] += 3
    for server, patterns in _COMMAND_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, readme, re.IGNORECASE):
                scores[server] += 2 if server == "llama.cpp" else 3
    return scores


def top_serving_program(scores: dict[str, int]) -> str | None:
    best = max(scores.values())
    if best <= 0:
        return None
    winners = [s for s, v in scores.items() if v == best]
    return winners[0] if len(winners) == 1 else None


def extract_flags(text: str, servers: list[str]) -> dict[str, str]:
    """Return {flag: value|''} parsed from code blocks mentioning known server commands."""
    flags: dict[str, str] = {}
    blocks = re.findall(r"```[^\n]*\n(.*?)```", text, re.DOTALL) + [text]
    for block in blocks:
        if not any(any(re.search(p, block, re.IGNORECASE) for p in _COMMAND_PATTERNS[s]) for s in servers):
            continue
        for m in _FLAG_RE.finditer(block):
            flag = m.group(1)
            value = (m.group(2) or m.group(3) or "").strip(" '\"")
            if value and value in _VALUE_TERMINATORS:
                value = ""
            flags[flag] = value
    return flags
