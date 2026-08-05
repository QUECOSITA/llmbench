import csv
import io
import json
import re
from app.tty_stream import TtyStream


def parse_llama_bench_csv(text: str) -> dict:
    rows = list(csv.DictReader(io.StringIO(text)))

    if rows and "avg_ts" in rows[0]:
        pp = None
        tg = None
        for r in rows:
            try:
                n_prompt = int(r.get("n_prompt") or 0)
            except (TypeError, ValueError):
                n_prompt = 0
            try:
                n_gen = int(r.get("n_gen") or 0)
            except (TypeError, ValueError):
                n_gen = 0
            try:
                ts = float(r["avg_ts"])
            except (TypeError, ValueError):
                ts = None
            if n_prompt > 0 and n_gen == 0:
                pp = ts
            elif n_gen > 0:
                tg = ts
        return {"prompt_processing_tps": pp, "decode_tps": tg}

    def tps(row):
        try:
            return float(row.get("t/s"))
        except (TypeError, ValueError):
            return None

    pp = next((tps(r) for r in rows if r.get("test") == "pp"), None)
    tg = next((tps(r) for r in rows if r.get("test") == "tg"), None)
    return {"prompt_processing_tps": pp, "decode_tps": tg}


def parse_vllm_throughput(text: str) -> dict:
    matches = re.findall(r"\{.*?\}", text, re.DOTALL)
    if not matches:
        return {"prompt_processing_tps": None, "decode_tps": None}
    data = json.loads(matches[-1])
    return {
        "prompt_processing_tps": data.get("input_token_throughput"),
        "decode_tps": data.get("tokens_per_second", data.get("output_token_throughput")),
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

import asyncio


class BenchmarkRunner:
    def __init__(self, server_id: str, bench_command: list[str], timeout_s: float):
        self.server_id = server_id
        self.bench_command = bench_command
        self.timeout_s = timeout_s
        self._aborted = asyncio.Event()
        self._done = asyncio.Event()
        self._proc: asyncio.subprocess.Process | None = None

    def abort(self) -> None:
        self._aborted.set()
        if self._proc is not None:
            self._proc.kill()

    async def run(self, on_output=None) -> dict:
        """Run the bench command, streaming decoded (kind, text) events to
        on_output. Returns the parsed result with full output text."""
        self._done.clear()
        if self._aborted.is_set():
            self._done.set()
            return {"status": "aborted", "prompt_processing_tps": None, "decode_tps": None,
                    "duration_s": 0.0, "output": ""}
        start = asyncio.get_event_loop().time()
        self._proc = await asyncio.create_subprocess_exec(
            *self.bench_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes, rc = await asyncio.wait_for(
                self._collect(self._proc, on_output), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            self._proc.kill()
            await self._proc.wait()
            duration = asyncio.get_event_loop().time() - start
            self._done.set()
            return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                    "duration_s": duration, "output": f"timeout after {self.timeout_s}s"}
        except Exception:
            self._proc.kill()
            await self._proc.wait()
            self._done.set()
            raise
        finally:
            self._proc = None
        duration = asyncio.get_event_loop().time() - start
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        output = "\n".join(part for part in (stdout, stderr) if part)
        if self._aborted.is_set():
            self._done.set()
            return {"status": "aborted", "prompt_processing_tps": None, "decode_tps": None,
                    "duration_s": duration, "output": output}
        if rc != 0:
            self._done.set()
            return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                    "duration_s": duration, "output": output}
        try:
            parsed = PARSERS[self.server_id](stdout)
        except Exception:
            self._done.set()
            return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                    "duration_s": duration, "output": output}
        if parsed["decode_tps"] is None:
            self._done.set()
            return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                    "duration_s": duration, "output": output}
        self._done.set()
        return {"status": "ok", **parsed, "duration_s": duration, "output": output}

    async def _collect(self, proc, on_output) -> tuple[bytes, bytes, int]:
        out_tty = TtyStream()
        err_tty = TtyStream()
        out_parts: list[bytes] = []
        err_parts: list[bytes] = []

        async def pump(stream, tty, parts):
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                if self._aborted.is_set():
                    proc.kill()
                    break
                parts.append(chunk)
                if on_output is not None:
                    for kind, text in tty.feed(chunk):
                        await on_output(kind, text)
            if on_output is not None:
                for kind, text in tty.flush():
                    await on_output(kind, text)

        await asyncio.gather(pump(proc.stdout, out_tty, out_parts),
                             pump(proc.stderr, err_tty, err_parts))
        rc = proc.returncode
        if rc is None:
            rc = await proc.wait()
        return b"".join(out_parts), b"".join(err_parts), rc
