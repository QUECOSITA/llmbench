import app.agentic as agentic_mod

from app.benchmark import parse_llama_bench_csv

LLAMA_CSV = """\
model,size,params,backend,test,t,n_threads,batch,ngl,ms,t/s
org/model,Q4_K_M,7.2B,CUDA,pp,0,8,512,999,42.0,1234.5
org/model,Q4_K_M,7.2B,CUDA,tg,0,8,512,999,820.0,86.4
"""


def test_parse_llama_bench_csv():
    r = parse_llama_bench_csv(LLAMA_CSV)
    assert r["prompt_processing_tps"] == 1234.5
    assert r["decode_tps"] == 86.4


def test_parse_llama_bench_csv_schema_drift():
    csv_text = "build_commit,build_number,cpu_info,t,ms\nabc123,42,cpu,0,100.0\n"
    r = parse_llama_bench_csv(csv_text)
    assert r["prompt_processing_tps"] is None
    assert r["decode_tps"] is None


LLAMA_CSV_V9992 = """\
build_commit,build_number,cpu_info,gpu_info,backends,model_filename,model_type,model_size,model_n_params,n_batch,n_ubatch,n_threads,cpu_mask,cpu_strict,poll,type_k,type_v,n_gpu_layers,n_cpu_moe,split_mode,main_gpu,no_kv_offload,flash_attn,devices,tensor_split,tensor_buft_overrides,use_mmap,use_direct_io,embeddings,no_op_offload,no_host,fit_target,fit_min_ctx,n_prompt,n_gen,n_depth,test_time,avg_ns,stddev_ns,avg_ts,stddev_ts
"6eddde06a","9992","cpu","gpu","CUDA","x.gguf","q4","216","354","512","512","16","0x0","0","50","f16","f16","999","0","layer","0","0","-1","auto","0","none","1","0","0","0","0","0","0","64","0","0","2026-08-04T00:00:00Z","7374707","0","8678.31","0"
"6eddde06a","9992","cpu","gpu","CUDA","x.gguf","q4","216","354","512","512","16","0x0","0","50","f16","f16","999","0","layer","0","0","-1","auto","0","none","1","0","0","0","0","0","0","0","32","0","2026-08-04T00:00:00Z","33876041","0","944.62","0"
"""


def test_parse_llama_bench_csv_v9992():
    r = parse_llama_bench_csv(LLAMA_CSV_V9992)
    assert r["prompt_processing_tps"] == 8678.31
    assert r["decode_tps"] == 944.62


import asyncio

from app.benchmark import BenchmarkRunner
from app.tty_stream import TtyStream

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


class FakeProc:
    def __init__(self, out: bytes, err: bytes = b"", rc: int = 0):
        self.stdout = _reader(out)
        self.stderr = _reader(err)
        self.returncode = rc
        self.killed = False

    async def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class HangReader(asyncio.StreamReader):
    async def read(self, n=-1):
        await asyncio.sleep(3600)
        return b""


class HangProc(FakeProc):
    def __init__(self):
        self.stdout = HangReader()
        self.stderr = _reader(b"")
        self.returncode = 0
        self.killed = False


async def test_runner_streams_output_and_returns_full_output(monkeypatch):
    seen = []

    async def fake_create(*a, **k):
        return FakeProc(FAKE_BENCH.encode(), err=b"warning: loading model\n")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="llama.cpp", bench_command=["llama-bench", "-m", "x"],
                             timeout_s=60)

    async def on_output(kind, text):
        seen.append((kind, text))

    result = await runner.run(on_output=on_output)
    assert result["status"] == "ok"
    assert result["decode_tps"] == 80.0
    assert result["prompt_processing_tps"] == 1000.0
    assert ("line", "warning: loading model") in seen
    assert "warning: loading model" in result["output"]
    assert FAKE_BENCH in result["output"]


async def test_runner_emits_progress_for_carriage_returns(monkeypatch):
    seen = []

    async def fake_create(*a, **k):
        return FakeProc(FAKE_BENCH.encode(),
                        err=b"Processing: 0%\rProcessing: 50%\rProcessing: 100%\r\n")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="llama.cpp", bench_command=["llama-bench", "-m", "x"],
                             timeout_s=60)

    async def on_output(kind, text):
        seen.append((kind, text))

    result = await runner.run(on_output=on_output)
    assert result["status"] == "ok"
    assert any(kind == "progress" for kind, _ in seen)


async def test_runner_merges_stderr_only_for_output_not_parse(monkeypatch):
    async def fake_create(*a, **k):
        return FakeProc(b"bunch of non-json text", err=b"stderr noise")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="llama.cpp", bench_command=["bench"], timeout_s=60)
    result = await runner.run()
    assert result["status"] == "failed"
    assert "stderr noise" in result["output"]


