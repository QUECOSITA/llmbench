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


SGLANG_OUT = """\
prefill throughput: 1200.00 token/s
decode throughput: 90.10 token/s
"""


def test_parse_sglang_bench():
    r = parse_sglang_bench(SGLANG_OUT)
    assert r["prompt_processing_tps"] == 1200.0
    assert r["decode_tps"] == 90.1
