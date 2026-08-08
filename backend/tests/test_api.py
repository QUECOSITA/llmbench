import asyncio
import os
import signal
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


def _reader(data: bytes) -> asyncio.StreamReader:
    r = asyncio.StreamReader()
    if data:
        r.feed_data(data)
    r.feed_eof()
    return r


class FakeProcess:
    def __init__(self, out, err=b"", rc=0):
        self.stdout = _reader(out)
        self.stderr = _reader(err)
        self.returncode = rc
        self.killed = False

    async def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True


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
                        hf_cache_dir=tmp_path / "hf",
                        workload_file=tmp_path / "prompts.jsonl")
    (tmp_path / "prompts.jsonl").write_text("{\"prompt\": \"hi\"}\n")
    with TestClient(create_app(settings)) as c:
        yield c


def test_servers_endpoint(client):
    r = client.get("/api/servers")
    assert r.status_code == 200
    assert set(r.json()["readiness"]) == {"llama.cpp", "vllm", "sglang", "speed-bench"}


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


def test_analyze_direct_file_link_uses_single_file_size(client, httpx_mock):
    httpx_mock.add_response(
        url="https://huggingface.co/api/models/org/model/tree/main?recursive=true",
        json=[{"path": "README.md", "type": "file", "size": 100},
              {"path": "model.Q2_K.gguf", "type": "file", "size": 2_000_000_000},
              {"path": "model.Q4_K_M.gguf", "type": "file", "size": 4_000_000_000},
              {"path": "model.Q8_0.gguf", "type": "file", "size": 8_000_000_000}],
    )
    httpx_mock.add_response(url="https://huggingface.co/org/model/raw/main/README.md",
                            text="# M\n")
    r = client.post("/api/models/analyze",
                    json={"input": "https://huggingface.co/org/model/resolve/main/model.Q4_K_M.gguf"})
    assert r.status_code == 200
    body = r.json()
    assert body["weights_bytes"] == 4_000_000_000
    assert [g["path"] for g in body["gguf_files"]] == ["model.Q4_K_M.gguf"]
    assert body["fit_verdict"]["needed_gb"] < 8.0


def test_analyze_single_file_without_config_scales_fit_to_file(client, httpx_mock):
    """A small GGUF repo without config.json must not inherit the 7B-scale
    default's ~4 GB KV cache: a ~711 MB file should fit with < 2 GB needed."""
    httpx_mock.add_response(
        url="https://huggingface.co/api/models/org/model/tree/main?recursive=true",
        json=[{"path": "README.md", "type": "file", "size": 100},
              {"path": "model-F16.gguf", "type": "file", "size": 711_483_104},
              {"path": "model-Q4_K_M.gguf", "type": "file", "size": 229_310_176}],
    )
    httpx_mock.add_response(url="https://huggingface.co/org/model/raw/main/README.md",
                            text="# M\n")
    r = client.post("/api/models/analyze",
                    json={"input": "https://huggingface.co/org/model/resolve/main/model-F16.gguf"})
    assert r.status_code == 200
    body = r.json()
    assert body["weights_bytes"] == 711_483_104
    assert body["fit_verdict"]["needed_gb"] < 2.0


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
        assert cmd[cmd.index("-hfr") + 1] == "org/model"
        assert cmd[cmd.index("-hff") + 1] == "model.Q4_K_M.gguf"
        assert "--hf-repo org/model" in cfg["serving_command"]
        assert "--hf-file model.Q4_K_M.gguf" in cfg["serving_command"]
        assert "/tmp/models/model.Q4_K_M.gguf" not in cfg["serving_command"]


def _make_snapshot_gguf(settings, repo_id: str) -> str:
    root = settings.hf_cache_dir
    snap = root / f"models--{repo_id.replace('/', '--')}" / "snapshots" / "ref1"
    snap.mkdir(parents=True)
    gguf = snap / "model.Q4_K_M.gguf"
    gguf.write_bytes(b"dummy-gguf")
    return str(gguf)


def test_generate_configs_llama_resolves_local_gguf(client):
    from app.api import state
    gguf_path = _make_snapshot_gguf(state.settings, "org/model")
    r = client.post("/api/configs/generate", json={
        "repo_id": "org/model", "server_id": "llama.cpp", "n": 2,
        "readme_flags": {"--ctx-size": "4096"},
    })
    assert r.status_code == 200
    for cfg in r.json()["configs"]:
        assert cfg["bench_command"][cfg["bench_command"].index("-hfr") + 1] == "org/model"
        assert cfg["bench_command"][cfg["bench_command"].index("-hff") + 1] == "model.Q4_K_M.gguf"
        assert "--hf-repo org/model" in cfg["serving_command"]
        assert "--hf-file model.Q4_K_M.gguf" in cfg["serving_command"]
        assert gguf_path not in cfg["serving_command"]


