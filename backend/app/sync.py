import asyncio
import shutil
from pathlib import Path

from app import db as db_mod

_CACHE_PREFIX = "models--"


def _hf_cache_root(settings) -> Path:
    return settings.hf_cache_dir or (Path.home() / ".cache" / "huggingface" / "hub")


def snapshot_dir_for(settings, repo_id: str) -> Path:
    org, name = repo_id.split("/", 1)
    return _hf_cache_root(settings) / f"{_CACHE_PREFIX}{org}--{name}"


def scan_hf_cache(cache_root: Path) -> dict[str, Path]:
    """Return {repo_id: snapshot_dir} for cache dirs that hold a real snapshot."""
    if not cache_root.is_dir():
        return {}
    found: dict[str, Path] = {}
    for snap in cache_root.glob(f"{_CACHE_PREFIX}*--*"):
        if not _snapshot_has_files(snap):
            continue
        repo_id = snap.name[len(_CACHE_PREFIX):].replace("--", "/", 1)
        found[repo_id] = snap
    return found


def _snapshot_has_files(snap: Path) -> bool:
    snaps_dir = snap / "snapshots"
    if not snaps_dir.is_dir():
        return False
    for ref in snaps_dir.iterdir():
        if ref.is_dir() and any(p.is_file() for p in ref.iterdir()):
            return True
    return False


def _ggufs_in_snapshot(snap: Path) -> list[Path]:
    out: list[Path] = []
    snaps_dir = snap / "snapshots"
    if not snaps_dir.is_dir():
        return out
    for ref in snaps_dir.iterdir():
        if ref.is_dir():
            out.extend(p for p in ref.rglob("*.gguf") if p.is_file())
    return out


def reconcile_models(conn, settings) -> None:
    """Scan the HF cache and sync the models table to what exists on disk."""
    cache_root = _hf_cache_root(settings)
    ggufs = _ggufs_in_snapshot(snapshot_dir_for(settings, "dummy")) if False else {}
    # llama.cpp-only: no vllm/sglang sync
    for m in db_mod.list_models(conn):
        if m["status"] != "downloaded":
            continue
        if not Path(m["local_path"] or "").exists():
            db_mod.upsert_model(conn, repo_id=m["repo_id"], server_id=m["server_id"],
                                format=m["format"], local_path=m["local_path"], status="missing")


def _path_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def rm_command(repo_id: str, cache_dir: str | None = None) -> list[str]:
    cmd = ["hf", "cache", "rm", f"hf://models/{repo_id}", "-y"]
    if cache_dir:
        cmd += ["--cache-dir", cache_dir]
    return cmd


async def remove_model(conn, settings, repo_id: str) -> None:
    rows = [r for r in db_mod.list_models(conn) if r["repo_id"] == repo_id]
    if not rows:
        return

    snap = snapshot_dir_for(settings, repo_id)
    if snap.exists():
        if shutil.which("hf") is not None:
            cache_dir = str(settings.hf_cache_dir) if settings.hf_cache_dir else None
            proc = await asyncio.create_subprocess_exec(
                *rm_command(repo_id, cache_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"hf cache rm failed: {out.decode(errors='replace').strip()}")
            if snap.exists():
                shutil.rmtree(snap)
        else:
            shutil.rmtree(snap)
    else:
        for r in rows:
            if r["server_id"] != "llama.cpp":
                continue
            p = Path(r["local_path"] or "")
            if p.suffix == ".gguf" and (
                _path_under(p, settings.resolved_gguf_dir) or _path_under(p, _hf_cache_root(settings))
            ) and p.exists():
                p.unlink()

    for r in rows:
        db_mod.delete_model(conn, repo_id, r["server_id"])