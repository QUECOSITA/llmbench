import asyncio
import fcntl
import logging
import os
import shutil
import signal
import struct
import termios
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app import benchmark as benchmark_mod
from app import db as db_mod
from app import sync as sync_mod
from app.config import Settings
from app.fit import arch_from_config, config_fit, fit_verdict
from app.flags import build_serving_command, generate_configs
from app.hardware import detect_hardware
from app.hf import HfClient, InvalidModelInput, normalize_input, parse_input
from app.readme_parser import detect_serving_programs, extract_flags, top_serving_program
from app.servers import (build_bench_command, build_server_command, build_speed_bench_command,
                         detect_binaries, is_spec_decoding_model, model_ref_from_flags,
                         parse_serving_command, resolve_speed_bench_script)
from app.tty_stream import TtyStream

router = APIRouter(prefix="/api")

logger = logging.getLogger(__name__)


KNOWN_SERVERS = ("llama.cpp", "vllm", "sglang")

AUTO_ADVANCE_GRACE_S = 3.0


def _download_command(repo_id: str, server_id: str, gguf_filename: str | None = None,
                      cache_dir: str | None = None) -> list[str]:
    cmd = ["hf", "download", "--format", "human", repo_id]
    if server_id == "llama.cpp":
        cmd += ["--include", gguf_filename or "*.gguf"]
    if cache_dir:
        cmd += ["--cache-dir", cache_dir]
    return cmd


def _prune_command(cache_dir: str | None = None) -> list[str]:
    cmd = ["hf", "cache", "prune", "--format", "human"]
    if cache_dir:
        cmd += ["--cache-dir", cache_dir]
    return cmd


def _open_pty() -> tuple[int, int]:
    """Open a pty with a real window size.

    os.openpty() defaults to a 0x0 terminal. Tools like tqdm query the size and
    suppress their progress bars entirely when it reads 0 columns/rows, so set a
    sane default on the slave before the child is spawned.
    """
    master_fd, slave_fd = os.openpty()
    try:
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    except OSError:
        pass
    return master_fd, slave_fd


async def _spawn_pty(cmd: list[str], stdin_fd: int, stdout_fd: int, stderr_fd: int):
    return await asyncio.create_subprocess_exec(
        *cmd, stdin=stdin_fd, stdout=stdout_fd, stderr=stderr_fd, start_new_session=True,
    )


