import asyncio

import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path, gguf_dir=tmp_path / "gguf",
                        workload_file=tmp_path / "prompts.jsonl")
    (tmp_path / "prompts.jsonl").write_text("{\"prompt\": \"hi\"}\n")
    with TestClient(create_app(settings)) as c:
        yield c


def test_servers_endpoint(client):
    r = client.get("/api/servers")
    assert r.status_code == 200
    assert set(r.json()["readiness"]) == {"llama.cpp", "vllm", "sglang"}


def test_analyze_normalizes_and_reads_readme(client, httpx_mock):
    httpx_mock.add_response(
        url="https://huggingface.co/api/models/org/model/tree/main",
        json=[{"path": "README.md", "type": "file", "size": 100}],
    )
    httpx_mock.add_response(url="https://huggingface.co/org/model/raw/main/README.md",
                            text="# M\n\n```\nvllm serve org/model --max-model-len 8192\n```")
    r = client.post("/api/models/analyze", json={"input": "https://huggingface.co/org/model"})
    assert r.status_code == 200
    body = r.json()
    assert body["repo_id"] == "org/model"
    assert body["detected_server"] == "vllm"


def test_generate_configs_endpoint(client):
    r = client.post("/api/configs/generate", json={
        "repo_id": "org/model", "server_id": "vllm", "n": 3, "vram_gb": 24.0,
        "readme_flags": {"--max-model-len": "8192"},
    })
    assert r.status_code == 200
    assert len(r.json()["configs"]) == 3


def test_start_run_rejects_duplicate(client, monkeypatch):
    release = asyncio.Event()

    class HangProcess:
        returncode = 0
        killed = False

        async def communicate(self):
            await release.wait()
            return b"", ""

        async def wait(self):
            pass

        def kill(self):
            self.killed = True

    async def fake_create(*a, **k):
        return HangProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    cfg = {
        "server_id": "llama.cpp",
        "flags": {"-c": "4096"},
        "model_id": "org/model",
        "serving_command": "llama-server -m x",
        "bench_command": ["llama-bench", "-m", "x"],
    }
    r1 = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg]})
    assert r1.status_code in (200, 422)
    r2 = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg]})
    assert r2.status_code == 409
    release.set()
