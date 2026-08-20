import sys

import httpx
import pytest

from app.servers import SERVERS, detect_binaries, build_bench_command, resolve_bench_binary, README_FLAG_MAP
from app.servers import parse_serving_command, model_ref_from_flags
from app.servers import serving_command_display_flags
from app.servers import (is_spec_decoding_model, resolve_serving_binary, resolve_speed_bench_script,
                         build_server_command, build_speed_bench_command, speed_bench_deps_available,
                         parse_speed_bench_flags, validate_speed_bench_flags, speed_bench_default_flags,
                         ensure_speed_bench_script, _split_command)
from app.servers import (agentic_default_flags, build_agentic_command,
                         parse_agentic_flags, validate_agentic_flags)


def test_detect_finds_llama_bench(monkeypatch):
    monkeypatch.setattr("app.servers.shutil.which", lambda name: "/usr/bin/llama-bench" if name == "llama-bench" else None)
    assert detect_binaries()["llama.cpp"] is True


def test_detect_missing(monkeypatch):
    monkeypatch.setattr("app.servers.shutil.which", lambda name: None)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    assert detect_binaries() == {"llama.cpp": False, "speed-bench": False}


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
    cmd = build_bench_command("llama.cpp", model_ref="org/model",
                              flags={"--ctx-size": "4096", "--n-gpu-layers": "999", "-hf": "org/model"},
                              workload=str(workload), timeout_s=60,
                              gguf_filename="x.gguf")
    assert cmd[0] == "llama-bench"
    assert cmd[cmd.index("-hfr") + 1] == "org/model"
    assert cmd[cmd.index("-hff") + 1] == "x.gguf"
    assert "-m" not in cmd
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


def test_build_bench_command_llama_filters_server_only_flags(tmp_path):
    workload = tmp_path / "p.jsonl"
    workload.write_text('{"prompt": "hello world"}\n')
    flags = {
        "--ctx-size": "4096",
        "--n-gpu-layers": "999",
        "--fit": "on",
        "--spec-type": "mtp",
        "--spec-draft-n-max": "2",
        "--no-mmap": "\\",
        "--jinja": "\\",
        "-m": "Qwen3.6-27B-MTP-UD-IQ3_XXS.gguf",
    }
    cmd = build_bench_command("llama.cpp", "org/model", flags,
                              workload=str(workload), timeout_s=60,
                              gguf_filename="Qwen3.6-27B-MTP-UD-IQ3_XXS.gguf")
    assert cmd[cmd.index("-hfr") + 1] == "org/model"
    assert cmd[cmd.index("-hff") + 1] == "Qwen3.6-27B-MTP-UD-IQ3_XXS.gguf"
    assert "-m" not in cmd
    for bad in ("--fit", "--spec-type", "--spec-draft-n-max", "--no-mmap", "--jinja"):
        assert bad not in cmd


def test_build_bench_command_llama_keeps_bench_relevant_flags(tmp_path):
    workload = tmp_path / "p.jsonl"
    workload.write_text('{"prompt": "hello world"}\n')
    cmd = build_bench_command("llama.cpp", "/models/x.gguf",
                              {"--ctx-size": "4096", "-fa": "on", "-ctk": "q4_0", "-ctv": "q4_0", "-t": "20"},
                              workload=str(workload), timeout_s=60)
    assert cmd[cmd.index("-fa") + 1] == "on"
    assert cmd[cmd.index("-ctk") + 1] == "q4_0"
    assert cmd[cmd.index("-ctv") + 1] == "q4_0"
    assert cmd[cmd.index("-t") + 1] == "20"


def test_build_bench_command_llama_generated_ctx_wins_over_readme_alias(tmp_path):
    workload = tmp_path / "p.jsonl"
    workload.write_text('{"prompt": "hello world"}\n')
    cmd = build_bench_command("llama.cpp", "/models/x.gguf",
                              {"--ctx-size": "4096", "-c": "57344"},
                              workload=str(workload), timeout_s=60)
    assert cmd[cmd.index("--fit-ctx") + 1] == "4096"
    assert "-c" not in cmd


def test_build_bench_command_llama_bare_bool_flag(tmp_path):
    cmd = build_bench_command("llama.cpp", "/models/x.gguf", {"--enforce-eager": ""},
                              workload="/nonexistent/prompts.jsonl", timeout_s=60)
    assert "--enforce-eager" not in cmd
    assert cmd[cmd.index("-p") + 1] == "512"
    assert cmd[-4:] == ["-r", "2", "-o", "csv"]