async def _read_master(master_fd: int) -> asyncio.Queue[bytes | None]:
    """Read a pty master fd on a background thread into an asyncio queue."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    def _read() -> None:
        try:
            while True:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                loop.call_soon_threadsafe(queue.put_nowait, data)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=_read, daemon=True).start()
    return queue


async def _stream_download_output(master_fd: int):
    """Yield (kind, text) events parsed from a pty master fd."""
    queue = await _read_master(master_fd)
    tty = TtyStream()
    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        for event in tty.feed(chunk):
            yield event
    for event in tty.flush():
        yield event


async def _force_kill_after(proc, delay: float) -> None:
    await asyncio.sleep(delay)
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.conn = db_mod.init_db(settings.data_dir / "llmbench.db")
        self.lock = asyncio.Lock()
        self.runner: benchmark_mod.BenchmarkRunner | benchmark_mod.SpeedBenchRunner | None = None
        self._ws_clients: set[WebSocket] = set()
        self._state_lock = threading.Lock()
        self._job_active = False
        self._download_active = False
        self._download_proc: asyncio.subprocess.Process | None = None
        self._download_cancelled = False
        self._prune_proc: asyncio.subprocess.Process | None = None
        self._prune_answer: asyncio.Queue[str] | None = None
        self._continue_queue: asyncio.Queue | None = None
        self._active_run_id: int | None = None


state: AppState | None = None
_hf = HfClient()


def init_state(settings: Settings) -> AppState:
    global state
    state = AppState(settings)
    return state


async def broadcast(state: AppState, event: dict) -> None:
    dead = []
    for ws in list(state._ws_clients):
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        state._ws_clients.discard(ws)


def _require_state() -> AppState:
    if state is None:
        raise HTTPException(503, "app not initialized")
    return state


@router.get("/servers")
async def servers():
    s = _require_state()
    bin_dir = str(s.settings.llama_cpp_bin_dir) if s.settings.llama_cpp_bin_dir else None
    return {"readiness": detect_binaries(bin_dir), "hardware": detect_hardware()}


@router.post("/models/analyze")
async def analyze(payload: dict):
    s = _require_state()
    raw = payload.get("input")
    if raw is None:
        raise HTTPException(422, "Missing required field 'input'.")
    try:
        repo_id, file_path = parse_input(raw)
    except InvalidModelInput as e:
        raise HTTPException(422, str(e))
    sync_mod.reconcile_models(s.conn, s.settings)
    try:
        readme, files = _hf.fetch_repo(repo_id, file_path=file_path)
        if file_path:
            files = [f for f in files if f.get("path") == file_path]
    except Exception as e:
        raise HTTPException(404, f"Could not fetch repo {repo_id}: {e}")
    gguf = _hf.gguf_files(files)
    scores = detect_serving_programs(readme, has_gguf=bool(gguf))
    detected = top_serving_program(scores)
    flags = extract_flags(readme, [detected or "vllm"])
    weights = _hf.weights_size_bytes(files)
    hw = detect_hardware()
    arch = None
    if any(f.get("path", "").lower() == "config.json" for f in files):
        try:
            arch = arch_from_config(_hf.fetch_config(repo_id))
        except Exception:
            arch = None
    verdict = fit_verdict(weights, hw["gpu_vram_gb"], hw["ram_total_gb"], arch=arch)
    return {
        "repo_id": repo_id,
        "detected_server": detected,
        "server_scores": scores,
        "readme_flags": flags,
        "gguf_files": gguf,
        "weights_bytes": weights,
        "downloaded": _model_status(s, repo_id),
        "fit_verdict": verdict,
        "model_arch": arch,
        "hardware": {
            "gpu_vram_gb": hw["gpu_vram_gb"],
            "ram_total_gb": hw["ram_total_gb"],
            "gpu_name": hw["gpu_name"],
        },
    }


def _model_status(s: AppState, repo_id: str) -> dict[str, bool]:
    out = {}
    for server_id in ("llama.cpp", "vllm", "sglang"):
        m = db_mod.get_model(s.conn, repo_id, server_id)
        out[server_id] = bool(m and m["status"] == "downloaded")
    return out


def _hf_snapshot_dir(settings: Settings, repo_id: str) -> Path:
    return sync_mod.snapshot_dir_for(settings, repo_id)


def _resolve_download_path(s: AppState, repo_id: str, server_id: str,
                           gguf_filename: str | None) -> tuple[str | None, str | None, int | None]:
    if server_id == "llama.cpp":
        gguf_dir = s.settings.resolved_gguf_dir
        if gguf_filename and (gguf_dir / gguf_filename).exists():
            p = gguf_dir / gguf_filename
            return str(p), gguf_filename, p.stat().st_size
        for p in sorted(gguf_dir.glob("*.gguf")):
            return str(p), p.name, p.stat().st_size
        snapshot = _hf_snapshot_dir(s.settings, repo_id)
        ggufs = sync_mod._ggufs_in_snapshot(snapshot)
        if ggufs:
            g = max(ggufs, key=lambda p: p.stat().st_size)
            return str(g), g.name, g.stat().st_size
        return None, None, None
    snapshot = _hf_snapshot_dir(s.settings, repo_id)
    if snapshot.exists():
        return str(snapshot), None, None
    return None, None, None


async def _download_job(s: AppState, repo_id: str, server_id: str,
                        cmd: list[str], gguf_filename: str | None):
    proc = None
    master_fd = None
    slave_fd = None
    try:
        await broadcast(s, {"type": "download_started", "server_id": server_id,
                            "repo_id": repo_id, "command": " ".join(cmd)})
        master_fd, slave_fd = _open_pty()
        proc = await _spawn_pty(cmd, slave_fd, slave_fd, slave_fd)
        try:
            os.close(slave_fd)
            slave_fd = None
        except OSError:
            slave_fd = None
        s._download_proc = proc
        async for kind, text in _stream_download_output(master_fd):
            if kind == "line":
                await broadcast(s, {"type": "download_log", "server_id": server_id,
                                    "repo_id": repo_id, "line": text})
            else:
                await broadcast(s, {"type": "download_progress", "server_id": server_id,
                                    "repo_id": repo_id, "line": text})
        rc = await proc.wait()
        s._download_proc = None
        if s._download_cancelled:
            await broadcast(s, {"type": "download_cancelled", "server_id": server_id,
                                "repo_id": repo_id})
            await _prune_job(s, repo_id, server_id)
            return
        if rc != 0:
            db_mod.upsert_model(s.conn, repo_id=repo_id, server_id=server_id,
                                format="hf", local_path="", status="missing")
            await broadcast(s, {"type": "download_error", "server_id": server_id,
                                "repo_id": repo_id, "message": f"download exited with code {rc}"})
            return
        local_path, gguf_resolved, size = _resolve_download_path(s, repo_id, server_id, gguf_filename)
        if local_path is None:
            db_mod.upsert_model(s.conn, repo_id=repo_id, server_id=server_id,
                                format="hf", local_path="", status="missing")
            await broadcast(s, {"type": "download_error", "server_id": server_id,
                                "repo_id": repo_id, "message": "download finished but no artifact was found"})
            return
        db_mod.upsert_model(s.conn, repo_id=repo_id, server_id=server_id, format="hf",
                            local_path=local_path, status="downloaded",
                            gguf_filename=gguf_resolved, size_bytes=size,
                            downloaded_at=datetime.now(timezone.utc).isoformat())
        await broadcast(s, {"type": "download_done", "server_id": server_id,
                            "repo_id": repo_id, "status": "downloaded", "local_path": local_path})
    except Exception as e:
        await broadcast(s, {"type": "download_error", "server_id": server_id,
                            "repo_id": repo_id, "message": str(e)})
    finally:
        for fd in (slave_fd, master_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        s._download_proc = None
        s._download_cancelled = False
        with s._state_lock:
            s._download_active = False


@router.get("/models")
async def models():
    s = _require_state()
    sync_mod.reconcile_models(s.conn, s.settings)
    return {"models": db_mod.list_models(s.conn, status="downloaded")}


@router.delete("/models/{model_ref:path}")
async def delete_model(model_ref: str):
    s = _require_state()
    try:
        await sync_mod.remove_model(s.conn, s.settings, model_ref)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return {"ok": True}


@router.post("/models/download")
async def start_download(payload: dict):
    s = _require_state()
    repo_id = payload.get("repo_id")
    server_id = payload.get("server_id")
    if repo_id is None:
        raise HTTPException(422, "Missing required field 'repo_id'.")
    if server_id not in KNOWN_SERVERS:
        raise HTTPException(422, f"'server_id' must be one of {list(KNOWN_SERVERS)}.")
    cache_dir = str(s.settings.hf_cache_dir) if s.settings.hf_cache_dir else None
    cmd = _download_command(repo_id, server_id, payload.get("gguf_filename"), cache_dir=cache_dir)
    if shutil.which("hf") is None:
        raise HTTPException(400, f"HF CLI not found. Run: {' '.join(cmd)}")
    with s._state_lock:
        if s._download_active:
            raise HTTPException(409, "A download is already running")
        s._download_active = True
    try:
        asyncio.create_task(_download_job(s, repo_id, server_id, cmd, payload.get("gguf_filename")))
    except Exception:
        with s._state_lock:
            s._download_active = False
        raise
    return {"ok": True}


async def _prune_job(s: AppState, repo_id: str, server_id: str):
    cache_dir = str(s.settings.hf_cache_dir) if s.settings.hf_cache_dir else None
    cmd = _prune_command(cache_dir=cache_dir)
    proc = None
    last_line = ""
    prompt_sent = False
    try:
        await broadcast(s, {"type": "prune_started", "server_id": server_id,
                            "repo_id": repo_id, "command": " ".join(cmd)})
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        s._prune_proc = proc
        buf = ""
        while True:
            chunk = await proc.stdout.read(1024)
            if not chunk:
                break
            buf += chunk.decode(errors="replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.rstrip("\r")
                if line:
                    last_line = line
                    await broadcast(s, {"type": "prune_log", "server_id": server_id,
                                        "repo_id": repo_id, "line": line})
            if not prompt_sent and "Proceed?" in buf:
                prompt_sent = True
                q: asyncio.Queue[str] = asyncio.Queue()
                s._prune_answer = q
                await broadcast(s, {"type": "prune_prompt", "server_id": server_id,
                                    "repo_id": repo_id})
                answer = await q.get()
                assert proc.stdin is not None
                proc.stdin.write((answer + "\n").encode())
                await proc.stdin.drain()
                buf = ""
        rc = await proc.wait()
        await broadcast(s, {"type": "prune_done", "server_id": server_id,
                            "repo_id": repo_id, "accepted": rc == 0, "message": last_line})
    except Exception as e:
        await broadcast(s, {"type": "prune_done", "server_id": server_id,
                            "repo_id": repo_id, "accepted": False, "message": str(e)})
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        s._prune_proc = None
        s._prune_answer = None


@router.post("/models/download/cancel")
async def cancel_download():
    s = _require_state()
    with s._state_lock:
        if not s._download_active:
            raise HTTPException(409, "No download is running")
        s._download_cancelled = True
    proc = s._download_proc
    if proc is not None:
        try:
            proc.send_signal(signal.SIGINT)
        except (ProcessLookupError, OSError):
            pass
        asyncio.create_task(_force_kill_after(proc, 5.0))
    return {"ok": True}


@router.post("/models/download/prune-answer")
async def prune_answer(payload: dict):
    s = _require_state()
    answer = payload.get("answer")
    if answer not in ("y", "n"):
        raise HTTPException(422, "'answer' must be 'y' or 'n'.")
    if s._prune_answer is None:
        raise HTTPException(409, "No prune is waiting for input")
    await s._prune_answer.put(answer)
    return {"ok": True}


@router.post("/configs/generate")
async def generate(payload: dict):
    s = _require_state()
    server_id = payload.get("server_id")
    repo_id = payload.get("repo_id")
    n = payload.get("n")
    if server_id is None:
        raise HTTPException(422, "Missing required field 'server_id'.")
    if repo_id is None:
        raise HTTPException(422, "Missing required field 'repo_id'.")
    if n is None:
        raise HTTPException(422, "Missing required field 'n'.")
    try:
        n = int(n)
    except (TypeError, ValueError):
        raise HTTPException(422, "'n' must be an integer.")
    if n < 1:
        raise HTTPException(422, "'n' must be at least 1.")
    vram_gb = float(payload.get("vram_gb", 24.0))
    try:
        configs = generate_configs(
            server_id=server_id,
            readme_flags=payload.get("readme_flags", {}),
            n=n,
            vram_gb=vram_gb,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    weights = payload.get("weights_bytes")
    resolved_gguf = payload.get("gguf_path")
    gguf_filename = os.path.basename(resolved_gguf) if resolved_gguf else None
    if resolved_gguf is None and server_id == "llama.cpp":
        local_path, name, _size = _resolve_download_path(s, repo_id, "llama.cpp", None)
        resolved_gguf = local_path
        gguf_filename = name
    bin_dir = str(s.settings.llama_cpp_bin_dir) if s.settings.llama_cpp_bin_dir else None
    uses_speed_bench = (
        server_id == "llama.cpp"
        and is_spec_decoding_model(repo_id, gguf_filename, payload.get("readme_flags", {}))
    )
    for cfg in configs:
        cfg["serving_command"] = build_serving_command(
            server_id, repo_id, cfg["flags"],
            gguf_filename=gguf_filename,
            gguf_path=resolved_gguf,
        )
        cfg["bench_tool"] = "speed-bench" if uses_speed_bench else "llama-bench"
        if uses_speed_bench:
            script = resolve_speed_bench_script(bin_dir, configured=s.settings.speed_bench_script)
            if script:
                cfg["bench_command"] = build_speed_bench_command(
                    script, osl=s.settings.speed_bench_osl,
                    output=str(s.settings.data_dir / "speed-bench.json"))
            else:
                cfg["bench_command"] = []
                cfg["bench_error"] = (
                    "speed-bench is not available for this model: could not locate speed_bench.py "
                    "next to llama-server. Set LLMBENCH_SPEED_BENCH_SCRIPT or install llama.cpp "
                    "with the speed-bench tool.")
        else:
            bench_ref = repo_id if gguf_filename else (resolved_gguf or repo_id)
            cfg["bench_command"] = build_bench_command(
                server_id, bench_ref, cfg["flags"],
                workload=str(s.settings.workload_file),
                timeout_s=s.settings.benchmark_timeout_s,
                bin_dir=bin_dir,
                gguf_filename=gguf_filename,
            )
        if weights is None:
            cfg["fit"] = None
        else:
            cfg["fit"] = config_fit(
                server_id, cfg["flags"], float(weights), vram_gb,
                float(payload.get("ram_gb", 0.0)), payload.get("model_arch"),
            )
    return {"configs": configs}


def _rebuild_bench_command(s: AppState, cfg: dict, repo_id: str) -> None:
    """Re-derive the executed commands from the user's edited serving command so
    edits to the config bank actually take effect at run time. speed-bench runs
    need both a server command (llama-server) and a client command
    (speed_bench.py); llama-bench/vllm/sglang keep the single bench command."""
    if not cfg.get("server_id"):
        return
    if cfg.get("bench_tool") == "speed-bench":
        bin_dir = str(s.settings.llama_cpp_bin_dir) if s.settings.llama_cpp_bin_dir else None
        cfg["server_command"] = build_server_command(cfg.get("serving_command", ""), bin_dir)
        script = resolve_speed_bench_script(bin_dir, configured=s.settings.speed_bench_script)
        if not script:
            cfg["bench_command"] = []
            cfg["bench_error"] = (
                "speed-bench is not available: could not locate speed_bench.py next to llama-server. "
                "Set LLMBENCH_SPEED_BENCH_SCRIPT or install llama.cpp with the speed-bench tool.")
            return
        cfg["bench_command"] = build_speed_bench_command(
            script, osl=s.settings.speed_bench_osl,
            output=str(s.settings.data_dir / "speed-bench.json"))
        return
    flags = parse_serving_command(cfg.get("server_id", ""), cfg.get("serving_command", ""))
    if not flags:
        flags = cfg.get("flags") or {}
    if not flags:
        return
    model_ref, gguf_filename = model_ref_from_flags(cfg["server_id"], flags, repo_id)
    cfg["bench_command"] = build_bench_command(
        cfg["server_id"], model_ref, flags,
        workload=str(s.settings.workload_file),
        timeout_s=s.settings.benchmark_timeout_s,
        bin_dir=str(s.settings.llama_cpp_bin_dir) if s.settings.llama_cpp_bin_dir else None,
        gguf_filename=gguf_filename,
    )


@router.post("/benchmarks")
async def start_run(payload: dict):
    s = _require_state()
    with s._state_lock:
        if s._job_active:
            raise HTTPException(409, "A benchmark is already running")
    repo_id = payload["repo_id"]
    configs = payload.get("configs", [])
    for cfg in configs:
        _rebuild_bench_command(s, cfg, repo_id)
        if cfg.get("bench_error"):
            raise HTTPException(422, cfg["bench_error"])
    pause = bool(payload.get("pause", True))
    run_id = db_mod.create_run(s.conn, repo_id, len(configs))
    with s._state_lock:
        s._job_active = True
    asyncio.create_task(_run_job(s, run_id, configs, pause=pause))
    return {"run_id": run_id}


@router.post("/benchmarks/continue")
async def continue_run(payload: dict):
    s = _require_state()
    if s._continue_queue is None or s._active_run_id is None:
        raise HTTPException(409, "No benchmark is waiting for input")
    if payload.get("run_id") != s._active_run_id:
        raise HTTPException(409, "Run is not waiting for input")
    await s._continue_queue.put("continue")
    return {"ok": True}


async def _run_job(s: AppState, run_id: int, configs: list[dict], pause: bool = True):
    s._continue_queue = None
    s._active_run_id = run_id
    try:
        async with s.lock:
            try:
                db_mod.set_run_status(s.conn, run_id, "running")
                await broadcast(s, {"type": "run_started", "run_id": run_id, "total": len(configs)})
                status = "completed"
                for i, cfg in enumerate(configs):
                    await broadcast(s, {"type": "config_start", "run_id": run_id, "index": i,
                                        "total": len(configs), "config": cfg})
                    if cfg.get("bench_tool") == "speed-bench":
                        runner = benchmark_mod.SpeedBenchRunner(
                            server_command=cfg.get("server_command", []),
                            bench_command=cfg.get("bench_command", []),
                            timeout_s=s.settings.speed_bench_timeout_s,
                            startup_timeout_s=s.settings.speed_bench_timeout_s,
                            output_dir=s.settings.data_dir,
                        )
                    else:
                        runner = benchmark_mod.BenchmarkRunner(
                            server_id=cfg["server_id"],
                            bench_command=cfg["bench_command"],
                            timeout_s=s.settings.benchmark_timeout_s,
                        )
                    s.runner = runner

                    async def on_output(kind: str, text: str, _i: int = i) -> None:
                        await broadcast(s, {"type": "bench_log", "run_id": run_id, "index": _i,
                                            "kind": kind, "text": text})

                    result = await runner.run(on_output=on_output)
                    s.runner = None
                    cfg_id = db_mod.create_config(
                        s.conn, run_id, cfg["server_id"], _coerce_model_id(cfg.get("model_id")),
                        cfg["flags"], cfg["serving_command"], " ".join(cfg["bench_command"]),
                    )
                    db_mod.save_result(s.conn, cfg_id, result["prompt_processing_tps"],
                                       result["decode_tps"], result["duration_s"],
                                       result["output"], result["status"])
                    await broadcast(s, {"type": "config_done", "run_id": run_id, "index": i,
                                        "result": result})
                    if result["status"] == "aborted":
                        status = "aborted"
                        break
                    if pause:
                        wait_queue: asyncio.Queue = asyncio.Queue()
                        s._continue_queue = wait_queue
                        await broadcast(s, {"type": "config_wait", "run_id": run_id, "index": i})
                        await _await_continue(s, wait_queue)
                        s._continue_queue = None
                db_mod.set_run_status(s.conn, run_id, status)
                await broadcast(s, {"type": "run_done", "run_id": run_id, "status": status})
            except Exception:
                logger.exception("run %s failed", run_id)
                db_mod.set_run_status(s.conn, run_id, "failed")
                await broadcast(s, {"type": "run_done", "run_id": run_id, "status": "failed"})
    finally:
        s.runner = None
        s._continue_queue = None
        s._active_run_id = None
        with s._state_lock:
            s._job_active = False


async def _await_continue(s: AppState, queue: asyncio.Queue | None) -> None:
    if queue is None:
        return
    empty_for = 0.0
    while True:
        if not queue.empty():
            queue.get_nowait()
            return
        if len(s._ws_clients) == 0:
            empty_for += 0.2
            if empty_for >= AUTO_ADVANCE_GRACE_S:
                return
        else:
            empty_for = 0.0
        await asyncio.sleep(0.2)


def _coerce_model_id(raw) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@router.get("/benchmarks")
async def runs():
    s = _require_state()
    return {"runs": db_mod.list_runs(s.conn)}


@router.get("/benchmarks/{run_id}")
async def run_detail(run_id: int):
    s = _require_state()
    run = db_mod.get_run(s.conn, run_id)
    return {
        "status": run["status"] if run else None,
        "total": run["requested_n"] if run else 0,
        "results": db_mod.get_results_for_run(s.conn, run_id),
    }


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    s = _require_state()
    await ws.accept()
    s._ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        s._ws_clients.discard(ws)