async def test_runner_timeout_kills(monkeypatch):
    async def fake_create(*a, **k):
        return HangProc()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="llama.cpp", bench_command=["llama-bench"],
                             timeout_s=0.05)
    result = await runner.run()
    assert result["status"] == "failed"


async def test_runner_abort(monkeypatch):
    async def fake_create(*a, **k):
        return FakeProc(b"")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="llama.cpp", bench_command=["llama-bench"],
                             timeout_s=60)
    runner.abort()
    result = await runner.run()
    assert result["status"] == "aborted"


async def test_runner_abort_mid_run_kills_proc(monkeypatch):
    captured = {}
    killed_evt = asyncio.Event()

    class MidReader(asyncio.StreamReader):
        def __init__(self):
            super().__init__()
            self.fed = False

        async def read(self, n=-1):
            if not self.fed:
                self.fed = True
                return b"partial stdout\n"
            await killed_evt.wait()
            return b""

    class MidProc(FakeProc):
        def __init__(self):
            self.stdout = MidReader()
            self.stderr = _reader(b"")
            self.returncode = 0

        async def wait(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9
            killed_evt.set()

    async def fake_create(*a, **k):
        p = MidProc()
        captured["proc"] = p
        return p

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="llama.cpp", bench_command=["llama-bench"], timeout_s=60)

    async def do_abort():
        await asyncio.sleep(0.02)
        runner.abort()

    abort_task = asyncio.create_task(do_abort())
    result = await runner.run()
    await abort_task
    assert result["status"] == "aborted"
    assert "partial stdout" in result["output"]
    assert captured["proc"].killed


import json

import app.benchmark as bench_mod
from app.benchmark import parse_speed_bench_json, SpeedBenchRunner, AgenticRunner

SPEED_JSON = json.dumps({
    "summary": [
        {"category": "high_entropy", "requests": 1, "avg_prompt_t_s": 900.0, "avg_pred_t_s": 50.0},
        {"category": "overall", "requests": 3, "avg_prompt_t_s": 1000.0, "avg_pred_t_s": 88.8},
    ],
})


def test_parse_speed_bench_json_overall():
    r = parse_speed_bench_json(SPEED_JSON)
    assert r["prompt_processing_tps"] == 1000.0
    assert r["decode_tps"] == 88.8


def test_parse_speed_bench_json_no_overall():
    r = parse_speed_bench_json(json.dumps({"summary": [{"category": "high_entropy"}]}))
    assert r["prompt_processing_tps"] is None
    assert r["decode_tps"] is None


def test_parse_speed_bench_json_invalid():
    r = parse_speed_bench_json("not json")
    assert r["prompt_processing_tps"] is None
    assert r["decode_tps"] is None


def test_substitute_speed_bench_command():
    cmd = bench_mod._substitute_speed_bench_command(
        ["python", "s.py", "--url", "localhost:8080", "--limit", "1", "--output", "out.json"],
        port=9999, output_path="/tmp/real.json")
    assert cmd[cmd.index("--url") + 1] == "localhost:9999"
    assert cmd[cmd.index("--output") + 1] == "/tmp/real.json"
    assert cmd[cmd.index("--limit") + 1] == "1"


def test_free_port_returns_int():
    assert isinstance(bench_mod._free_port(), int)


class _FakeNamedTempFile:
    def __init__(self, path):
        self.name = str(path)

    def close(self):
        pass


class _FakeTempfile:
    def __init__(self, path):
        self._path = str(path)

    def NamedTemporaryFile(self, **kwargs):
        return _FakeNamedTempFile(self._path)


async def test_speed_bench_runner_ok(monkeypatch, tmp_path):
    seen = []
    procs = []
    spawned = []
    spawn_count = {"n": 0}

    def new_proc(out=b"", rc=0):
        p = FakeProc(out, rc=rc)
        procs.append(p)
        return p

    async def fake_create(*a, **k):
        spawned.append(a)
        spawn_count["n"] += 1
        if spawn_count["n"] == 1:
            p = new_proc(out=b"")
            p.returncode = None  # server still running until torn down
            return p
        return new_proc(out=b"")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    monkeypatch.setattr(bench_mod, "_free_port", lambda: 9123)
    async def fake_health(*a, **k):
        return True

    monkeypatch.setattr(bench_mod, "_wait_health", fake_health)
    out_path = tmp_path / "out.json"
    out_path.write_text(SPEED_JSON)
    monkeypatch.setattr(bench_mod, "tempfile", _FakeTempfile(out_path))

    runner = SpeedBenchRunner(
        server_command=["llama-server", "-m", "/models/x.gguf", "--spec-type", "draft-mtp"],
        bench_command=["python", "speed_bench.py", "--url", "localhost:8080", "--limit", "1",
                       "--category", "all", "--bench", "throughput_1k", "--output", "x.json"],
        timeout_s=60, startup_timeout_s=60, output_dir=tmp_path)

    async def on_output(kind, text):
        seen.append((kind, text))

    result = await runner.run(on_output=on_output)
    assert result["status"] == "ok"
    assert result["decode_tps"] == 88.8
    assert result["prompt_processing_tps"] == 1000.0
    assert len(spawned) == 2
    assert spawned[0][0] == "llama-server"
    assert "--port" in spawned[0] and "9123" in spawned[0]
    assert spawned[1][0] == "python"
    client_cmd = spawned[1]
    assert client_cmd[client_cmd.index("--url") + 1] == "localhost:9123"
    assert client_cmd[client_cmd.index("--output") + 1] == str(out_path)
    assert procs[0].killed is True


