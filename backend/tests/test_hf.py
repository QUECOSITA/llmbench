from app.hf import normalize_input, InvalidModelInput, parse_input


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
