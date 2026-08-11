import asyncio
import csv
import io
import json
import os
import socket
import tempfile
from pathlib import Path

from app.spawn import spawn_env
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


PARSERS = {
    "llama.cpp": parse_llama_bench_csv,
}


async def _collect_proc(proc, on_output, aborted: asyncio.Event | None = None):
    out_tty = TtyStream()
    err_tty = TtyStream()
    out_parts: list[bytes] = []
    err_parts: list[bytes] = []

    async def pump(stream, tty, parts):
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            if aborted is not None and aborted.is_set():
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
            env=spawn_env(),
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
        return await _collect_proc(proc, on_output, self._aborted)


def parse_speed_bench_json(text: str) -> dict:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"prompt_processing_tps": None, "decode_tps": None}
    summary = data.get("summary") or []
    overall = next((r for r in summary if r.get("category") == "overall"), None)
    if not overall:
        return {"prompt_processing_tps": None, "decode_tps": None}
    return {
        "prompt_processing_tps": overall.get("avg_prompt_t_s"),
        "decode_tps": overall.get("avg_pred_t_s"),
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _substitute_speed_bench_command(cmd: list[str], port: int, output_path: str) -> list[str]:
    out: list[str] = []
    skip_next = False
    for tok in cmd:
        if skip_next:
            skip_next = False
            continue
        if tok == "--url":
            out += [tok, f"localhost:{port}"]
            skip_next = True
        elif tok == "--output":
            out += [tok, output_path]
            skip_next = True
        else:
            out.append(tok)
    return out


def _decode_parts(parts: list[bytes]) -> str:
    return "\n".join(p.decode(errors="replace") for p in parts if p)


_STARTUP_REPORT_S = 10.0


async def _startup_watchdog(port: int, allowed_s: float, parts: list[bytes],
                            on_output, report_every_s: float = _STARTUP_REPORT_S) -> None:
    """While a server is starting, periodically surface that we are still
    waiting. llama.cpp buffers its logs when stdout/stderr is not a TTY, so a
    slow startup can otherwise be completely silent for minutes."""
    loop = asyncio.get_event_loop()
    start = loop.time()
    next_report = start + report_every_s
    while True:
        await asyncio.sleep(0.1)
        if on_output is None:
            return
        now = loop.time()
        if now < next_report:
            continue
        next_report = now + report_every_s
        elapsed = now - start
        tail = _decode_parts(parts[-6:]).strip()
        msg = (f"waiting for llama-server on port {port}: {elapsed:.0f}s elapsed "
               f"(up to {allowed_s:.0f}s allowed) — server not ready yet")
        if tail:
            msg += f"\nlatest server output:\n{tail[-800:]}"
        else:
            msg += ("\nno server output yet — llama.cpp logs are likely buffered; "
                    "the model may be downloading or the GPU may be busy")
        await on_output("line", msg)


async def _wait_health(port: int, timeout_s: float) -> bool:
    import httpx
    url = f"http://127.0.0.1:{port}/health"
    deadline = asyncio.get_event_loop().time() + timeout_s
    async with httpx.AsyncClient(timeout=2.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return False


class SpeedBenchRunner:
    """Benchmark a llama.cpp model via speed-bench: start llama-server, wait for
    /health, run speed_bench.py against it, parse the --output JSON, and kill the
    server. speed-bench cannot run as a standalone CLI like llama-bench."""

    def __init__(self, server_command: list[str], bench_command: list[str],
                 timeout_s: float, startup_timeout_s: float, output_dir: str | Path):
        self.server_command = list(server_command)
        self.bench_command = list(bench_command)
        self.timeout_s = timeout_s
        self.startup_timeout_s = startup_timeout_s
        self.output_dir = Path(output_dir)
        self._aborted = asyncio.Event()
        self._procs: list[asyncio.subprocess.Process] = []

    def abort(self) -> None:
        self._aborted.set()
        for proc in self._procs:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

    async def _pump(self, proc, parts: list[bytes], on_output) -> int:
        out_tty = TtyStream()
        err_tty = TtyStream()

        async def pump(stream, tty):
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

        await asyncio.gather(pump(proc.stdout, out_tty), pump(proc.stderr, err_tty))
        rc = proc.returncode
        if rc is None:
            rc = await proc.wait()
        return rc

    async def run(self, on_output=None) -> dict:
        start = asyncio.get_event_loop().time()
        if not self.server_command or not self.bench_command:
            return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                    "duration_s": 0.0,
                    "output": "speed-bench is not configured: missing server or client command"}
        port = _free_port()
        output_fh = tempfile.NamedTemporaryFile(prefix="speed-bench-", suffix=".json",
                                                dir=str(self.output_dir), delete=False)
        output_path = output_fh.name
        output_fh.close()
        server_cmd = list(self.server_command) + ["--port", str(port), "--host", "127.0.0.1"]
        client_cmd = _substitute_speed_bench_command(self.bench_command, port, output_path)

        server_proc = None
        client_proc = None
        server_pump: asyncio.Task | None = None
        parts: list[bytes] = []
        try:
            server_proc = await asyncio.create_subprocess_exec(
                *server_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=spawn_env(),
            )
            self._procs.append(server_proc)
            server_pump = asyncio.create_task(self._pump(server_proc, parts, on_output))

            watchdog = None
            if on_output is not None:
                watchdog = asyncio.create_task(
                    _startup_watchdog(port, self.startup_timeout_s, parts, on_output,
                                      report_every_s=_STARTUP_REPORT_S))
            try:
                ready = await _wait_health(port, self.startup_timeout_s)
            finally:
                if watchdog is not None:
                    watchdog.cancel()
                    try:
                        await watchdog
                    except (asyncio.CancelledError, Exception):
                        pass
            if self._aborted.is_set():
                return {"status": "aborted", "prompt_processing_tps": None, "decode_tps": None,
                        "duration_s": asyncio.get_event_loop().time() - start,
                        "output": _decode_parts(parts)}
            if not ready:
                return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                        "duration_s": asyncio.get_event_loop().time() - start,
                        "output": f"llama-server did not become ready on port {port} "
                                  f"within {self.startup_timeout_s}s\n{_decode_parts(parts)}"}

            client_proc = await asyncio.create_subprocess_exec(
                *client_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=spawn_env(),
            )
            self._procs.append(client_proc)
            try:
                await asyncio.wait_for(self._pump(client_proc, parts, on_output), timeout=self.timeout_s)
                rc = client_proc.returncode if client_proc.returncode is not None else 0
            except asyncio.TimeoutError:
                client_proc.kill()
                await client_proc.wait()
                rc = -1
            except Exception:
                client_proc.kill()
                await client_proc.wait()
                raise
            duration = asyncio.get_event_loop().time() - start
            output = _decode_parts(parts)
            if self._aborted.is_set():
                return {"status": "aborted", "prompt_processing_tps": None, "decode_tps": None,
                        "duration_s": duration, "output": output}
            if rc != 0:
                return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                        "duration_s": duration, "output": output}
            try:
                with open(output_path, encoding="utf-8") as fh:
                    parsed = parse_speed_bench_json(fh.read())
            except OSError:
                parsed = {"prompt_processing_tps": None, "decode_tps": None}
            if parsed["decode_tps"] is None:
                return {"status": "failed", "prompt_processing_tps": None, "decode_tps": None,
                        "duration_s": duration, "output": output}
            return {"status": "ok", **parsed, "duration_s": duration, "output": output}
        finally:
            for proc in (client_proc, server_proc):
                if proc is not None and proc.returncode is None:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
            if server_pump is not None:
                server_pump.cancel()
                try:
                    await server_pump
                except (asyncio.CancelledError, Exception):
                    pass
            self._procs.clear()
            try:
                if os.path.getsize(output_path) == 0:
                    os.unlink(output_path)
            except OSError:
                pass
