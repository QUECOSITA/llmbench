import asyncio
import logging
import shutil
from pathlib import Path

from app import db as db_mod
from app.hf import hf_bin
from app.readme_parser import detect_serving_programs, top_serving_program

logger = logging.getLogger(__name__)

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


_NON_GGUF_WEIGHT_SUFFIXES = (".safetensors", ".bin")


def _snapshot_has_non_gguf_weights(snap: Path) -> bool:
    """True when the snapshot still holds model weights other than .gguf
    (e.g. an unrelated `hf download`), which must never be wiped."""
    snaps_dir = snap / "snapshots"
    if not snaps_dir.is_dir():
        return False
    for ref in snaps_dir.iterdir():
        if ref.is_dir():
            for p in ref.rglob("*"):
                if p.is_file() and p.suffix in _NON_GGUF_WEIGHT_SUFFIXES:
                    return True
    return False


def _readme_in_snapshot(snap: Path) -> str | None:
    snaps_dir = snap / "snapshots"
    if not snaps_dir.is_dir():
        return None
    for ref in sorted(snaps_dir.iterdir()):
        if ref.is_dir():
            p = ref / "README.md"
            if p.is_file():
                return p.read_text(errors="replace")
    return None


def detect_server_from_snapshot(snap: Path, has_gguf: bool) -> str | None:
    readme = _readme_in_snapshot(snap)
    if readme is not None:
        return top_serving_program(detect_serving_programs(readme, has_gguf=has_gguf))
    if has_gguf:
        return "llama.cpp"
    return None


def _set_downloaded_servers(conn, repo_id: str, allowed: tuple[str, ...]) -> None:
    """Downgrade any other 'downloaded' rows for a repo to 'missing'."""
    for m in db_mod.list_models(conn):
        if m["repo_id"] != repo_id or m["server_id"] in allowed:
            continue
        if m["status"] == "downloaded":
            db_mod.upsert_model(conn, repo_id=m["repo_id"], server_id=m["server_id"],
                                format=m["format"], local_path=m["local_path"], status="missing")


def reconcile_models(conn, settings) -> None:
    """Scan the HF cache and sync the models table to what exists on disk,
    keeping llama.cpp as the only serving server. Never downgrades rows when
    detection fails — that preserves existing data."""
    cache_root = _hf_cache_root(settings)
    for repo_id, snap in scan_hf_cache(cache_root).items():
        ggufs = _ggufs_in_snapshot(snap)
        detected = detect_server_from_snapshot(snap, has_gguf=bool(ggufs))
        if detected is None:
            continue
        if detected == "llama.cpp" and ggufs:
            for g in {g.name: g for g in ggufs}.values():
                db_mod.upsert_model(conn, repo_id, "llama.cpp", "hf", str(g),
                                    "downloaded", gguf_filename=g.name, size_bytes=g.stat().st_size)
        _set_downloaded_servers(conn, repo_id, ("llama.cpp",))

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
    cmd = [hf_bin() or "hf", "cache", "rm", f"hf://models/{repo_id}", "-y"]
    if cache_dir:
        cmd += ["--cache-dir", cache_dir]
    return cmd


async def _rm_cache_repo(settings, repo_id: str, snap: Path, strict: bool) -> None:
    """Delete a repo's whole HF cache entry. Runs ``hf cache rm`` when the CLI
    is available (strict cleaning of blobs/refs), then removes any leftover
    directory.

    strict=True (whole-repo removal): a CLI failure raises RuntimeError and the
    entry is always removed. strict=False (last-file cleanup): a CLI failure is
    logged, not raised, and the rmtree is skipped if a concurrent download
    repopulated the snapshot with a .gguf while the CLI was running."""
    if hf_bin() is not None:
        cache_dir = str(settings.hf_cache_dir) if settings.hf_cache_dir else None
        proc = await asyncio.create_subprocess_exec(
            *rm_command(repo_id, cache_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            detail = out.decode(errors="replace").strip()
            if strict:
                raise RuntimeError(f"hf cache rm failed: {detail}")
            logger.warning("hf cache rm failed for %s (ignored): %s", repo_id, detail)
    if strict or not _ggufs_in_snapshot(snap):
        if snap.exists():
            shutil.rmtree(snap)


async def remove_gguf_file(conn, settings, repo_id: str, server_id: str, gguf_filename: str) -> None:
    rows = [r for r in db_mod.get_models(conn, repo_id, server_id)
            if r["gguf_filename"] == gguf_filename]
    if not rows:
        return
    p = Path(rows[0]["local_path"] or "")
    if p.suffix == ".gguf" and (
        _path_under(p, settings.resolved_gguf_dir) or _path_under(p, _hf_cache_root(settings))
    ) and p.exists():
        p.unlink()
    db_mod.delete_model_row(conn, repo_id, server_id, gguf_filename)

    # If the repo's HF cache entry no longer holds any .gguf, drop the whole
    # entry (README/refs/blobs leftovers included) so `hf cache list` stops
    # showing it — even when the removed file lived in the local gguf_dir.
    # Safety: never wipe an entry that still holds non-gguf weights, or whose
    # layout we can't inspect (no snapshots/ dir).
    snap = snapshot_dir_for(settings, repo_id)
    if (snap.exists()
            and (snap / "snapshots").is_dir()
            and not _ggufs_in_snapshot(snap)
            and not _snapshot_has_non_gguf_weights(snap)):
        await _rm_cache_repo(settings, repo_id, snap, strict=False)


async def remove_model(conn, settings, repo_id: str) -> None:
    rows = [r for r in db_mod.list_models(conn) if r["repo_id"] == repo_id]
    if not rows:
        return

    snap = snapshot_dir_for(settings, repo_id)
    if snap.exists():
        await _rm_cache_repo(settings, repo_id, snap, strict=True)
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
