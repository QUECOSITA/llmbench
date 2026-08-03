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
        return self._out, ""

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


async def test_runner_serial_and_parses(monkeypatch):
    calls = []

    async def fake_create(*args, **kwargs):
        calls.append(args)
        return FakeProcess(FAKE_BENCH.encode())

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="llama.cpp", bench_command=["llama-bench", "-m", "x"],
                             timeout_s=60)
    result = await runner.run()
    assert result["status"] == "ok"
    assert result["decode_tps"] == 80.0
    assert result["prompt_processing_tps"] == 1000.0


async def test_runner_timeout_kills(monkeypatch):
    class SlowProcess(FakeProcess):
        def __init__(self):
            super().__init__(b"")
            self.waiter = asyncio.Event()

        async def communicate(self):
            await asyncio.wait_for(self.waiter.wait(), 10)
            return b"", ""

    async def fake_create(*a, **k):
        return SlowProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="llama.cpp", bench_command=["llama-bench"],
                             timeout_s=0.05)
    result = await runner.run()
    assert result["status"] == "failed"


async def test_runner_abort(monkeypatch):
    async def fake_create(*a, **k):
        proc = FakeProcess(b"")
        return proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="llama.cpp", bench_command=["llama-bench"],
                             timeout_s=60)
    runner.abort()
    result = await runner.run()
    assert result["status"] == "aborted"


async def test_runner_parser_error_returns_failed(monkeypatch):
    async def fake_create(*a, **k):
        return FakeProcess(b"bunch of non-json text")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)
    runner = BenchmarkRunner(server_id="vllm", bench_command=["bench"],
                             timeout_s=60)
    result = await runner.run()
    assert result["status"] == "failed"
