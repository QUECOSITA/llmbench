import shlex

from app.servers import README_FLAG_MAP

KEY_FLAGS = {
    "llama.cpp": ["--ctx-size", "--n-gpu-layers", "--batch-size", "--spec-type", "--spec-draft-n-max"],
}

VALUE_POOLS = {
    "llama.cpp": {
        "--ctx-size": [2048, 4096, 8192, 16384],
        "--n-gpu-layers": [999, 40, 0],
        "--batch-size": [512, 2048],
        "--spec-type": ["draft-mtp", "none"],
        "--spec-draft-n-max": [2, 3],
    },
}

# Pinned flags applied to every generated llama-server command, emitted first
# (right after the model reference). --load-mode none avoids mmap; --no-mmproj
# disables the mmproj auto-download that is on by default when using -hf.
LLAMA_PINNED_FLAGS = {"--load-mode": "none", "--no-mmproj": ""}

# README flags dropped during _baseline merge. Deprecated memory-mode flags and
# --defrag-thold/-dt are superseded by the pinned --load-mode none; the mmproj
# auto variants are superseded by the pinned --no-mmproj. Emitting these
# alongside --load-mode is itself deprecated (arg.cpp:883).
LLAMA_DROPPED_FLAGS = {
    "--mlock", "--mmap", "--no-mmap", "--direct-io", "--no-direct-io",
    "--defrag-thold", "-dt", "--mmproj-auto", "--no-mmproj-auto",
}

DEFAULTS = {
    "llama.cpp": {"--load-mode": "none", "--no-mmproj": "",
                  "--ctx-size": 4096, "--n-gpu-layers": 999, "--batch-size": 512,
                  "--spec-type": "draft-mtp", "--spec-draft-n-max": 2},
}


_SPEC_TYPE_ALIASES = {"mtp": "draft-mtp", "draft-mtp": "draft-mtp"}

_LLAMA_MODEL_FLAGS = {"-m", "-hf", "-hfr", "--hf-repo", "-hff", "--hf-file", "-hft", "--hf-token"}


def _baseline(server_id: str, readme_flags: dict[str, str], vram_gb: float) -> dict[str, str]:
    flags: dict[str, str] = {}
    for key, default in DEFAULTS[server_id].items():
        flags[key] = str(default)
    mapping = README_FLAG_MAP.get(server_id, {})
    canon_from_readme: set[str] = set()
    for flag, value in readme_flags.items():
        if flag in LLAMA_DROPPED_FLAGS:
            continue
        canon = mapping.get(flag, flag)
        # Only canonical long-form README entries override the defaults directly.
        if canon == flag:
            if canon == "--spec-type":
                value = _SPEC_TYPE_ALIASES.get(value, value)
            if flag in KEY_FLAGS[server_id] or flag not in DEFAULTS[server_id]:
                flags[canon] = value
                canon_from_readme.add(canon)
    for flag, value in readme_flags.items():
        if flag in LLAMA_DROPPED_FLAGS:
            continue
        canon = mapping.get(flag, flag)
        # Aliases (e.g. -c) map to their canonical long form; the long form
        # wins if the README also provided it explicitly.
        if canon != flag and canon not in canon_from_readme:
            if canon == "--spec-type":
                value = _SPEC_TYPE_ALIASES.get(value, value)
            if flag in KEY_FLAGS[server_id] or flag not in DEFAULTS[server_id]:
                flags[canon] = value
    # The pins are non-negotiable: a README may not override load-mode/mmproj.
    for flag, value in LLAMA_PINNED_FLAGS.items():
        flags[flag] = value
    return flags


def generate_configs(server_id: str, readme_flags: dict[str, str], n: int, vram_gb: float) -> list[dict]:
    if server_id not in KEY_FLAGS:
        raise ValueError(f"unknown server {server_id}")
    base = _baseline(server_id, readme_flags, vram_gb)
    configs = [{"flags": dict(base)}]
    seen = {tuple(sorted(base.items()))}
    for key in KEY_FLAGS[server_id]:
        base_val = base[key]
        for val in VALUE_POOLS[server_id][key]:
            sv = str(val)
            if sv == base_val:
                continue
            cfg = dict(base)
            cfg[key] = sv
            signature = tuple(sorted(cfg.items()))
            if signature in seen:
                continue
            seen.add(signature)
            configs.append({"flags": cfg})
    return configs[:n]


_SHELL_SPECIALS = " \t\n\"'\\$`"


def _shell_arg(value: str) -> str:
    if any(ch in value for ch in _SHELL_SPECIALS):
        return shlex.quote(value)
    return value


def _flag_tokens(flags: dict[str, str]) -> list[str]:
    tokens: list[str] = []
    for flag, value in flags.items():
        tokens.append(flag)
        if value and value != flag:
            tokens.append(_shell_arg(value))
    return tokens


def _drop_duplicate_aliases(server_id: str, flags: dict[str, str]) -> dict[str, str]:
    mapping = README_FLAG_MAP.get(server_id, {})
    emitted: set[str] = set()
    out: dict[str, str] = {}
    for flag, value in flags.items():
        canon = mapping.get(flag, flag)
        if canon in emitted:
            continue
        out[flag] = value
        emitted.add(canon)
    return out


def build_serving_command(server_id: str, repo_id: str, flags: dict[str, str],
                          gguf_filename: str | None = None,
                          gguf_path: str | None = None) -> str:
    if server_id == "llama.cpp":
        cmd = ["llama-server"]
        if gguf_filename:
            cmd += ["--hf-repo", repo_id, "--hf-file", gguf_filename]
        elif gguf_path:
            cmd += ["-m", gguf_path]
        if gguf_filename or gguf_path:
            flags = {k: v for k, v in flags.items() if k not in _LLAMA_MODEL_FLAGS}
        flags = _drop_duplicate_aliases(server_id, flags)
        cmd += _flag_tokens(flags)
        return " ".join(cmd)
    raise ValueError(f"unknown server {server_id}")