async def test_speed_bench_runner_server_not_ready(monkeypatch, tmp_path):
    async def fake_create(*a, **k):
        return FakeProc(b"")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    monkeypatch.setattr(bench_mod, "_free_port", lambda: 9123)
    async def fake_health(*a, **k):
        return False

    monkeypatch.setattr(bench_mod, "_wait_health", fake_health)

    runner = SpeedBenchRunner(
        server_command=["llama-server", "-m", "/models/x.gguf"],
        bench_command=["python", "speed_bench.py", "--url", "localhost:8080"],
        timeout_s=60, startup_timeout_s=5, output_dir=tmp_path)
    result = await runner.run()
    assert result["status"] == "failed"
    assert "not become ready" in result["output"]
    assert list(tmp_path.glob("speed-bench-*.json")) == []


async def test_speed_bench_runner_client_fails(monkeypatch, tmp_path):
    async def fake_create(*a, **k):
        return FakeProc(b"boom", rc=1)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    monkeypatch.setattr(bench_mod, "_free_port", lambda: 9123)
    async def fake_health(*a, **k):
        return True

    monkeypatch.setattr(bench_mod, "_wait_health", fake_health)

    runner = SpeedBenchRunner(
        server_command=["llama-server", "-m", "/models/x.gguf"],
        bench_command=["python", "speed_bench.py", "--url", "localhost:8080"],
        timeout_s=60, startup_timeout_s=5, output_dir=tmp_path)
    result = await runner.run()
    assert result["status"] == "failed"


async def test_runner_spawns_with_wsl2_pin_memory_env(monkeypatch):
    spawned_env = {}

    async def fake_create(*a, **k):
        spawned_env.update(k.get("env", {}) or {})
        return FakeProc(FAKE_BENCH.encode())

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="llama.cpp", bench_command=["llama-bench", "-m", "x"],
                             timeout_s=60)
    result = await runner.run()
    assert result["status"] == "ok"
    assert "PATH" in spawned_env


async def test_speed_bench_runner_spawns_with_wsl2_pin_memory_env(monkeypatch, tmp_path):
    spawned_envs = []
    procs = []
    spawn_count = {"n": 0}

    def new_proc(out=b"", rc=0):
        p = FakeProc(out, rc=rc)
        procs.append(p)
        return p

    async def fake_create(*a, **k):
        spawned_envs.append(k.get("env", {}) or {})
        spawn_count["n"] += 1
        if spawn_count["n"] == 1:
            p = new_proc(out=b"")
            p.returncode = None  # server still running until torn down
            return p
        return new_proc(out=b"")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    monkeypatch.setattr(bench_mod, "_free_port", lambda: 9123)
    async def fake_health(*a, **k):
        return True

    monkeypatch.setattr(bench_mod, "_wait_health", fake_health)
    out_path = tmp_path / "out.json"
    out_path.write_text(SPEED_JSON)
    monkeypatch.setattr(bench_mod, "tempfile", _FakeTempfile(out_path))

    runner = SpeedBenchRunner(
        server_command=["llama-server", "-m", "/models/x.gguf"],
        bench_command=["python", "speed_bench.py", "--url", "localhost:8080"],
        timeout_s=60, startup_timeout_s=5, output_dir=tmp_path)
    result = await runner.run()
    assert result["status"] == "ok"
    assert len(spawned_envs) == 2
    for env in spawned_envs:
        assert "PATH" in env


async def test_startup_watchdog_reports_progress_and_tail():
    parts = [b"0.00.5 I srv load_model: loading model 'org/m'\n"]
    seen = []

    async def on_output(kind, text):
        seen.append((kind, text))

    task = asyncio.create_task(
        bench_mod._startup_watchdog(43700, 300.0, parts, on_output, report_every_s=0.2))
    await asyncio.sleep(0.9)
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass

    assert len(seen) >= 2
    assert all(kind == "line" for kind, _ in seen)
    assert "waiting for llama-server on port 43700" in seen[0][1]
    assert "load_model" in seen[0][1]