def test_generate_configs_llama_falls_back_to_repo_id_when_no_gguf(client):
    r = client.post("/api/configs/generate", json={
        "repo_id": "org/model", "server_id": "llama.cpp", "n": 1,
        "readme_flags": {"--ctx-size": "4096"},
    })
    assert r.status_code == 200
    cfg = r.json()["configs"][0]
    assert cfg["bench_command"][cfg["bench_command"].index("-m") + 1] == "org/model"
    assert "--fit-ctx" in cfg["bench_command"]
    assert "--hf-file" not in cfg["serving_command"]


def test_start_run_rejects_duplicate(client, monkeypatch):
    release = asyncio.Event()

    class HangReader(asyncio.StreamReader):
        async def read(self, n=-1):
            await release.wait()
            return b""

    class HangProcess:
        returncode = 0
        killed = False

        def __init__(self):
            self.stdout = HangReader()
            self.stderr = _reader(b"")

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

    detail = client.get(f"/api/benchmarks/{run_id}").json()
    assert detail["status"] == "failed"
    assert detail["total"] == 1

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
    r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg], "pause": False})
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

    detail = client.get(f"/api/benchmarks/{run_id}").json()
    assert detail["status"] == "completed"
    assert detail["total"] == 1


def test_run_executes_rebuilt_bench_command_from_edited_serving_command(client, monkeypatch):
    captured = {}

    async def fake_create(*a, **k):
        captured["argv"] = list(a)
        return FakeProcess(FAKE_BENCH.encode())

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    cfg = {
        "server_id": "llama.cpp",
        "flags": {"--ctx-size": "4096"},
        "model_id": "org/model",
        "serving_command": "llama-server -m x --ctx-size 54000",
        "bench_command": ["llama-bench", "-m", "x", "--fit-ctx", "4096"],
    }
    r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg], "pause": False})
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    assert _poll(lambda: bool(client.get(f"/api/benchmarks/{run_id}").json()["results"]))
    assert "--fit-ctx" in captured["argv"]
    assert captured["argv"][captured["argv"].index("--fit-ctx") + 1] == "54000"
    assert "4096" not in captured["argv"]


def test_download_missing_fields_422(client):
    assert client.post("/api/models/download", json={}).status_code == 422
    assert client.post("/api/models/download", json={"repo_id": "org/model"}).status_code == 422
    assert client.post("/api/models/download",
                       json={"repo_id": "org/model", "server_id": "nope"}).status_code == 422


