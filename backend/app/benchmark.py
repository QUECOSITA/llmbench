import csv
import io
import json
import re


def parse_llama_bench_csv(text: str) -> dict:
    rows = list(csv.DictReader(io.StringIO(text)))
    pp = next((float(r["t/s"]) for r in rows if r["test"] == "pp"), None)
    tg = next((float(r["t/s"]) for r in rows if r["test"] == "tg"), None)
    return {"prompt_processing_tps": pp, "decode_tps": tg}


def parse_vllm_throughput(text: str) -> dict:
    data = json.loads(text)
    return {
        "prompt_processing_tps": data.get("input_token_throughput"),
        "decode_tps": data.get("output_token_throughput"),
    }


def parse_sglang_bench(text: str) -> dict:
    pp = re.search(r"prefill throughput:\s*([\d.]+)", text)
    tg = re.search(r"decode throughput:\s*([\d.]+)", text)
    return {
        "prompt_processing_tps": float(pp.group(1)) if pp else None,
        "decode_tps": float(tg.group(1)) if tg else None,
    }


PARSERS = {
    "llama.cpp": parse_llama_bench_csv,
    "vllm": parse_vllm_throughput,
    "sglang": parse_sglang_bench,
}