def test_readme_flag_map_aliases():
    assert README_FLAG_MAP["llama.cpp"]["-c"] == "--ctx-size"


def test_build_bench_command_llama_no_gguf_filename_uses_m(tmp_path):
    workload = tmp_path / "p.jsonl"
    workload.write_text('{"prompt": "hello world"}\n')
    cmd = build_bench_command("llama.cpp", "org/model", {"--ctx-size": "4096"},
                              workload=str(workload), timeout_s=60)
    assert cmd[cmd.index("-m") + 1] == "org/model"
    assert "-hfr" not in cmd


def test_parse_serving_command_llama_hf_pair():
    cmd = "llama-server --hf-repo org/model --hf-file x.gguf --ctx-size 4096 --n-gpu-layers 999"
    assert parse_serving_command("llama.cpp", cmd) == {
        "--hf-repo": "org/model",
        "--hf-file": "x.gguf",
        "--ctx-size": "4096",
        "--n-gpu-layers": "999",
    }


def test_parse_serving_command_llama_local_model_and_alias():
    assert parse_serving_command("llama.cpp", "llama-server -m /models/x.gguf -c 2048") == {
        "-m": "/models/x.gguf",
        "-c": "2048",
    }


def test_parse_serving_command_llama_bare_bool_flag():
    assert parse_serving_command("llama.cpp", "llama-server -m x --no-mmap") == {
        "-m": "x",
        "--no-mmap": "",
    }


def test_parse_serving_command_empty():
    assert parse_serving_command("llama.cpp", "  ") == {}


def test_serving_command_display_flags_hf_pair_canonical():
    cmd = "llama-server --hf-repo org/model --hf-file x.gguf --ctx-size 8192 -ngl 40"
    assert serving_command_display_flags("llama.cpp", cmd) == {
        "--ctx-size": "8192",
        "--n-gpu-layers": "40",
    }


def test_serving_command_display_flags_local_model_drops_m_and_plumbing():
    cmd = "llama-server -m /models/x.gguf -c 2048 --port 8080 --host 0.0.0.0"
    assert serving_command_display_flags("llama.cpp", cmd) == {
        "--ctx-size": "2048",
    }


def test_serving_command_display_flags_bare_boolean():
    cmd = "llama-server -m x --flash-attn"
    assert serving_command_display_flags("llama.cpp", cmd) == {"--flash-attn": ""}


def test_serving_command_display_flags_empty_and_malformed():
    assert serving_command_display_flags("llama.cpp", "  ") == {}
    assert serving_command_display_flags("llama.cpp", "llama-server --reasoning-budget-message $'\n") == {}


def test_serving_command_display_flags_short_alias_canonicalized():
    cmd = "llama-server -m x -c 54000"
    assert serving_command_display_flags("llama.cpp", cmd) == {"--ctx-size": "54000"}


def test_model_ref_from_flags_llama_hf_pair():
    flags = {"--hf-repo": "org/model", "--hf-file": "x.gguf"}
    assert model_ref_from_flags("llama.cpp", flags, "org/model") == ("org/model", "x.gguf")


def test_model_ref_from_flags_llama_local_model():
    assert model_ref_from_flags("llama.cpp", {"-m": "/models/x.gguf"}, "org/model") == ("/models/x.gguf", None)


def test_model_ref_from_flags_fallbacks():
    assert model_ref_from_flags("llama.cpp", {}, "org/model") == ("org/model", None)


def test_roundtrip_rebuild_bench_command_matches_generated(tmp_path):
    from app.flags import build_serving_command, generate_configs

    def normalized(flags):
        return {k: ("" if v == k else v) for k, v in flags.items()}

    workload = tmp_path / "p.jsonl"
    workload.write_text('{"prompt": "hello world"}\n')
    repo_id = "org/model"
    for server_id in ("llama.cpp",):
        for cfg in generate_configs(server_id, {}, n=3, vram_gb=24.0):
            gguf = "x.gguf"
            serving = build_serving_command(server_id, repo_id, cfg["flags"], gguf_filename=gguf)
            original = build_bench_command(server_id, repo_id, normalized(cfg["flags"]),
                                           workload=str(workload), timeout_s=60, gguf_filename=gguf)
            parsed = parse_serving_command(server_id, serving)
            assert all(parsed.get(k) == v for k, v in normalized(cfg["flags"]).items())
            model_ref, gguf2 = model_ref_from_flags(server_id, parsed, repo_id)
            rebuilt = build_bench_command(server_id, model_ref, parsed,
                                          workload=str(workload), timeout_s=60, gguf_filename=gguf2)
            assert rebuilt == original, (server_id, rebuilt, original)


