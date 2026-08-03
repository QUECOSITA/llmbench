import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings

FAKE_BENCH = """\
model,size,params,backend,test,t,n_threads,batch,ngl,ms,t/s
x,Q4,7B,CUDA,pp,0,8,512,999,40,1000.0
x,Q4,7B,CUDA,tg,0,8,512,999,900,80.0
"""


class FakeProcess:
    def __init__(self, out, rc=0):
        self._out = out
        self.returncode = rc
        self.killed = False

    async def communicate(self):
        return self._out, b""

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


def _poll(predicate, timeout=3.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


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


def test_analyze_includes_fit_verdict_and_hardware(client, httpx_mock):
    httpx_mock.add_response(
        url="https://huggingface.co/api/models/org/model/tree/main",
        json=[{"path": "README.md", "type": "file", "size": 100},
              {"path": "model.safetensors", "type": "file", "size": 4000000000}],
    )
    httpx_mock.add_response(url="https://huggingface.co/org/model/raw/main/README.md",
                            text="# M\n")
    r = client.post("/api/models/analyze", json={"input": "org/model"})
    assert r.status_code == 200
    body = r.json()
    fv = body["fit_verdict"]
    assert isinstance(fv["warning"], bool)
    assert isinstance(fv["needed_gb"], float)
    assert fv["stage"] in ("gpu", "ram_offload", "ram", "no_fit")
    hw = body["hardware"]
    assert "gpu_vram_gb" in hw and "ram_total_gb" in hw and "gpu_name" in hw


def test_generate_configs_endpoint(client):
    r = client.post("/api/configs/generate", json={
        "repo_id": "org/model", "server_id": "vllm", "n": 3, "vram_gb": 24.0,
        "readme_flags": {"--max-model-len": "8192"},
    })
    assert r.status_code == 200
    configs = r.json()["configs"]
    assert len(configs) == 3
    for cfg in configs:
        assert isinstance(cfg["bench_command"], list)
        assert cfg["bench_command"][0] == "python"
        assert any("benchmark_throughput" in tok for tok in cfg["bench_command"])


def test_generate_configs_llama_uses_gguf_path(client):
    r = client.post("/api/configs/generate", json={
        "repo_id": "org/model", "server_id": "llama.cpp", "n": 2,
        "gguf_path": "/tmp/models/model.Q4_K_M.gguf",
        "readme_flags": {"-c": "4096"},
    })
    assert r.status_code == 200
    for cfg in r.json()["configs"]:
        cmd = cfg["bench_command"]
        assert cmd[0] == "llama-bench"
        assert cmd[cmd.index("-m") + 1] == "/tmp/models/model.Q4_K_M.gguf"


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


def test_analyze_missing_input_422(client):
    r = client.post("/api/models/analyze", json={})
    assert r.status_code == 422


def test_generate_missing_server_422(client):
    r = client.post("/api/configs/generate", json={})
    assert r.status_code == 422


@pytest.mark.parametrize("n", [0, -1])
def test_generate_configs_rejects_non_positive_n(client, n):
    r = client.post("/api/configs/generate", json={
        "repo_id": "org/model", "server_id": "vllm", "n": n, "vram_gb": 24.0,
        "readme_flags": {"--max-model-len": "8192"},
    })
    assert r.status_code == 422


def test_run_failure_marks_run_failed(client, monkeypatch):
    async def fake_create(*a, **k):
        raise FileNotFoundError("no bench binary")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    cfg = {
        "server_id": "llama.cpp",
        "flags": {"-c": "4096"},
        "model_id": None,
        "serving_command": "llama-server -m x",
        "bench_command": ["llama-bench", "-m", "x"],
    }
    r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg]})
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    def status():
        runs = {x["id"]: x for x in client.get("/api/benchmarks").json()["runs"]}
        return runs[run_id]["status"]

    _poll(lambda: status() != "running")
    assert status() == "failed"

    r2 = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg]})
    assert r2.status_code == 200


def test_full_run_completes_and_persists(client, monkeypatch):
    async def fake_create(*a, **k):
        return FakeProcess(FAKE_BENCH.encode())

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    cfg = {
        "server_id": "llama.cpp",
        "flags": {"-c": "4096"},
        "model_id": "org/model",
        "serving_command": "llama-server -m x",
        "bench_command": ["llama-bench", "-m", "x"],
    }
    r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg]})
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    def results():
        return client.get(f"/api/benchmarks/{run_id}").json()["results"]

    assert _poll(lambda: bool(results()))
    rows = results()
    assert len(rows) == 1
    assert rows[0]["result_status"] == "ok"
    assert rows[0]["prompt_processing_tps"] == 1000.0
    assert rows[0]["decode_tps"] == 80.0


def test_download_missing_fields_422(client):
    assert client.post("/api/models/download", json={}).status_code == 422
    assert client.post("/api/models/download", json={"repo_id": "org/model"}).status_code == 422
    assert client.post("/api/models/download",
                       json={"repo_id": "org/model", "server_id": "nope"}).status_code == 422


def test_download_cli_missing_400_with_manual_command(client, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    r = client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
    assert r.status_code == 400
    assert "hf download org/model" in r.json()["detail"]
