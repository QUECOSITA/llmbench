import asyncio
import threading

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app import benchmark as benchmark_mod
from app import db as db_mod
from app.config import Settings
from app.flags import build_serving_command, generate_configs
from app.hardware import detect_hardware
from app.hf import HfClient, InvalidModelInput, normalize_input
from app.readme_parser import detect_serving_programs, extract_flags, top_serving_program
from app.servers import detect_binaries

router = APIRouter(prefix="/api")


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.conn = db_mod.init_db(settings.data_dir / "llmbench.db")
        self.lock = asyncio.Lock()
        self.runner: benchmark_mod.BenchmarkRunner | None = None
        self._ws_clients: set[WebSocket] = set()
        self._state_lock = threading.Lock()
        self._job_active = False


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
    return {"readiness": detect_binaries(), "hardware": detect_hardware()}


@router.post("/models/analyze")
async def analyze(payload: dict):
    s = _require_state()
    raw = payload.get("input")
    if raw is None:
        raise HTTPException(422, "Missing required field 'input'.")
    try:
        repo_id = normalize_input(raw)
    except InvalidModelInput as e:
        raise HTTPException(422, str(e))
    try:
        readme, files = _hf.fetch_repo(repo_id)
    except Exception as e:
        raise HTTPException(404, f"Could not fetch repo {repo_id}: {e}")
    gguf = _hf.gguf_files(files)
    scores = detect_serving_programs(readme, has_gguf=bool(gguf))
    detected = top_serving_program(scores)
    flags = extract_flags(readme, [detected or "vllm"])
    weights = _hf.weights_size_bytes(files)
    return {
        "repo_id": repo_id,
        "detected_server": detected,
        "server_scores": scores,
        "readme_flags": flags,
        "gguf_files": gguf,
        "weights_bytes": weights,
        "downloaded": _model_status(s, repo_id),
    }


def _model_status(s: AppState, repo_id: str) -> dict[str, bool]:
    out = {}
    for server_id in ("llama.cpp", "vllm", "sglang"):
        m = db_mod.get_model(s.conn, repo_id, server_id)
        out[server_id] = bool(m and m["status"] == "downloaded")
    return out


@router.get("/models")
async def models():
    s = _require_state()
    return {"models": db_mod.list_models(s.conn)}


@router.delete("/models/{server_id}/{model_ref}")
async def delete_model(server_id: str, model_ref: str):
    s = _require_state()
    db_mod.upsert_model(s.conn, repo_id=model_ref, server_id=server_id, format="hf",
                        local_path="", status="missing")
    return {"ok": True}


@router.post("/configs/generate")
async def generate(payload: dict):
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
    try:
        configs = generate_configs(
            server_id=server_id,
            readme_flags=payload.get("readme_flags", {}),
            n=n,
            vram_gb=float(payload.get("vram_gb", 24.0)),
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    for cfg in configs:
        cfg["serving_command"] = build_serving_command(
            server_id, repo_id, cfg["flags"],
            gguf_path=payload.get("gguf_path"),
        )
    return {"configs": configs}


@router.post("/benchmarks")
async def start_run(payload: dict):
    s = _require_state()
    with s._state_lock:
        if s._job_active:
            raise HTTPException(409, "A benchmark is already running")
    repo_id = payload["repo_id"]
    configs = payload.get("configs", [])
    run_id = db_mod.create_run(s.conn, repo_id, len(configs))
    with s._state_lock:
        s._job_active = True
    asyncio.create_task(_run_job(s, run_id, configs))
    return {"run_id": run_id}


async def _run_job(s: AppState, run_id: int, configs: list[dict]):
    try:
        async with s.lock:
            try:
                db_mod.set_run_status(s.conn, run_id, "running")
                await broadcast(s, {"type": "run_started", "run_id": run_id, "total": len(configs)})
                status = "completed"
                for i, cfg in enumerate(configs):
                    await broadcast(s, {"type": "config_start", "run_id": run_id, "index": i,
                                        "total": len(configs), "config": cfg})
                    runner = benchmark_mod.BenchmarkRunner(
                        server_id=cfg["server_id"],
                        bench_command=cfg["bench_command"],
                        timeout_s=s.settings.benchmark_timeout_s,
                    )
                    s.runner = runner
                    result = await runner.run()
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
                db_mod.set_run_status(s.conn, run_id, status)
                await broadcast(s, {"type": "run_done", "run_id": run_id, "status": status})
            except Exception:
                db_mod.set_run_status(s.conn, run_id, "failed")
                await broadcast(s, {"type": "run_done", "run_id": run_id, "status": "failed"})
    finally:
        s.runner = None
        with s._state_lock:
            s._job_active = False


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
    return {"results": db_mod.get_results_for_run(s.conn, run_id)}


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
