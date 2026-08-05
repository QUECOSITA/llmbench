from app.benchmark import parse_llama_bench_csv, parse_vllm_throughput, parse_sglang_bench

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


VLLM_OUT = """\
{
  "elapsed_time": 30.0,
  "num_requests": 20,
  "total_prompt_tokens": 10240,
  "total_generation_tokens": 2560,
  "request_throughput": 0.67,
  "output_token_throughput": 85.3,
  "total_token_throughput": 426.7,
  "input_token_throughput": 341.3
}
"""


def test_parse_vllm_throughput():
    r = parse_vllm_throughput(VLLM_OUT)
    assert r["prompt_processing_tps"] == 341.3
    assert r["decode_tps"] == 85.3


def test_parse_vllm_throughput_mixed_stdout():
    r = parse_vllm_throughput("INFO: root: some log line\n" + VLLM_OUT)
    assert r["prompt_processing_tps"] == 341.3
    assert r["decode_tps"] == 85.3


def test_parse_vllm_throughput_real_keys():
    r = parse_vllm_throughput('{"tokens_per_second": 99.5, "requests_per_second": 2.1}')
    assert r["decode_tps"] == 99.5
    assert r["prompt_processing_tps"] is None


def test_parse_vllm_throughput_no_json():
    r = parse_vllm_throughput("bunch of non-json text")
    assert r["prompt_processing_tps"] is None
    assert r["decode_tps"] is None


def test_parse_vllm_throughput_two_json_blocks():
    r = parse_vllm_throughput('{"a":1} and {"tokens_per_second": 42.0}')
    assert r["prompt_processing_tps"] is None
    assert r["decode_tps"] == 42.0


def test_parse_vllm_throughput_last_block_not_throughput():
    r = parse_vllm_throughput('{"tokens_per_second": 42.0} and {"a":1}')
    assert r["prompt_processing_tps"] is None
    assert r["decode_tps"] is None


SGLANG_OUT = """\
prefill throughput: 1200.00 token/s
decode throughput: 90.10 token/s
"""


def test_parse_sglang_bench():
    r = parse_sglang_bench(SGLANG_OUT)
    assert r["prompt_processing_tps"] == 1200.0
    assert r["decode_tps"] == 90.1


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
    runner = BenchmarkRunner(server_id="vllm", bench_command=["bench"], timeout_s=60)
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