async def test_speed_bench_runner_warns_while_server_not_ready(monkeypatch, tmp_path):
    seen = []

    async def on_output(kind, text):
        seen.append((kind, text))

    async def fake_create(*a, **k):
        return FakeProc(b"")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    monkeypatch.setattr(bench_mod, "_free_port", lambda: 9123)

    async def fake_health(*a, **k):
        await asyncio.sleep(0.6)
        return False

    monkeypatch.setattr(bench_mod, "_wait_health", fake_health)
    monkeypatch.setattr(bench_mod, "_STARTUP_REPORT_S", 0.2)

    runner = SpeedBenchRunner(
        server_command=["llama-server", "-m", "/models/x.gguf"],
        bench_command=["python", "speed_bench.py", "--url", "localhost:8080"],
        timeout_s=60, startup_timeout_s=2, output_dir=tmp_path)
    result = await runner.run(on_output=on_output)

    assert result["status"] == "failed"
    assert any("waiting for llama-server" in text for _, text in seen)


AGENTIC_SESSION_RESULT = {
    "agentic_tps": 25.0,
    "prompt_processing_tps": None,
    "decode_tps": None,
    "total_prompt_tokens": 9000,
    "total_completion_tokens": 1600,
    "total_wall_s": 64.0,
    "turns": 4,
    "per_turn": [],
}


async def test_agentic_runner_ok(monkeypatch, tmp_path):
    spawned = []
    procs = []
    spawn_count = {"n": 0}

    def new_proc(out=b"", rc=0):
        p = FakeProc(out, rc=rc)
        procs.append(p)
        return p

    async def fake_create(*a, **k):
        spawned.append(a)
        spawn_count["n"] += 1
        if spawn_count["n"] == 1:
            p = new_proc(out=b"")
            p.returncode = None
            return p
        return new_proc(out=b"")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    monkeypatch.setattr(bench_mod, "_free_port", lambda: 9123)

    async def fake_health(*a, **k):
        return True

    monkeypatch.setattr(bench_mod, "_wait_health", fake_health)

    async def fake_session(base_url, model, turns, max_tokens, prompts,
                           on_output=None, request_timeout=120.0, transport=None):
        return dict(AGENTIC_SESSION_RESULT)

    monkeypatch.setattr(agentic_mod, "run_agentic_session", fake_session)
    monkeypatch.setattr(agentic_mod, "load_workload_prompts", lambda path: ["t"])

    runner = AgenticRunner(
        server_command=["llama-server", "-m", "/models/x.gguf"],
        params={"model": "x.gguf", "turns": "4", "max_tokens": "16384"},
        timeout_s=60, startup_timeout_s=60,
        workload_file=str(tmp_path / "p.jsonl"))
    result = await runner.run()
    assert result["status"] == "ok"
    assert result["agentic_tps"] == 25.0
    assert len(spawned) == 1
    assert "--port" in spawned[0] and "9123" in spawned[0]
    assert procs[0].killed is True


async def test_agentic_runner_server_not_ready(monkeypatch, tmp_path):
    async def fake_create(*a, **k):
        return FakeProc(b"")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    monkeypatch.setattr(bench_mod, "_free_port", lambda: 9123)

    async def fake_health(*a, **k):
        return False

    monkeypatch.setattr(bench_mod, "_wait_health", fake_health)

    runner = AgenticRunner(
        server_command=["llama-server", "-m", "/models/x.gguf"],
        params={}, timeout_s=60, startup_timeout_s=5,
        workload_file=str(tmp_path / "p.jsonl"))
    result = await runner.run()
    assert result["status"] == "failed"
    assert "not become ready" in result["output"]


async def test_agentic_runner_session_raises(monkeypatch, tmp_path):
    async def boom(*a, **k):
        raise RuntimeError("boom")

    async def fake_health(*a, **k):
        return True

    async def fake_create(*a, **k):
        return FakeProc(b"")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    monkeypatch.setattr(bench_mod, "_free_port", lambda: 9123)
    monkeypatch.setattr(bench_mod, "_wait_health", fake_health)
    monkeypatch.setattr(agentic_mod, "run_agentic_session", boom)
    monkeypatch.setattr(agentic_mod, "load_workload_prompts", lambda path: ["t"])
    runner = AgenticRunner(
        server_command=["llama-server", "-m", "/models/x.gguf"],
        params={}, timeout_s=60, startup_timeout_s=5,
        workload_file=str(tmp_path / "p.jsonl"))
    result = await runner.run()
    assert result["status"] == "failed"