def test_is_spec_decoding_model_mtp_in_repo():
    assert is_spec_decoding_model("GazTrab/Qwen3.6-27B-MTP-UD-IQ3_XXS-GGUF") is True


def test_is_spec_decoding_model_mtp_in_gguf():
    assert is_spec_decoding_model("org/model", gguf_filename="Qwen3.6-27B-MTP-UD-IQ3_XXS.gguf") is True


def test_is_spec_decoding_model_mtp_case_insensitive():
    assert is_spec_decoding_model("org/qwen3-mtp-model") is True


def test_is_spec_decoding_model_readme_spec_type():
    assert is_spec_decoding_model("org/model", readme_flags={"--spec-type": "draft-mtp"}) is True


def test_is_spec_decoding_model_readme_draft_flag():
    assert is_spec_decoding_model("org/model", readme_flags={"-md": "draft.gguf"}) is True


def test_is_spec_decoding_model_false():
    assert is_spec_decoding_model("org/model", gguf_filename="model.Q4_K_M.gguf",
                                  readme_flags={"--ctx-size": "4096"}) is False
    assert is_spec_decoding_model("org/model", readme_flags={}) is False


def test_resolve_serving_binary_uses_bin_dir(tmp_path):
    fake = tmp_path / "llama-server"
    fake.write_text("#!/bin/sh\n")
    assert resolve_serving_binary("llama.cpp", bin_dir=str(tmp_path)) == str(fake)


def test_resolve_bench_binary_windows_exe(tmp_path):
    from app.servers import resolve_bench_binary
    (tmp_path / "llama-bench.exe").write_bytes(b"x")
    assert resolve_bench_binary("llama.cpp", str(tmp_path)) == str(tmp_path / "llama-bench.exe")


def test_resolve_serving_binary_windows_exe(tmp_path):
    from app.servers import resolve_serving_binary
    (tmp_path / "llama-server.exe").write_bytes(b"x")
    assert resolve_serving_binary("llama.cpp", str(tmp_path)) == str(tmp_path / "llama-server.exe")


def test_resolve_speed_bench_script_configured_wins(tmp_path):
    configured = tmp_path / "speed_bench.py"
    configured.write_text("x")
    other = tmp_path / "other.py"
    other.write_text("x")
    assert resolve_speed_bench_script(configured=configured) == str(configured)


def test_resolve_speed_bench_script_auto_discovers(tmp_path):
    bin_dir = tmp_path / "build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    script = tmp_path / "tools" / "server" / "bench" / "speed-bench" / "speed_bench.py"
    script.parent.mkdir(parents=True)
    script.write_text("x")
    assert resolve_speed_bench_script(bin_dir=str(bin_dir)) == str(script)


def test_resolve_speed_bench_script_missing(tmp_path):
    bin_dir = tmp_path / "build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    assert resolve_speed_bench_script(bin_dir=str(bin_dir)) is None


def test_speed_bench_default_flags():
    assert speed_bench_default_flags() == "--bench qualitative --category all --limit 1 --osl 528"
    assert speed_bench_default_flags(osl=256) == "--bench qualitative --category all --limit 1 --osl 256"


def test_parse_speed_bench_flags_defaults():
    flags = parse_speed_bench_flags("--bench throughput_1k --category all --limit 1 --osl 128")
    assert flags == ["--bench", "throughput_1k", "--category", "all", "--limit", "1", "--osl", "128"]


def test_parse_speed_bench_flags_drops_leading_bare_tokens():
    flags = parse_speed_bench_flags("python3 /x/speed_bench.py --bench qualitative --limit 2")
    assert flags == ["--bench", "qualitative", "--limit", "2"]


def test_parse_speed_bench_flags_extra_flags():
    flags = parse_speed_bench_flags("--bench throughput_1k --concurrency 4 --timeout 120")
    assert flags == ["--bench", "throughput_1k", "--concurrency", "4", "--timeout", "120"]


def test_parse_speed_bench_flags_equals_form():
    flags = parse_speed_bench_flags("--bench=qualitative --category=coding")
    assert flags == ["--bench", "qualitative", "--category", "coding"]


