import asyncio
import logging
import os
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
from app.hf import HfClient, InvalidModelInput, hf_bin, normalize_input, parse_input
from app.pty_stream import DownloadPty, open_download_pty
from app.readme_parser import (detect_serving_programs, extract_flags,
                               has_serving_command, top_serving_program)
from app.servers import (build_bench_command, build_server_command, build_speed_bench_command,
                         detect_binaries, ensure_speed_bench_script, is_spec_decoding_model,
                         model_ref_from_flags, parse_serving_command,
                         serving_command_display_flags,
                         speed_bench_deps_available, parse_speed_bench_flags,
                         speed_bench_default_flags, validate_speed_bench_flags,
                         SPEED_BENCH_BENCHES, SPEED_BENCH_CATEGORIES)
from app.spawn import spawn_env

router = APIRouter(prefix="/api")

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Structured API error: keeps FastAPI's `detail` string while adding
    machine-readable context the frontend can render alongside the message."""

    def __init__(self, status_code: int, message: str, context: dict | None = None):
        self.status_code = status_code
        self.message = message
        self.context = context or {}
        super().__init__(message)


KNOWN_SERVERS = ("llama.cpp",)


def _download_command(repo_id: str, server_id: str, gguf_filenames: list[str] | None = None,
                      cache_dir: str | None = None) -> list[str]:
    cmd = [hf_bin() or "hf", "download", "--format", "human", repo_id]
    for name in gguf_filenames or ["*.gguf"]:
        cmd += ["--include", name]
    cmd += ["--include", "README.md"]
    if cache_dir:
        cmd += ["--cache-dir", cache_dir]
    return cmd


def _prune_command(cache_dir: str | None = None) -> list[str]:
    cmd = [hf_bin() or "hf", "cache", "prune", "--format", "human"]
    if cache_dir:
        cmd += ["--cache-dir", cache_dir]
    return cmd


async def _force_kill_after(pty, delay: float) -> None:
    await asyncio.sleep(delay)
    pty.close()


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
        self._download_pty: DownloadPty | None = None
        self._download_cancelled = False
        self._prune_proc: asyncio.subprocess.Process | None = None
        self._prune_answer: asyncio.Queue[str] | None = None
        self._active_run_id: int | None = None
        self._cancel_requested = False


state: AppState | None = None
_hf = HfClient()


def init_state(settings: Settings) -> AppState:
    global state
    state = AppState(settings)
    db_mod.fail_stale_runs(state.conn)
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
    return {"readiness": detect_binaries(bin_dir, data_dir=str(s.settings.data_dir)),
            "hardware": detect_hardware()}


@router.get("/speed-bench/info")
async def speed_bench_info():
    return {
        "benches": list(SPEED_BENCH_BENCHES),
        "categories": {bench: list(cats) for bench, cats in SPEED_BENCH_CATEGORIES.items()},
    }


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
    readme_flags_by_server = {
        "llama.cpp": extract_flags(readme, ["llama.cpp"]),
    }
    flags = readme_flags_by_server.get(detected) if detected else {}
    weights = _hf.weights_size_bytes(files)
    hw = detect_hardware()
    arch = None
    if any(f.get("path", "").lower() == "config.json" for f in files):
        try:
            arch = arch_from_config(_hf.fetch_config(repo_id))
        except Exception:
            arch = None
    verdict = fit_verdict(weights, hw["gpu_vram_gb"], hw["ram_total_gb"], arch=arch)
    for g in gguf:
        g["fit"] = fit_verdict(g["size"], hw["gpu_vram_gb"], hw["ram_total_gb"], arch=arch)
    first_gguf_basename = os.path.basename(gguf[0]["path"]) if gguf else None
    auto_bench_tool = (
        "speed-bench"
        if is_spec_decoding_model(repo_id, first_gguf_basename, flags)
        else "llama-bench"
    )
    return {
        "repo_id": repo_id,
        "detected_server": detected,
        "server_scores": scores,
        "readme_has_serving_command": has_serving_command(readme, "llama.cpp"),
        "auto_bench_tool": auto_bench_tool,
        "readme_flags": flags,
        "readme_flags_by_server": readme_flags_by_server,
        "gguf_files": gguf,
        "weights_bytes": weights,
        "downloaded": _model_status(s, repo_id),
        "downloaded_ggufs": _model_ggufs(s, repo_id),
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
    for server_id in ("llama.cpp",):
        out[server_id] = bool(db_mod.get_models(s.conn, repo_id, server_id, status="downloaded"))
    return out


def _model_ggufs(s: AppState, repo_id: str) -> dict[str, list[str]]:
    out = {}
    for server_id in ("llama.cpp",):
        out[server_id] = [
            m["gguf_filename"] for m in db_mod.get_models(s.conn, repo_id, server_id, status="downloaded")
            if m["gguf_filename"]
        ]
    return out


def _hf_snapshot_dir(settings: Settings, repo_id: str) -> Path:
    return sync_mod.snapshot_dir_for(settings, repo_id)


def _resolve_download_paths(s: AppState, repo_id: str, server_id: str,
                            gguf_filenames: list[str] | None) -> list[tuple[str, str, int]]:
    gguf_dir = s.settings.resolved_gguf_dir
    snapshot = _hf_snapshot_dir(s.settings, repo_id)
    snapshot_ggufs = {g.name: g for g in sync_mod._ggufs_in_snapshot(snapshot)}
    candidates: list[Path] = []
    if gguf_filenames:
        for name in gguf_filenames:
            p = gguf_dir / name
            if not p.exists():
                p = snapshot_ggufs.get(name)
            if p is not None:
                candidates.append(p)
    else:
        candidates = sorted(snapshot_ggufs.values(), key=lambda p: p.name)
        candidates += [p for p in sorted(gguf_dir.glob("*.gguf"))
                       if p.name not in snapshot_ggufs]
    return [(str(p), p.name, p.stat().st_size) for p in candidates if p.exists()]


def _resolve_download_path(s: AppState, repo_id: str, server_id: str,
                           gguf_filename: str | None) -> tuple[str | None, str | None, int | None]:
    """Single-file convenience for callers that only need one resolved gguf.

    The generate endpoint still relies on this wrapper.
    Note: when both gguf_dir and the HF snapshot hold ggufs, this returns the
    smallest-named snapshot file first — interim behavior to be revisited when
    generate migrates to per-file selection."""
    results = _resolve_download_paths(s, repo_id, server_id,
                                      [gguf_filename] if gguf_filename else None)
    return results[0] if results else (None, None, None)


async def _download_job(s: AppState, repo_id: str, server_id: str,
                        cmd: list[str], gguf_filenames: list[str] | None):
    pty = None
    try:
        await broadcast(s, {"type": "download_started", "server_id": server_id,
                            "repo_id": repo_id, "command": " ".join(cmd)})
        pty = open_download_pty(cmd, env=spawn_env())
        await pty.spawn()
        s._download_pty = pty
        async for kind, text in pty.read_events():
            if kind == "line":
                await broadcast(s, {"type": "download_log", "server_id": server_id,
                                    "repo_id": repo_id, "line": text})
            else:
                await broadcast(s, {"type": "download_progress", "server_id": server_id,
                                    "repo_id": repo_id, "line": text})
        rc = await pty.wait()
        s._download_pty = None
        if s._download_cancelled:
            await broadcast(s, {"type": "download_cancelled", "server_id": server_id,
                                "repo_id": repo_id})
            await _prune_job(s, repo_id, server_id)
            return
        if rc != 0:
            db_mod.upsert_model(s.conn, repo_id=repo_id, server_id=server_id,
                                format="hf", local_path="", status="missing")
            await broadcast(s, {"type": "download_error", "server_id": server_id,
                                "repo_id": repo_id,
                                "message": f"download exited with code {rc} (see the download log for details)"})
            return
        local = _resolve_download_paths(s, repo_id, server_id, gguf_filenames)
        if not local:
            db_mod.upsert_model(s.conn, repo_id=repo_id, server_id=server_id,
                                format="hf", local_path="", status="missing")
            await broadcast(s, {"type": "download_error", "server_id": server_id,
                                "repo_id": repo_id, "message": "download finished but no artifact was found"})
            return
        for path, name, size in local:
            db_mod.upsert_model(s.conn, repo_id=repo_id, server_id=server_id, format="hf",
                                local_path=path, status="downloaded",
                                gguf_filename=name, size_bytes=size,
                                downloaded_at=datetime.now(timezone.utc).isoformat())
        await broadcast(s, {"type": "download_done", "server_id": server_id,
                            "repo_id": repo_id, "status": "downloaded", "local_path": local[0][0]})
    except Exception as e:
        await broadcast(s, {"type": "download_error", "server_id": server_id,
                            "repo_id": repo_id, "message": str(e)})
    finally:
        if pty is not None:
            pty.close()
        s._download_pty = None
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
        repo_id, file_path = parse_input(model_ref)
    except InvalidModelInput as e:
        raise HTTPException(422, str(e))
    try:
        if file_path:
            await sync_mod.remove_gguf_file(s.conn, s.settings, repo_id, "llama.cpp", file_path)
        else:
            await sync_mod.remove_model(s.conn, s.settings, repo_id)
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
    gguf_filenames = payload.get("gguf_filenames")
    if gguf_filenames is None:
        single = payload.get("gguf_filename")
        gguf_filenames = [single] if single else None
    if gguf_filenames is not None:
        if not isinstance(gguf_filenames, list) or not gguf_filenames:
            raise HTTPException(422, "'gguf_filenames' must be a non-empty list of .gguf filenames.")
        for name in gguf_filenames:
            if not isinstance(name, str) or not name or os.path.basename(name) != name:
                raise HTTPException(422, "'gguf_filenames' entries must be plain .gguf filenames.")
    cmd = _download_command(repo_id, server_id, gguf_filenames, cache_dir=cache_dir)
    if hf_bin() is None:
        raise HTTPException(400, f"HF CLI not found. Run: {' '.join(cmd)}")
    with s._state_lock:
        if s._download_active:
            raise HTTPException(409, "A download is already running")
        s._download_active = True
    try:
        asyncio.create_task(_download_job(s, repo_id, server_id, cmd, gguf_filenames))
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
    pty = s._download_pty
    if pty is not None:
        pty.cancel()
        asyncio.create_task(_force_kill_after(pty, 5.0))
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
    if not isinstance(repo_id, str) or "/" not in repo_id:
        raise HTTPException(422, "'repo_id' must be 'org/model'.")
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
    if resolved_gguf is not None and not isinstance(resolved_gguf, str):
        raise HTTPException(422, "gguf_path must be a string.")
    gguf_filename = os.path.basename(resolved_gguf) if resolved_gguf else None
    if resolved_gguf is None and server_id == "llama.cpp":
        local_path, name, size = _resolve_download_path(s, repo_id, "llama.cpp", None)
        resolved_gguf = local_path
        gguf_filename = name
        if size is not None:
            weights = size
    elif resolved_gguf:
        resolved = os.path.realpath(resolved_gguf)
        gguf_dir = os.path.realpath(str(s.settings.resolved_gguf_dir))
        snap_dir = os.path.realpath(str(_hf_snapshot_dir(s.settings, repo_id)))
        if resolved.startswith(gguf_dir + os.sep) or resolved.startswith(snap_dir + os.sep):
            p = Path(resolved)
            if not (p.suffix == ".gguf" and p.exists()):
                raise HTTPException(
                    422,
                    "gguf_path must be a .gguf file under the models/gguf directory "
                    "or the HF cache for this repo",
                )
            try:
                weights = p.stat().st_size
            except OSError:
                pass
        else:
            raise HTTPException(
                422,
                "gguf_path must be a .gguf file under the models/gguf directory "
                "or the HF cache for this repo",
            )
    bin_dir = str(s.settings.llama_cpp_bin_dir) if s.settings.llama_cpp_bin_dir else None
    requested_bench_tool = payload.get("bench_tool")
    if requested_bench_tool not in (None, "llama-bench", "speed-bench"):
        raise HTTPException(422, "'bench_tool' must be 'llama-bench' or 'speed-bench'.")
    uses_speed_bench = (
        server_id == "llama.cpp"
        and (
            requested_bench_tool == "speed-bench"
            if requested_bench_tool is not None
            else is_spec_decoding_model(repo_id, gguf_filename, payload.get("readme_flags", {}))
        )
    )
    for cfg in configs:
        cfg["serving_command"] = build_serving_command(
            server_id, repo_id, cfg["flags"],
            gguf_filename=gguf_filename,
            gguf_path=resolved_gguf,
        )
        cfg["bench_tool"] = "speed-bench" if uses_speed_bench else "llama-bench"
        if uses_speed_bench:
            script = await asyncio.to_thread(
                ensure_speed_bench_script,
                bin_dir,
                configured=s.settings.speed_bench_script,
                data_dir=str(s.settings.data_dir),
            )
            if script and speed_bench_deps_available():
                flags_text = speed_bench_default_flags(s.settings.speed_bench_osl)
                cfg["bench_flags"] = flags_text
                cfg["bench_command"] = build_speed_bench_command(
                    script, parse_speed_bench_flags(flags_text),
                    output=str(s.settings.data_dir / "speed-bench.json"))
            else:
                cfg["bench_command"] = []
                cfg["bench_error"] = _speed_bench_error(script)
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


def _speed_bench_error(script: str | None) -> str:
    if script:
        return ("speed-bench is not available: speed_bench.py requires 'requests', 'datasets', 'tqdm' "
                "in the backend venv. Install them with `pip install -e '.[speed-bench]'`.")
    return ("speed-bench is not available: could not locate speed_bench.py and the automatic "
            "download into the app data dir failed or is pending. Check the backend log, or set "
            "LLMBENCH_SPEED_BENCH_SCRIPT to point at a speed_bench.py.")


def _rebuild_bench_command(s: AppState, cfg: dict, repo_id: str) -> None:
    """Re-derive the executed commands from the user's edited serving command so
    edits to the config bank actually take effect at run time. speed-bench runs
    need both a server command (llama-server) and a client command
    (speed_bench.py); llama-bench keeps the single bench command."""
    if not cfg.get("server_id"):
        return
    if cfg.get("bench_tool") == "speed-bench":
        bin_dir = str(s.settings.llama_cpp_bin_dir) if s.settings.llama_cpp_bin_dir else None
        try:
            cfg["server_command"] = build_server_command(cfg.get("serving_command", ""), bin_dir)
        except ValueError as exc:
            cfg["server_command"] = []
            cfg["bench_command"] = []
            cfg["bench_error"] = f"invalid serving command: {exc}"
            return
        script = ensure_speed_bench_script(
            bin_dir,
            configured=s.settings.speed_bench_script,
            data_dir=str(s.settings.data_dir),
        )
        if not (script and speed_bench_deps_available()):
            cfg["bench_command"] = []
            cfg["bench_error"] = _speed_bench_error(script)
            return
        flags_text = cfg.get("bench_flags") or speed_bench_default_flags(s.settings.speed_bench_osl)
        flags = parse_speed_bench_flags(flags_text)
        error = validate_speed_bench_flags(flags)
        if error:
            cfg["bench_command"] = []
            cfg["bench_error"] = error
            return
        cfg["bench_command"] = build_speed_bench_command(
            script, flags, output=str(s.settings.data_dir / "speed-bench.json"))
        cfg["flags"] = serving_command_display_flags(
            cfg["server_id"], cfg.get("serving_command", "")) or cfg.get("flags", {})
        cfg.pop("bench_error", None)
        return
    try:
        flags = parse_serving_command(cfg.get("server_id", ""), cfg.get("serving_command", ""))
    except ValueError as exc:
        cfg["bench_command"] = []
        cfg["bench_error"] = f"invalid serving command: {exc}"
        return
    if flags:
        cfg["flags"] = serving_command_display_flags(cfg["server_id"], cfg.get("serving_command", ""))
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
    cfg.pop("bench_error", None)


@router.post("/benchmarks")
async def start_run(payload: dict):
    s = _require_state()
    with s._state_lock:
        if s._job_active:
            active = db_mod.get_active_run(s.conn)
            raise ApiError(
                409, "A benchmark is already running",
                context={"active_run": active or {"id": s._active_run_id}})
    repo_id = payload["repo_id"]
    configs = payload.get("configs", [])
    for cfg in configs:
        _rebuild_bench_command(s, cfg, repo_id)
        if cfg.get("bench_error"):
            raise ApiError(422, cfg["bench_error"],
                           context={"config_index": configs.index(cfg),
                                    "server_id": cfg.get("server_id"),
                                    "bench_tool": cfg.get("bench_tool")})
    run_id = db_mod.create_run(s.conn, repo_id, len(configs))
    with s._state_lock:
        s._job_active = True
        s._cancel_requested = False
    asyncio.create_task(_run_job(s, run_id, configs))
    return {"run_id": run_id}


@router.post("/benchmarks/cancel")
async def cancel_run():
    s = _require_state()
    with s._state_lock:
        if not s._job_active or s._active_run_id is None:
            raise HTTPException(409, "No benchmark is running")
        s._cancel_requested = True
    runner = s.runner
    if runner is not None:
        runner.abort()
    return {"ok": True}


async def _run_job(s: AppState, run_id: int, configs: list[dict]):
    s._active_run_id = run_id
    try:
        async with s.lock:
            try:
                db_mod.set_run_status(s.conn, run_id, "running")
                await broadcast(s, {"type": "run_started", "run_id": run_id, "total": len(configs)})
                status = "completed"
                for i, cfg in enumerate(configs):
                    if s._cancel_requested:
                        status = "aborted"
                        break
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
                                        "result": result, "flag_conf": cfg.get("flags", {})})
                    if result["status"] == "aborted":
                        status = "aborted"
                        break
                    if result["status"] == "failed":
                        status = "failed"
                db_mod.set_run_status(s.conn, run_id, status)
                await broadcast(s, {"type": "run_done", "run_id": run_id, "status": status})
            except Exception:
                logger.exception("run %s failed", run_id)
                db_mod.set_run_status(s.conn, run_id, "failed")
                await broadcast(s, {"type": "run_done", "run_id": run_id, "status": "failed"})
    finally:
        s.runner = None
        s._active_run_id = None
        with s._state_lock:
            s._job_active = False
            s._cancel_requested = False


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


@router.delete("/benchmarks")
async def clear_history():
    s = _require_state()
    with s._state_lock:
        if s._job_active:
            active = db_mod.get_active_run(s.conn)
            raise ApiError(
                409, "A benchmark is already running",
                context={"active_run": active or {"id": s._active_run_id}})
    db_mod.clear_history(s.conn)
    for p in s.settings.data_dir.glob("speed-bench-*.json"):
        try:
            p.unlink()
        except OSError:
            pass
    return {"ok": True}


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
