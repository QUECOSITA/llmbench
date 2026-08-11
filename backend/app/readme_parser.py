import re

_SERVERS = ("llama.cpp",)

_COMMAND_PATTERNS = {
    "llama.cpp": [
        r"\bllama-server\b", r"\bllama-cli\b", r"\bllama-bench\b", r"\bllama\.cpp\b",
    ],
}

_FLAG_RE = re.compile(
    r"(?<![A-Za-z0-9])(-{1,2}[a-z][\w-]*)"
    r"(?:\s*=\s*(\S+)|(?:\s+((?:-\d+\.?\d*|[^\s-][^\s]*))))?",
    re.IGNORECASE,
)

_VALUE_TERMINATORS = {"--", "-m", "-c", "-t", "-b", "-ngl", "&&", "|", ";", "\\"}

_QUOTE_OPENS = ("$'", '$"', "'", '"')

_ANSI_ESCAPES = {
    "a": "\a", "b": "\b", "e": "\x1b", "f": "\f",
    "n": "\n", "r": "\r", "t": "\t", "v": "\v",
    "\\": "\\", "'": "'", '"': '"',
}


def _decode_ansi_escape(text: str, i: int) -> tuple[str, int]:
    """Decode the ANSI-C escape beginning at text[i] (a backslash)."""
    if i + 1 >= len(text):
        return "\\", 1
    ch = text[i + 1]
    if ch in _ANSI_ESCAPES:
        return _ANSI_ESCAPES[ch], 2
    if ch == "x":
        j = i + 2
        hexdigits = ""
        while j < len(text) and len(hexdigits) < 2 and text[j] in "0123456789abcdefABCDEF":
            hexdigits += text[j]
            j += 1
        if hexdigits:
            return chr(int(hexdigits, 16)), j - i
    if ch in "01234567":
        j = i + 1
        octdigits = ""
        while j < len(text) and len(octdigits) < 3 and text[j] in "01234567":
            octdigits += text[j]
            j += 1
        return chr(int(octdigits, 8)), j - i
    return "\\" + ch, 2


def _consume_quoted_value(text: str, start: int) -> tuple[str | None, int, bool]:
    """If text[start:] begins a quoted value, return (decoded_value, end_after_quote,
    unterminated). unterminated is True only when a quote opened but never closed."""
    while start < len(text) and text[start].isspace():
        start += 1
    rest = text[start:]
    opener = next((op for op in _QUOTE_OPENS if rest.startswith(op)), None)
    if opener is None:
        return None, start, False
    ansi = opener in ("$'", '$"')
    qchar = opener[-1]
    i = len(opener)
    out: list[str] = []
    while i < len(rest):
        ch = rest[i]
        if ansi and ch == "\\":
            decoded, consumed = _decode_ansi_escape(rest, i)
            out.append(decoded)
            i += consumed
            continue
        if ch == qchar:
            return "".join(out), start + i + 1, False
        out.append(ch)
        i += 1
    return None, start, True


def detect_serving_programs(readme: str, has_gguf: bool) -> dict[str, int]:
    scores = {"llama.cpp": 0}
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


def _is_negative_number(value: str) -> bool:
    try:
        float(value[1:])
        return True
    except ValueError:
        return False


def extract_flags(text: str, servers: list[str]) -> dict[str, str]:
    """Return {flag: value|''} parsed from code blocks plus the full text,
    gated on known server command mentions."""
    flags: dict[str, str] = {}
    fenced = re.findall(r"```[^\n]*\n(.*?)```", text, re.DOTALL)
    blocks = fenced if fenced else [text]
    for block in blocks:
        if not any(any(re.search(p, block, re.IGNORECASE) for p in _COMMAND_PATTERNS.get(s, ())) for s in servers):
            continue
        i = 0
        while True:
            m = _FLAG_RE.search(block, i)
            if m is None:
                break
            flag = m.group(1)
            q_value, q_end, unterminated = _consume_quoted_value(block, m.end(1))
            if unterminated:
                i = m.end()
                continue
            if q_value is not None:
                flags[flag] = q_value
                i = q_end
                continue
            value = (m.group(2) or m.group(3) or "").strip(" '\"")
            if value and value in _VALUE_TERMINATORS:
                value = ""
            elif value.startswith("-") and not _is_negative_number(value):
                value = ""
            flags[flag] = value
            i = m.end()
    return flags