def test_parse_speed_bench_flags_keeps_dash_prefixed_value_attached():
    flags = parse_speed_bench_flags("--model=-hf:org/Qwen3")
    assert flags == ["--model=-hf:org/Qwen3"]


def test_validate_speed_bench_flags_dash_prefixed_value_ok():
    assert validate_speed_bench_flags(["--model=-hf:org/Qwen3"]) is None
    assert validate_speed_bench_flags(["--bench", "throughput_1k", "--model=-hf:org/Qwen3"]) is None


def test_validate_speed_bench_flags_valid():
    assert validate_speed_bench_flags(["--bench", "throughput_1k", "--category", "all", "--limit", "1", "--osl", "128"]) is None


def test_validate_speed_bench_flags_unknown_flag():
    err = validate_speed_bench_flags(["--foo", "bar"])
    assert err is not None and "unknown speed-bench flag '--foo'" in err
    assert "--url" in err and "--output" in err


def test_validate_speed_bench_flags_bad_bench():
    err = validate_speed_bench_flags(["--bench", "foo"])
    assert err is not None and "unknown --bench 'foo'" in err
    assert "throughput_1k" in err


def test_validate_speed_bench_flags_bad_category_per_bench():
    err = validate_speed_bench_flags(["--bench", "throughput_1k", "--category", "coding"])
    assert err is not None and "unknown --category 'coding' for bench 'throughput_1k'" in err
    assert "high_entropy" in err
    err2 = validate_speed_bench_flags(["--bench", "qualitative", "--category", "high_entropy"])
    assert err2 is not None and "unknown --category 'high_entropy' for bench 'qualitative'" in err2


def test_validate_speed_bench_flags_all_category_valid_for_any_bench():
    assert validate_speed_bench_flags(["--bench", "qualitative", "--category", "all"]) is None
    assert validate_speed_bench_flags(["--bench", "throughput_1k", "--category", "all"]) is None


def test_validate_speed_bench_flags_reserved_url_output():
    err = validate_speed_bench_flags(["--url", "localhost:9000"])
    assert err is not None and "managed by the app" in err
    err2 = validate_speed_bench_flags(["--output", "x.json"])
    assert err2 is not None and "managed by the app" in err2


def test_validate_speed_bench_flags_bare_token():
    err = validate_speed_bench_flags(["--bench", "throughput_1k", "stray"])
    assert err is not None and "unexpected token 'stray'" in err


def test_validate_speed_bench_flags_missing_value():
    err = validate_speed_bench_flags(["--osl", "--bench"])
    assert err is not None and "requires a value" in err


def test_build_speed_bench_command_with_flags(tmp_path):
    script = str(tmp_path / "speed_bench.py")
    cmd = build_speed_bench_command(script, ["--bench", "qualitative", "--limit", "2"],
                                    url="localhost:8080", output="/tmp/out.json")
    assert cmd[0] == sys.executable
    assert cmd[1] == script
    assert cmd[cmd.index("--bench") + 1] == "qualitative"
    assert cmd[cmd.index("--limit") + 1] == "2"
    assert cmd[cmd.index("--url") + 1] == "localhost:8080"
    assert cmd[cmd.index("--output") + 1] == "/tmp/out.json"


