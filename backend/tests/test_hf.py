from pathlib import Path

import app.hf as hf_mod
from app.hf import hf_bin, normalize_input, InvalidModelInput, parse_input


def _fake_python(tmp_path, shim_name):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    if shim_name:
        (bin_dir / shim_name).write_text("")
    return str(bin_dir / "python.exe")


def test_hf_bin_prefers_venv_shim(tmp_path, monkeypatch):
    python = _fake_python(tmp_path, "hf.exe")
    monkeypatch.setattr(hf_mod.sys, "executable", python)
    monkeypatch.setattr(hf_mod.shutil, "which", lambda *a, **k: "/usr/bin/hf")
    assert hf_bin() == str(Path(python).parent / "hf.exe")


def test_hf_bin_falls_back_to_path_when_no_venv_shim(tmp_path, monkeypatch):
    python = _fake_python(tmp_path, None)
    monkeypatch.setattr(hf_mod.sys, "executable", python)
    monkeypatch.setattr(hf_mod.shutil, "which", lambda *a, **k: "/usr/bin/hf")
    assert hf_bin() == "/usr/bin/hf"


def test_hf_bin_none_when_no_venv_shim_and_no_path(tmp_path, monkeypatch):
    python = _fake_python(tmp_path, None)
    monkeypatch.setattr(hf_mod.sys, "executable", python)
    monkeypatch.setattr(hf_mod.shutil, "which", lambda *a, **k: None)
    assert hf_bin() is None


def test_normalize_repo_id():
    assert normalize_input("org/model") == "org/model"


def test_normalize_full_link():
    assert normalize_input("https://huggingface.co/org/model") == "org/model"


def test_normalize_link_with_suffix():
    assert normalize_input("http://huggingface.co/org/model/tree/main") == "org/model"
    assert normalize_input("https://www.huggingface.co/org/model/blob/main/README.md") == "org/model"


def test_normalize_trailing_slash():
    assert normalize_input("  org/model/  ") == "org/model"


def test_parse_input_repo_only():
    assert parse_input("org/model") == ("org/model", None)
    assert parse_input("https://huggingface.co/org/model") == ("org/model", None)


def test_parse_input_repo_and_file():
    assert parse_input("org/model/file.gguf") == ("org/model", "file.gguf")
    assert parse_input("unsloth/gemma-4-E4B-it-GGUF/gemma-4-E4B-it-IQ4_XS.gguf") == (
        "unsloth/gemma-4-E4B-it-GGUF", "gemma-4-E4B-it-IQ4_XS.gguf")


def test_normalize_repo_and_file():
    assert normalize_input("org/model/file.gguf") == "org/model"


def test_parse_input_direct_file_link():
    repo, path = parse_input(
        "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf"
    )
    assert repo == "Qwen/Qwen2.5-7B-Instruct-GGUF"
    assert path == "qwen2.5-7b-instruct-q4_k_m.gguf"


def test_parse_input_blob_and_raw_links():
    assert parse_input("https://huggingface.co/org/model/blob/main/x.gguf") == ("org/model", "x.gguf")
    assert parse_input("https://huggingface.co/org/model/raw/main/y.bin") == ("org/model", "y.bin")


def test_parse_input_invalid():
    for bad in ["", "org", "org/model/extra/deep"]:
        try:
            parse_input(bad)
            raise AssertionError(f"expected InvalidModelInput for {bad!r}")
        except InvalidModelInput:
            pass


def test_invalid_input():
    for bad in ["", "org", "https://google.com/foo", "org/model/extra/deep"]:
        try:
            normalize_input(bad)
            raise AssertionError(f"expected InvalidModelInput for {bad!r}")
        except InvalidModelInput:
            pass


import httpx
import pytest
from app.hf import HfClient


@pytest.fixture
def hf_client():
    return HfClient(base_url="https://huggingface.co")


def test_fetch_readme_and_files(hf_client, httpx_mock):
    httpx_mock.add_response(
        url="https://huggingface.co/api/models/org/model/tree/main",
        json=[
            {"path": "README.md", "type": "file", "size": 100},
            {"path": "config.json", "type": "file", "size": 50},
            {"path": "model-00001-of-00002.safetensors", "type": "file", "size": 1000},
            {"path": "model.safetensors.index.json", "type": "file", "size": 10},
        ],
    )
    httpx_mock.add_response(
        url="https://huggingface.co/org/model/raw/main/README.md",
        text="# Org/model\n\nRun it with `vllm serve Org/model --max-model-len 8192`.",
    )
    readme, files = hf_client.fetch_repo("org/model")
    assert "vllm serve" in readme
    gguf = [f for f in files if f["path"].endswith(".gguf")]
    assert gguf == []
    sizes = hf_client.weights_size_bytes(files)
    assert sizes == 1000


def test_gguf_list(hf_client, httpx_mock):
    httpx_mock.add_response(
        url="https://huggingface.co/api/models/org/llm/tree/main",
        json=[
            {"path": "org-llm-Q4_K_M.gguf", "type": "file", "size": 4_000_000_000},
            {"path": "org-llm-Q8_0.gguf", "type": "file", "size": 8_000_000_000},
        ],
    )
    readme, files = hf_client.fetch_repo("org/llm")
    assert sorted(f["path"] for f in files) == [
        "org-llm-Q4_K_M.gguf",
        "org-llm-Q8_0.gguf",
    ]


def test_repo_not_found(hf_client, httpx_mock):
    httpx_mock.add_response(url="https://huggingface.co/api/models/nope/x/tree/main",
                            status_code=404, json={"error": "Not found"})
    with pytest.raises(httpx.HTTPStatusError):
        hf_client.fetch_repo("nope/x")


def test_fetch_config_returns_json(hf_client, httpx_mock):
    httpx_mock.add_response(
        url="https://huggingface.co/org/model/raw/main/config.json",
        json={"num_hidden_layers": 40, "num_attention_heads": 64,
              "hidden_size": 8192, "max_position_embeddings": 32768},
    )
    cfg = hf_client.fetch_config("org/model")
    assert cfg["num_hidden_layers"] == 40


def test_fetch_config_missing_returns_none(hf_client, httpx_mock):
    httpx_mock.add_response(url="https://huggingface.co/org/model/raw/main/config.json",
                            status_code=404, json={"error": "Not found"})
    assert hf_client.fetch_config("org/model") is None