def test_download_cli_missing_400_with_manual_command(client, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    r = client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "HF CLI not found." in detail
    assert "hf download" in detail and "org/model" in detail
    assert "--format" in detail and "human" in detail


def test_open_pty_sets_a_terminal_window_size():
    """tqdm reads the pty's window size and suppresses its bars entirely when
    it is 0x0, so _open_pty must set a real size on the slave fd."""
    import app.api as api_mod

    master_fd, slave_fd = api_mod._open_pty()
    try:
        import fcntl
        import struct
        import termios

        packed = fcntl.ioctl(slave_fd, termios.TIOCGWINSZ, b"\x00" * 8)
        rows, cols = struct.unpack("HHHH", packed)[:2]
        assert rows > 0, "pty slave has zero terminal rows"
        assert cols > 0, "pty slave has zero terminal columns"
    finally:
        os.close(master_fd)
        os.close(slave_fd)


class FakeDownloadProc:
    """Stands in for an asyncio subprocess attached to a pty."""

    def __init__(self, rc=0):
        self._rc = rc
        self.returncode = None
        self.signals = []
        self.killed = False

    async def wait(self):
        self.returncode = self._rc
        return self._rc

    def send_signal(self, sig):
        self.signals.append(sig)

    def kill(self):
        self.killed = True
        self.returncode = -9


class FakeStdin:
    def __init__(self, answered):
        self.written = []
        self._answered = answered

    def write(self, data):
        self.written.append(data)
        self._answered.set()
        return len(data)

    async def drain(self):
        pass


class FakePruneProcess:
    """Simulates `hf cache prune --format human` writing the summary, then
    blocking on stdin at `Proceed? [y/N]: ` until an answer is written."""

    def __init__(self, first="About to delete 1 incomplete download(s) (8.0 total).\nProceed? [y/N]: ",
                 after="\n✓ Deleted 1 incomplete download(s); freed 8.0.\n", rc=0):
        self._first = first
        self._after = after
        self._rc = rc
        self.returncode = None
        self.answered = asyncio.Event()
        self.stdin = FakeStdin(self.answered)
        self._phase = 0

    @property
    def stdout(self):
        return self

    async def read(self, n=1024):
        if self._phase == 0:
            self._phase = 1
            return self._first.encode()
        if self._phase == 1:
            if "Proceed?" in self._first:
                await self.answered.wait()
            self._phase = 2
            return self._after.encode()
        return b""

    async def wait(self):
        self.returncode = self._rc
        return self._rc


def test_download_vllm_success_upserts_downloaded(client, tmp_path, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_stream(master_fd):
        yield ("line", "Fetching files...")
        yield ("line", "Done")

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("app.api._open_pty", lambda: (111, 112))
    async def fake_spawn(*a, **k):
        return FakeDownloadProc()
    monkeypatch.setattr("app.api._spawn_pty", fake_spawn)
    monkeypatch.setattr("app.api._stream_download_output", fake_stream)

    snapshot = tmp_path / "hf" / "models--org--model"
    snapshot.mkdir(parents=True)

    r = client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
    assert r.status_code == 200 and r.json()["ok"] is True

    def row():
        m = api_mod.db_mod.get_model(api_mod.state.conn, "org/model", "vllm")
        return m and m["status"]

    assert _poll(lambda: row() == "downloaded")
    assert events[0]["type"] == "download_started"
    assert "hf download" in events[0]["command"]
    assert "--format" in events[0]["command"] and "human" in events[0]["command"]
    assert any(e["type"] == "download_log" and e["line"] == "Fetching files..." for e in events)
    assert _poll(lambda: any(e["type"] == "download_done" for e in events))
    done = next(e for e in events if e["type"] == "download_done")
    assert done["local_path"] == str(snapshot)
    assert api_mod.state._download_active is False


def test_download_llama_resolves_gguf_file(client, tmp_path, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_stream(master_fd):
        yield ("line", "ok")

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("app.api._open_pty", lambda: (111, 112))
    async def fake_spawn(*a, **k):
        return FakeDownloadProc()
    monkeypatch.setattr("app.api._spawn_pty", fake_spawn)
    monkeypatch.setattr("app.api._stream_download_output", fake_stream)

    gguf = tmp_path / "gguf" / "model.Q4_K_M.gguf"
    gguf.parent.mkdir(parents=True)
    gguf.write_bytes(b"x" * 2048)

    r = client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "llama.cpp"})
    assert r.status_code == 200

    def row():
        return api_mod.db_mod.get_model(api_mod.state.conn, "org/model", "llama.cpp")

    assert _poll(lambda: (row() or {}).get("status") == "downloaded")
    row = row()
    assert row["local_path"] == str(gguf)
    assert row["gguf_filename"] == "model.Q4_K_M.gguf"
    assert row["size_bytes"] == 2048
    start = next(e for e in events if e["type"] == "download_started")
    assert "--include" in start["command"] and "*.gguf" in start["command"]



def test_download_rejects_duplicate(client, monkeypatch):
    import app.api as api_mod
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    api_mod.state._download_active = True
    try:
        r = client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
        assert r.status_code == 409
    finally:
        api_mod.state._download_active = False


def test_download_command_llama_uses_specific_gguf_when_given():
    from app.api import _download_command, _prune_command
    assert _download_command("org/model", "llama.cpp", gguf_filename="model.Q4_K_M.gguf") == [
        "hf", "download", "--format", "human", "org/model", "--include", "model.Q4_K_M.gguf",
    ]
    assert _download_command("org/model", "llama.cpp") == [
        "hf", "download", "--format", "human", "org/model", "--include", "*.gguf",
    ]
    assert _download_command("org/model", "vllm") == [
        "hf", "download", "--format", "human", "org/model",
    ]
    assert _download_command("org/model", "vllm", cache_dir="/tmp/hf") == [
        "hf", "download", "--format", "human", "org/model", "--cache-dir", "/tmp/hf",
    ]
    assert _prune_command() == ["hf", "cache", "prune", "--format", "human"]
    assert _prune_command(cache_dir="/tmp/hf") == [
        "hf", "cache", "prune", "--format", "human", "--cache-dir", "/tmp/hf",
    ]


def test_download_llama_with_gguf_filename_uses_exact_file(client, tmp_path, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_stream(master_fd):
        yield ("line", "ok")

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("app.api._open_pty", lambda: (111, 112))
    async def fake_spawn(*a, **k):
        return FakeDownloadProc()
    monkeypatch.setattr("app.api._spawn_pty", fake_spawn)
    monkeypatch.setattr("app.api._stream_download_output", fake_stream)

    gguf = tmp_path / "gguf" / "model.Q4_K_M.gguf"
    gguf.parent.mkdir(parents=True)
    gguf.write_bytes(b"x" * 2048)

    r = client.post("/api/models/download", json={
        "repo_id": "org/model", "server_id": "llama.cpp",
        "gguf_filename": "model.Q4_K_M.gguf",
    })
    assert r.status_code == 200

    def row():
        return api_mod.db_mod.get_model(api_mod.state.conn, "org/model", "llama.cpp")

    assert _poll(lambda: (row() or {}).get("status") == "downloaded")
    row = row()
    assert row["local_path"] == str(gguf)
    start = next(e for e in events if e["type"] == "download_started")
    assert "model.Q4_K_M.gguf" in start["command"]
    assert "*.gguf" not in start["command"]


def test_cancel_409_when_no_download(client):
    r = client.post("/api/models/download/cancel")
    assert r.status_code == 409


def test_cancel_sends_sigint_to_active_proc(client, monkeypatch):
    import app.api as api_mod
    proc = FakeDownloadProc()
    api_mod.state._download_proc = proc
    api_mod.state._download_active = True
    try:
        r = client.post("/api/models/download/cancel")
        assert r.status_code == 200 and r.json()["ok"] is True
        assert api_mod.state._download_cancelled is True
        assert proc.signals == [signal.SIGINT]
    finally:
        api_mod.state._download_active = False
        api_mod.state._download_cancelled = False
        api_mod.state._download_proc = None


def test_analyze_fetches_model_arch(client, httpx_mock):
    httpx_mock.add_response(
        url="https://huggingface.co/api/models/org/model/tree/main",
        json=[{"path": "README.md", "type": "file", "size": 100},
              {"path": "config.json", "type": "file", "size": 50},
              {"path": "model.safetensors", "type": "file", "size": 4000000000}],
    )
    httpx_mock.add_response(url="https://huggingface.co/org/model/raw/main/README.md",
                            text="# M\n")
    httpx_mock.add_response(url="https://huggingface.co/org/model/raw/main/config.json",
                            json={"num_hidden_layers": 40, "num_attention_heads": 64,
                                  "hidden_size": 8192, "max_position_embeddings": 32768})
    r = client.post("/api/models/analyze", json={"input": "org/model"})
    assert r.status_code == 200
    assert r.json()["model_arch"] == {
        "layers": 40, "heads": 64, "hidden": 8192, "max_ctx": 32768}


def test_models_endpoint_reconciles_hf_cache(client, tmp_path):
    from app.config import Settings
    from app.sync import snapshot_dir_for
    settings = Settings(data_dir=tmp_path, gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf", workload_file=tmp_path / "prompts.jsonl")
    snap = snapshot_dir_for(settings, "org/model") / "snapshots" / "main"
    snap.mkdir(parents=True)
    (snap / "model.safetensors").write_bytes(b"x")

    r = client.get("/api/models")
    assert r.status_code == 200
    models = {m["server_id"]: m for m in r.json()["models"]}
    for sid in ("vllm", "sglang"):
        assert models[sid]["repo_id"] == "org/model"
        assert models[sid]["status"] == "downloaded"


def test_delete_model_removes_row_and_files(client, tmp_path, monkeypatch):
    from app.config import Settings
    from app.sync import snapshot_dir_for
    settings = Settings(data_dir=tmp_path, gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf", workload_file=tmp_path / "prompts.jsonl")
    snap = snapshot_dir_for(settings, "org/model")
    (snap / "snapshots" / "main").mkdir(parents=True)
    (snap / "snapshots" / "main" / "model.safetensors").write_bytes(b"x")
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)

    assert client.get("/api/models").status_code == 200
    assert snap.exists()

    r = client.delete("/api/models/org%2Fmodel")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert client.get("/api/models").json()["models"] == []
    assert not snap.exists()


def test_delete_model_invokes_hf_cache_rm(client, tmp_path, monkeypatch):
    from app.config import Settings
    from app.sync import snapshot_dir_for
    settings = Settings(data_dir=tmp_path, gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf", workload_file=tmp_path / "prompts.jsonl")
    snap = snapshot_dir_for(settings, "org/model")
    (snap / "snapshots" / "main").mkdir(parents=True)
    (snap / "snapshots" / "main" / "model.safetensors").write_bytes(b"x")

    captured: dict = {}
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")

    class FakeProc:
        returncode = None

        async def communicate(self):
            self.returncode = 0
            return b"", None

    async def fake_create(*cmd, **kw):
        captured["cmd"] = list(cmd)
        return FakeProc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    assert client.get("/api/models").status_code == 200

    r = client.delete("/api/models/org%2Fmodel")
    assert r.status_code == 200
    assert captured["cmd"] == [
        "hf", "cache", "rm", "hf://models/org/model", "-y",
        "--cache-dir", str(settings.hf_cache_dir),
    ]


def test_delete_model_hf_cache_rm_failure_returns_500(client, tmp_path, monkeypatch):
    from app.config import Settings
    from app.sync import snapshot_dir_for
    settings = Settings(data_dir=tmp_path, gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf", workload_file=tmp_path / "prompts.jsonl")
    snap = snapshot_dir_for(settings, "org/model")
    (snap / "snapshots" / "main").mkdir(parents=True)
    (snap / "snapshots" / "main" / "model.safetensors").write_bytes(b"x")

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")

    class FakeProc:
        returncode = None

        async def communicate(self):
            self.returncode = 1
            return b"repo not found", None

    async def fake_create(*cmd, **kw):
        return FakeProc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    assert client.get("/api/models").status_code == 200

    r = client.delete("/api/models/org%2Fmodel")
    assert r.status_code == 500
    assert "repo not found" in r.json()["detail"]


def test_generate_configs_includes_per_config_fit(client):
    r = client.post("/api/configs/generate", json={
        "repo_id": "org/model", "server_id": "vllm", "n": 2, "vram_gb": 24.0,
        "weights_bytes": 10_000_000_000, "ram_gb": 64.0,
        "model_arch": {"layers": 32, "heads": 32, "hidden": 4096, "max_ctx": 8192},
        "readme_flags": {},
    })
    assert r.status_code == 200
    for cfg in r.json()["configs"]:
        fit = cfg["fit"]
        assert fit["stage"] in ("gpu", "no_fit")
        assert fit["fits_vram"] in (True, False)
        assert fit["label"] in ("FITS VRAM", "NO FIT")
        assert "needed_gb" in fit and "kv_gb" in fit


def test_generate_configs_fit_is_none_without_weights(client):
    r = client.post("/api/configs/generate", json={
        "repo_id": "org/model", "server_id": "vllm", "n": 2, "vram_gb": 24.0,
        "readme_flags": {},
    })
    assert r.status_code == 200
    for cfg in r.json()["configs"]:
        assert cfg["fit"] is None


def test_cancel_then_prune_prompt_y(client, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_stream(master_fd):
        yield ("line", "Fetching files...")
        while not api_mod.state._download_cancelled:
            await asyncio.sleep(0.01)
        yield ("line", "Done")

    async def fake_spawn(*a, **k):
        return FakeDownloadProc()

    async def fake_create(*a, **k):
        return FakePruneProcess()

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("app.api._open_pty", lambda: (111, 112))
    monkeypatch.setattr("app.api._spawn_pty", fake_spawn)
    monkeypatch.setattr("app.api._stream_download_output", fake_stream)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    r = client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
    assert r.status_code == 200
    assert _poll(lambda: any(e["type"] == "download_started" for e in events))
    assert _poll(lambda: api_mod.state._download_proc is not None)

    r = client.post("/api/models/download/cancel")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert api_mod.state._download_cancelled is True

    assert _poll(lambda: any(e["type"] == "prune_started" for e in events))
    assert _poll(lambda: any(e["type"] == "prune_prompt" for e in events))

    r = client.post("/api/models/download/prune-answer", json={"answer": "y"})
    assert r.status_code == 200 and r.json()["ok"] is True

    assert _poll(lambda: any(e["type"] == "prune_done" for e in events))
    done = next(e for e in events if e["type"] == "prune_done")
    assert done["accepted"] is True
    assert any(e["type"] == "prune_log" and "About to delete" in e["line"] for e in events)
    assert api_mod.state._download_active is False


def test_cancel_then_prune_prompt_n(client, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_stream(master_fd):
        yield ("line", "Fetching files...")
        while not api_mod.state._download_cancelled:
            await asyncio.sleep(0.01)
        yield ("line", "Done")

    async def fake_spawn(*a, **k):
        return FakeDownloadProc()

    async def fake_create(*a, **k):
        return FakePruneProcess(after="\nAborted!\n", rc=1)

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("app.api._open_pty", lambda: (111, 112))
    monkeypatch.setattr("app.api._spawn_pty", fake_spawn)
    monkeypatch.setattr("app.api._stream_download_output", fake_stream)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
    assert _poll(lambda: any(e["type"] == "download_started" for e in events))
    client.post("/api/models/download/cancel")

    assert _poll(lambda: any(e["type"] == "prune_prompt" for e in events))
    client.post("/api/models/download/prune-answer", json={"answer": "n"})
    assert _poll(lambda: any(e["type"] == "prune_done" for e in events))
    done = next(e for e in events if e["type"] == "prune_done")
    assert done["accepted"] is False


def test_cancel_then_prune_nothing_to_prune(client, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_stream(master_fd):
        yield ("line", "Fetching files...")
        while not api_mod.state._download_cancelled:
            await asyncio.sleep(0.01)
        yield ("line", "Done")

    async def fake_spawn(*a, **k):
        return FakeDownloadProc()

    async def fake_create(*a, **k):
        return FakePruneProcess(
            first="No unreferenced revisions or incomplete downloads found. Nothing to prune.\n",
            after="", rc=0,
        )

    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/hf")
    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("app.api._open_pty", lambda: (111, 112))
    monkeypatch.setattr("app.api._spawn_pty", fake_spawn)
    monkeypatch.setattr("app.api._stream_download_output", fake_stream)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    client.post("/api/models/download", json={"repo_id": "org/model", "server_id": "vllm"})
    assert _poll(lambda: any(e["type"] == "download_started" for e in events))
    client.post("/api/models/download/cancel")

    assert _poll(lambda: any(e["type"] == "prune_done" for e in events))
    assert not any(e["type"] == "prune_prompt" for e in events)
    done = next(e for e in events if e["type"] == "prune_done")
    assert done["accepted"] is True


def test_prune_answer_validation(client):
    import app.api as api_mod
    api_mod.state._download_active = True
    try:
        r = client.post("/api/models/download/prune-answer", json={"answer": "maybe"})
        assert r.status_code == 422
        r = client.post("/api/models/download/prune-answer", json={})
        assert r.status_code == 422
        r = client.post("/api/models/download/prune-answer", json={"answer": "y"})
        assert r.status_code == 409
    finally:
        api_mod.state._download_active = False


def test_pause_run_streams_and_waits_for_continue(client, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_create(*a, **k):
        return FakeProcess(FAKE_BENCH.encode(), err=b"progress noise\n")

    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    class FakeWs:
        pass

    ws = FakeWs()
    api_mod.state._ws_clients.add(ws)
    try:
        cfg = {
            "server_id": "llama.cpp",
            "flags": {"-c": "4096"},
            "model_id": "org/model",
            "serving_command": "llama-server -m x",
            "bench_command": ["llama-bench", "-m", "x"],
        }
        r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg], "pause": True})
        assert r.status_code == 200
        run_id = r.json()["run_id"]

        assert _poll(lambda: any(e["type"] == "config_wait" for e in events))
        assert any(e["type"] == "bench_log" and e["kind"] == "line" for e in events)
        assert api_mod.db_mod.get_run_status(api_mod.state.conn, run_id) == "running"

        r2 = client.post("/api/benchmarks/continue", json={"run_id": run_id})
        assert r2.status_code == 200

        assert _poll(lambda: api_mod.db_mod.get_run_status(api_mod.state.conn, run_id) == "completed")
        assert any(e["type"] == "config_wait" for e in events)
        assert api_mod.state._continue_queue is None
    finally:
        api_mod.state._ws_clients.discard(ws)


def test_pause_false_runs_straight_through(client, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_create(*a, **k):
        return FakeProcess(FAKE_BENCH.encode())

    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    cfg = {
        "server_id": "llama.cpp",
        "flags": {"-c": "4096"},
        "model_id": "org/model",
        "serving_command": "llama-server -m x",
        "bench_command": ["llama-bench", "-m", "x"],
    }
    r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg], "pause": False})
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    assert _poll(lambda: api_mod.db_mod.get_run_status(api_mod.state.conn, run_id) == "completed")
    assert not any(e["type"] == "config_wait" for e in events)
    assert any(e["type"] == "bench_log" for e in events)


def test_pause_run_auto_advances_when_no_clients(client, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_create(*a, **k):
        return FakeProcess(FAKE_BENCH.encode())

    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    monkeypatch.setattr("app.api.AUTO_ADVANCE_GRACE_S", 0.1)

    cfg = {
        "server_id": "llama.cpp",
        "flags": {"-c": "4096"},
        "model_id": "org/model",
        "serving_command": "llama-server -m x",
        "bench_command": ["llama-bench", "-m", "x"],
    }
    r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg], "pause": True})
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    assert _poll(lambda: api_mod.db_mod.get_run_status(api_mod.state.conn, run_id) == "completed")
    assert any(e["type"] == "config_wait" for e in events)


def test_continue_with_no_pending_run_409(client):
    r = client.post("/api/benchmarks/continue", json={"run_id": 1})
    assert r.status_code == 409


def test_double_continue_does_not_skip_next_wait(client, monkeypatch):
    import app.api as api_mod
    events = []

    async def fake_broadcast(s, event):
        events.append(event)

    async def fake_create(*a, **k):
        return FakeProcess(FAKE_BENCH.encode())

    monkeypatch.setattr("app.api.broadcast", fake_broadcast)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    class FakeWs:
        pass

    ws = FakeWs()
    api_mod.state._ws_clients.add(ws)
    try:
        cfg = {
            "server_id": "llama.cpp",
            "flags": {"-c": "4096"},
            "model_id": "org/model",
            "serving_command": "llama-server -m x",
            "bench_command": ["llama-bench", "-m", "x"],
        }
        r = client.post("/api/benchmarks", json={"repo_id": "org/model", "configs": [cfg, cfg], "pause": True})
        assert r.status_code == 200
        run_id = r.json()["run_id"]

        assert _poll(lambda: any(e["type"] == "config_wait" for e in events))
        client.post("/api/benchmarks/continue", json={"run_id": run_id})
        client.post("/api/benchmarks/continue", json={"run_id": run_id})

        assert _poll(lambda: len([e for e in events if e["type"] == "config_wait"]) >= 2)
        time.sleep(0.5)
        assert api_mod.db_mod.get_run_status(api_mod.state.conn, run_id) == "running"

        r2 = client.post("/api/benchmarks/continue", json={"run_id": run_id})
        assert r2.status_code == 200
        assert _poll(lambda: api_mod.db_mod.get_run_status(api_mod.state.conn, run_id) == "completed")
    finally:
        api_mod.state._ws_clients.discard(ws)


import sys


def test_generate_configs_llama_spec_readme_uses_speed_bench(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.speed_bench_deps_available", lambda: True)
    bin_dir = tmp_path / "llama" / "build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    (bin_dir / "llama-bench").write_text("#!/bin/sh\n")
    script = tmp_path / "llama" / "tools" / "server" / "bench" / "speed-bench" / "speed_bench.py"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env python3\n")
    settings = Settings(data_dir=tmp_path / "data", gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf",
                        workload_file=tmp_path / "prompts.jsonl",
                        llama_cpp_bin_dir=bin_dir)
    (tmp_path / "prompts.jsonl").write_text("{\"prompt\": \"hi\"}\n")
    with TestClient(create_app(settings)) as c:
        r = c.post("/api/configs/generate", json={
            "server_id": "llama.cpp",
            "repo_id": "org/Qwen3-MTP",
            "n": 1,
            "readme_flags": {"--spec-type": "draft-mtp"},
        })
    assert r.status_code == 200
    cfg = r.json()["configs"][0]
    assert cfg["bench_tool"] == "speed-bench"
    assert cfg["bench_flags"] == "--bench throughput_1k --category all --limit 1 --osl 128"
    cmd = cfg["bench_command"]
    assert cmd[0] == sys.executable
    assert cmd[1] == str(script)
    assert cmd[cmd.index("--limit") + 1] == "1"
    assert cmd[cmd.index("--category") + 1] == "all"
    assert cmd[cmd.index("--bench") + 1] == "throughput_1k"
    assert cmd[cmd.index("--osl") + 1] == "128"
    assert "draft-mtp" in cfg["serving_command"]


def test_generate_speed_bench_uses_configured_osl(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.speed_bench_deps_available", lambda: True)
    bin_dir = tmp_path / "llama" / "build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    script = tmp_path / "llama" / "tools" / "server" / "bench" / "speed-bench" / "speed_bench.py"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env python3\n")
    settings = Settings(data_dir=tmp_path / "data", gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf",
                        workload_file=tmp_path / "prompts.jsonl",
                        llama_cpp_bin_dir=bin_dir, speed_bench_osl=256)
    (tmp_path / "prompts.jsonl").write_text("{\"prompt\": \"hi\"}\n")
    with TestClient(create_app(settings)) as c:
        r = c.post("/api/configs/generate", json={
            "server_id": "llama.cpp",
            "repo_id": "org/Qwen3-MTP",
            "n": 1,
            "readme_flags": {"--spec-type": "draft-mtp"},
        })
    assert r.status_code == 200
    cfg = r.json()["configs"][0]
    assert cfg["bench_flags"] == "--bench throughput_1k --category all --limit 1 --osl 256"
    assert cfg["bench_command"][cfg["bench_command"].index("--osl") + 1] == "256"


def test_generate_configs_llama_non_spec_uses_llama_bench(client):
    r = client.post("/api/configs/generate", json={
        "server_id": "llama.cpp",
        "repo_id": "org/plain-model",
        "n": 1,
        "readme_flags": {},
    })
    assert r.status_code == 200
    cfg = r.json()["configs"][0]
    assert cfg["bench_tool"] == "llama-bench"
    assert cfg["bench_command"][0] == "llama-bench"


def test_rebuild_bench_command_speed_bench(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.speed_bench_deps_available", lambda: True)
    from app.api import _rebuild_bench_command, AppState
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    script = tmp_path / "speed_bench.py"
    script.write_text("x")
    settings = Settings(data_dir=tmp_path / "data", gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf",
                        workload_file=tmp_path / "prompts.jsonl",
                        llama_cpp_bin_dir=bin_dir, speed_bench_script=script)
    (tmp_path / "prompts.jsonl").write_text("x\n")
    s = AppState(settings)
    cfg = {
        "server_id": "llama.cpp",
        "bench_tool": "speed-bench",
        "serving_command": "llama-server -m /models/x.gguf --spec-type draft-mtp --port 9999 --host 0.0.0.0",
        "flags": {},
        "bench_flags": "--bench qualitative --category coding --limit 2 --concurrency 4",
        "bench_command": [],
    }
    _rebuild_bench_command(s, cfg, "org/model")
    assert cfg["server_command"][0] == str(bin_dir / "llama-server")
    assert "--port" not in cfg["server_command"]
    assert "--host" not in cfg["server_command"]
    assert "--spec-type" in cfg["server_command"]
    assert cfg["bench_command"][0] == sys.executable
    assert cfg["bench_command"][1] == str(script)
    assert cfg["bench_command"][cfg["bench_command"].index("--bench") + 1] == "qualitative"
    assert cfg["bench_command"][cfg["bench_command"].index("--category") + 1] == "coding"
    assert cfg["bench_command"][cfg["bench_command"].index("--concurrency") + 1] == "4"
    assert "bench_error" not in cfg


def test_rebuild_bench_command_speed_bench_invalid_flags(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.speed_bench_deps_available", lambda: True)
    from app.api import _rebuild_bench_command, AppState
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    script = tmp_path / "speed_bench.py"
    script.write_text("x")
    settings = Settings(data_dir=tmp_path / "data", gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf",
                        workload_file=tmp_path / "prompts.jsonl",
                        llama_cpp_bin_dir=bin_dir, speed_bench_script=script)
    (tmp_path / "prompts.jsonl").write_text("x\n")
    s = AppState(settings)
    cfg = {
        "server_id": "llama.cpp",
        "bench_tool": "speed-bench",
        "serving_command": "llama-server -m /models/x.gguf --spec-type draft-mtp",
        "flags": {},
        "bench_flags": "--bench foo",
        "bench_command": [],
    }
    _rebuild_bench_command(s, cfg, "org/model")
    assert cfg["bench_command"] == []
    assert "unknown --bench 'foo'" in cfg["bench_error"]


def test_rebuild_bench_command_speed_bench_missing_flags_uses_default(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.speed_bench_deps_available", lambda: True)
    from app.api import _rebuild_bench_command, AppState
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    script = tmp_path / "speed_bench.py"
    script.write_text("x")
    settings = Settings(data_dir=tmp_path / "data", gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf",
                        workload_file=tmp_path / "prompts.jsonl",
                        llama_cpp_bin_dir=bin_dir, speed_bench_script=script)
    (tmp_path / "prompts.jsonl").write_text("x\n")
    s = AppState(settings)
    cfg = {
        "server_id": "llama.cpp",
        "bench_tool": "speed-bench",
        "serving_command": "llama-server -m /models/x.gguf --spec-type draft-mtp",
        "flags": {},
        "bench_command": [],
    }
    _rebuild_bench_command(s, cfg, "org/model")
    assert cfg["bench_command"][cfg["bench_command"].index("--bench") + 1] == "throughput_1k"
    assert "bench_error" not in cfg


def test_start_run_speed_bench_invalid_flags_rejected(client, monkeypatch):
    monkeypatch.setattr("app.api.speed_bench_deps_available", lambda: True)
    monkeypatch.setattr("app.api.resolve_speed_bench_script", lambda *a, **k: "/tmp/speed_bench.py")
    config = {
        "server_id": "llama.cpp",
        "bench_tool": "speed-bench",
        "serving_command": "llama-server -m /models/x.gguf --spec-type draft-mtp",
        "flags": {},
        "bench_flags": "--bench foo",
        "bench_command": [],
    }
    r = client.post("/api/benchmarks", json={
        "repo_id": "org/model",
        "configs": [config],
        "pause": False,
    })
    assert r.status_code == 422
    assert "unknown --bench 'foo'" in r.json()["detail"]


def test_start_run_speed_bench_unavailable_rejected(client, monkeypatch):
    monkeypatch.setattr("app.api.resolve_speed_bench_script", lambda *a, **k: None)
    config = {
        "server_id": "llama.cpp",
        "bench_tool": "speed-bench",
        "serving_command": "llama-server -m /models/x.gguf --spec-type draft-mtp",
        "flags": {},
        "bench_command": [],
    }
    r = client.post("/api/benchmarks", json={
        "repo_id": "org/model",
        "configs": [config],
        "pause": False,
    })
    assert r.status_code == 422
    assert "speed-bench" in r.json()["detail"]


def test_generate_speed_bench_missing_deps_sets_bench_error(tmp_path, monkeypatch):
    bin_dir = tmp_path / "llama" / "build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    script = tmp_path / "llama" / "tools" / "server" / "bench" / "speed-bench" / "speed_bench.py"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env python3\n")
    settings = Settings(data_dir=tmp_path / "data", gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf",
                        workload_file=tmp_path / "prompts.jsonl",
                        llama_cpp_bin_dir=bin_dir)
    (tmp_path / "prompts.jsonl").write_text("{\"prompt\": \"hi\"}\n")
    monkeypatch.setattr("app.api.resolve_speed_bench_script", lambda *a, **k: str(script))
    monkeypatch.setattr("app.api.speed_bench_deps_available", lambda: False)
    with TestClient(create_app(settings)) as c:
        r = c.post("/api/configs/generate", json={
            "server_id": "llama.cpp",
            "repo_id": "org/Qwen3-MTP",
            "n": 1,
            "readme_flags": {"--spec-type": "draft-mtp"},
        })
    assert r.status_code == 200
    cfg = r.json()["configs"][0]
    assert cfg["bench_tool"] == "speed-bench"
    assert cfg["bench_command"] == []
    assert "speed-bench" in cfg["bench_error"]
    assert "speed-bench" in cfg["bench_error"].lower() or "speed-bench" in cfg["bench_error"]


def test_start_run_speed_bench_missing_deps_rejected(client, monkeypatch):
    monkeypatch.setattr("app.api.resolve_speed_bench_script", lambda *a, **k: "/tmp/speed_bench.py")
    monkeypatch.setattr("app.api.speed_bench_deps_available", lambda: False)
    config = {
        "server_id": "llama.cpp",
        "bench_tool": "speed-bench",
        "serving_command": "llama-server -m /models/x.gguf --spec-type draft-mtp",
        "flags": {},
        "bench_command": [],
    }
    r = client.post("/api/benchmarks", json={
        "repo_id": "org/model",
        "configs": [config],
        "pause": False,
    })
    assert r.status_code == 422
    assert "speed-bench" in r.json()["detail"]