def test_build_server_command_swaps_binary_and_strips_port(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    tokens = build_server_command(
        "llama-server -m /models/x.gguf --spec-type draft-mtp --port 9999 --host 0.0.0.0 -p 4",
        bin_dir=str(bin_dir))
    assert tokens[0] == str(bin_dir / "llama-server")
    assert "--port" not in tokens and "9999" not in tokens
    assert "--host" not in tokens and "0.0.0.0" not in tokens
    assert "-p" in tokens and "4" in tokens
    assert tokens[tokens.index("--spec-type") + 1] == "draft-mtp"


def test_speed_bench_deps_available_true(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    assert speed_bench_deps_available() is True


def test_speed_bench_deps_available_false(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    assert speed_bench_deps_available() is False


def test_detect_binaries_speed_bench_deps_gate(monkeypatch, tmp_path):
    monkeypatch.setattr("app.servers.resolve_speed_bench_script",
                        lambda *a, **k: str(tmp_path / "speed_bench.py"))
    monkeypatch.setattr("app.servers.speed_bench_deps_available", lambda: False)
    assert detect_binaries()["speed-bench"] is False
    monkeypatch.setattr("app.servers.speed_bench_deps_available", lambda: True)
    assert detect_binaries()["speed-bench"] is True


def test_build_server_command_malformed_raises_clear_error():
    try:
        build_server_command("llama-server --reasoning-budget-message $'\n")
    except ValueError as exc:
        assert "invalid serving command" in str(exc)
        assert "closing quotation" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_parse_serving_command_malformed_raises_clear_error():
    try:
        parse_serving_command("llama.cpp", "llama-server --reasoning-budget-message $'\n")
    except ValueError as exc:
        assert "invalid serving command" in str(exc)
        assert "closing quotation" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_split_command_windows_preserves_backslash_path():
    text = r"llama-server -m C:\Users\Ruben\.llmbench\gguf\model.gguf --spec-type draft-mtp"
    assert _split_command(text, windows=True) == [
        "llama-server", "-m", r"C:\Users\Ruben\.llmbench\gguf\model.gguf",
        "--spec-type", "draft-mtp",
    ]


def test_split_command_windows_quoted_path_with_spaces():
    text = r'llama-server -m "C:\Program Files\llama\model.gguf" -c 2048'
    assert _split_command(text, windows=True) == [
        "llama-server", "-m", r"C:\Program Files\llama\model.gguf", "-c", "2048",
    ]


def test_split_command_windows_flag_list():
    text = "--bench qualitative --category all --limit 1 --osl 528"
    assert _split_command(text, windows=True) == [
        "--bench", "qualitative", "--category", "all", "--limit", "1", "--osl", "528",
    ]


def test_split_command_windows_splits_crlf():
    text = "--bench qualitative\r\n--limit 2"
    assert _split_command(text, windows=True) == ["--bench", "qualitative", "--limit", "2"]


def test_split_command_windows_unclosed_quote_raises():
    with pytest.raises(ValueError) as exc:
        _split_command("llama-server --reasoning-budget-message $'\n", windows=True)
    assert "closing quotation" in str(exc.value)


def test_split_command_posix_default_matches_shlex():
    assert _split_command("llama-server -m /models/x.gguf -c 2048", windows=False) == [
        "llama-server", "-m", "/models/x.gguf", "-c", "2048",
    ]


def test_split_command_auto_detects_windows_path_on_posix():
    assert _split_command(r"llama-server -m C:\Users\me\model.gguf -c 2048") == [
        "llama-server", "-m", r"C:\Users\me\model.gguf", "-c", "2048",
    ]


def test_build_server_command_windows_path_roundtrip(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    tokens = build_server_command(
        r"llama-server -m C:\Users\Ruben\.llmbench\gguf\model.gguf --spec-type draft-mtp --port 9999",
        bin_dir=str(bin_dir))
    assert tokens[0] == str(bin_dir / "llama-server")
    assert r"C:\Users\Ruben\.llmbench\gguf\model.gguf" in tokens


def test_detect_binaries_data_dir_discovery(tmp_path):
    provisioned = tmp_path / "data" / "speed-bench" / "speed_bench.py"
    provisioned.parent.mkdir(parents=True)
    provisioned.write_text("x")
    assert resolve_speed_bench_script(data_dir=str(tmp_path / "data")) == str(provisioned)


def test_ensure_speed_bench_script_downloads_into_data_dir(tmp_path, monkeypatch):
    class FakeResp:
        text = "#!/usr/bin/env python3\n"

        def raise_for_status(self):
            pass

    monkeypatch.setattr("app.servers.httpx.get", lambda *a, **k: FakeResp())
    data_dir = tmp_path / "data"
    script = ensure_speed_bench_script(data_dir=str(data_dir))
    assert script == str(data_dir / "speed-bench" / "speed_bench.py")
    assert (data_dir / "speed-bench" / "speed_bench.py").read_text() == "#!/usr/bin/env python3\n"


def test_ensure_speed_bench_script_download_failure_returns_none(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise httpx.HTTPError("offline")

    monkeypatch.setattr("app.servers.httpx.get", boom)
    assert ensure_speed_bench_script(data_dir=str(tmp_path / "data")) is None


def test_ensure_speed_bench_script_does_not_override_configured(tmp_path, monkeypatch):
    configured = tmp_path / "speed_bench.py"
    configured.write_text("x")
    monkeypatch.setattr(
        "app.servers.httpx.get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not download")),
    )
    assert ensure_speed_bench_script(configured=configured) == str(configured)


def test_ensure_speed_bench_script_finds_existing_script(tmp_path, monkeypatch):
    bin_dir = tmp_path / "build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    script = tmp_path / "tools" / "server" / "bench" / "speed-bench" / "speed_bench.py"
    script.parent.mkdir(parents=True)
    script.write_text("x")
    monkeypatch.setattr(
        "app.servers.httpx.get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not download")),
    )
    assert ensure_speed_bench_script(bin_dir=str(bin_dir)) == str(script)


def test_ensure_speed_bench_script_downloads_at_most_once(tmp_path, monkeypatch):
    calls = []

    def fake_get(*a, **k):
        calls.append(a)
        class _Resp:
            text = "x\n"
            def raise_for_status(self):
                pass
        return _Resp()

    monkeypatch.setattr("app.servers.httpx.get", fake_get)
    data_dir = tmp_path / "data"
    first = ensure_speed_bench_script(data_dir=str(data_dir))
    second = ensure_speed_bench_script(data_dir=str(data_dir))
    assert first is not None and second is not None
    assert len(calls) == 1


def test_build_bench_command_excludes_load_mode_and_no_mmproj(tmp_path):
    workload = tmp_path / "p.jsonl"
    workload.write_text('{"prompt": "hello world"}\n')
    cmd = build_bench_command(
        "llama.cpp", "/models/x.gguf",
        {"--ctx-size": "4096", "--load-mode": "none", "--no-mmproj": ""},
        workload=str(workload), timeout_s=60,
    )
    assert "--load-mode" not in cmd
    assert "--no-mmproj" not in cmd
    assert cmd[cmd.index("--fit-ctx") + 1] == "4096"


def test_agentic_default_flags():
    assert agentic_default_flags() == "--steps 10 --max-tokens 4096 --task codebase_refactor --tier medium"
    assert agentic_default_flags(steps=6, max_tokens=8192, task="research", tier="heavy") == \
        "--steps 6 --max-tokens 8192 --task research --tier heavy"


def test_parse_agentic_flags():
    assert parse_agentic_flags("--steps 10 --max-tokens 4096 --task research") == \
        ["--steps", "10", "--max-tokens", "4096", "--task", "research"]
    assert parse_agentic_flags("agentic --steps=6 --task=research") == \
        ["--steps", "6", "--task", "research"]
    assert parse_agentic_flags("  ") == []


def test_validate_agentic_flags_valid():
    assert validate_agentic_flags(["--steps", "10", "--max-tokens", "4096",
                                   "--task", "research"]) is None


def test_validate_agentic_flags_unknown_flag():
    err = validate_agentic_flags(["--foo", "1"])
    assert err is not None and "unknown agentic flag '--foo'" in err


def test_validate_agentic_flags_missing_value():
    err = validate_agentic_flags(["--steps"])
    assert err is not None and "requires a value" in err


def test_validate_agentic_flags_non_int():
    err = validate_agentic_flags(["--steps", "abc"])
    assert err is not None and "integer" in err


def test_validate_agentic_flags_out_of_range():
    assert validate_agentic_flags(["--steps", "0", "--max-tokens", "1"]) is not None
    assert validate_agentic_flags(["--steps", "21", "--max-tokens", "1"]) is not None
    assert validate_agentic_flags(["--steps", "10", "--max-tokens", "0"]) is not None
    assert validate_agentic_flags(["--steps", "10", "--max-tokens", "32769"]) is None
    assert validate_agentic_flags(["--steps", "10", "--max-tokens", "65728"]) is None
    assert validate_agentic_flags(["--steps", "10", "--max-tokens", "65729"]) is not None


def test_validate_agentic_flags_tier():
    assert validate_agentic_flags(["--tier", "heavy"]) is None
    err = validate_agentic_flags(["--tier", "nope"])
    assert err is not None and "unknown --tier" in err


def test_validate_agentic_flags_bad_task():
    err = validate_agentic_flags(["--task", "nope"])
    assert err is not None and "unknown --task" in err


def test_validate_agentic_flags_bare_token():
    err = validate_agentic_flags(["--steps", "10", "stray"])
    assert err is not None and "unexpected token 'stray'" in err


def test_build_agentic_command():
    cmd = build_agentic_command("org/model", ["--steps", "10", "--max-tokens", "4096", "--task", "research"])
    assert cmd == ["agentic", "--model", "org/model", "--steps", "10", "--max-tokens", "4096", "--task", "research"]
