import asyncio
from pathlib import Path

import pytest

from app.config import Settings
from app.db import get_models, init_db, get_model, list_models, upsert_model
from app.sync import (_hf_cache_root, reconcile_models, remove_model, remove_gguf_file,
                      scan_hf_cache, snapshot_dir_for)


def _settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path, gguf_dir=tmp_path / "gguf",
                    hf_cache_dir=tmp_path / "hf", workload_file=tmp_path / "prompts.jsonl")


def _make_snapshot(settings: Settings, repo_id: str, ggufs: list[str] | None = None,
                   readme: str | None = None) -> Path:
    snap = snapshot_dir_for(settings, repo_id)
    snap_dir = snap / "snapshots" / "main"
    snap_dir.mkdir(parents=True)
    for g in ggufs or []:
        (snap_dir / g).write_bytes(b"x" * 100)
    if readme is not None:
        (snap_dir / "README.md").write_text(readme)
    return snap


def test_snapshot_dir_for_matches_hf_layout(tmp_path):
    settings = _settings(tmp_path)
    assert snapshot_dir_for(settings, "org/model") == tmp_path / "hf" / "models--org--model"


def test_scan_hf_cache_ignores_incomplete_snapshots(tmp_path):
    root = tmp_path / "hf"
    (root / "models--org--model" / ".cache").mkdir(parents=True)
    assert scan_hf_cache(root) == {}


def test_scan_hf_cache_finds_ready_snapshots(tmp_path):
    settings = _settings(tmp_path)
    _make_snapshot(settings, "org/model", ggufs=["model.gguf"])
    found = scan_hf_cache(settings.hf_cache_dir or tmp_path / "hf")
    assert found == {"org/model": snapshot_dir_for(settings, "org/model")}


def test_reconcile_readme_detects_llama_cpp(tmp_path):
    settings = _settings(tmp_path)
    _make_snapshot(settings, "org/model", ggufs=["model.Q4_K_M.gguf"],
                   readme="# model\n\nllama-server -m model.gguf\n")
    conn = init_db(tmp_path / "db.sqlite")

    reconcile_models(conn, settings)

    m = get_model(conn, "org/model", "llama.cpp")
    assert m and m["status"] == "downloaded"
    assert m["gguf_filename"] == "model.Q4_K_M.gguf"
    assert m["local_path"].endswith("model.Q4_K_M.gguf")
    for server_id in ("vllm", "sglang"):
        m = get_model(conn, "org/model", server_id)
        assert m is None or m["status"] != "downloaded"


def test_reconcile_downgrades_stale_all_server_rows(tmp_path):
    settings = _settings(tmp_path)
    snap = _make_snapshot(settings, "org/model", ggufs=["model.gguf"],
                          readme="# model\n\nllama-server -m model.gguf\n")
    conn = init_db(tmp_path / "db.sqlite")
    for server_id in ("llama.cpp", "vllm", "sglang"):
        upsert_model(conn, "org/model", server_id, "hf", str(snap), "downloaded")

    reconcile_models(conn, settings)

    assert get_model(conn, "org/model", "llama.cpp")["status"] == "downloaded"
    assert get_model(conn, "org/model", "vllm")["status"] == "missing"
    assert get_model(conn, "org/model", "sglang")["status"] == "missing"


def test_reconcile_keeps_existing_rows_when_readme_detects_none(tmp_path):
    settings = _settings(tmp_path)
    snap = _make_snapshot(settings, "org/model", readme="# model\n\nNo server mentioned.\n")
    conn = init_db(tmp_path / "db.sqlite")
    for server_id in ("llama.cpp", "vllm", "sglang"):
        upsert_model(conn, "org/model", server_id, "hf", str(snap), "downloaded")

    reconcile_models(conn, settings)

    for server_id in ("llama.cpp", "vllm", "sglang"):
        assert get_model(conn, "org/model", server_id)["status"] == "downloaded"


def test_reconcile_gguf_only_snapshot_without_readme_is_llama_cpp(tmp_path):
    settings = _settings(tmp_path)
    _make_snapshot(settings, "org/model", ggufs=["model.Q4_K_M.gguf"])
    conn = init_db(tmp_path / "db.sqlite")

    reconcile_models(conn, settings)

    m = get_model(conn, "org/model", "llama.cpp")
    assert m and m["status"] == "downloaded"
    assert m["gguf_filename"] == "model.Q4_K_M.gguf"
    assert m["local_path"].endswith("model.Q4_K_M.gguf")
    for server_id in ("vllm", "sglang"):
        m = get_model(conn, "org/model", server_id)
        assert m is None or m["status"] != "downloaded"


def test_reconcile_keeps_rows_when_no_readme_and_no_gguf(tmp_path):
    settings = _settings(tmp_path)
    snap = _make_snapshot(settings, "org/model")
    conn = init_db(tmp_path / "db.sqlite")
    upsert_model(conn, "org/model", "llama.cpp", "hf", str(snap), "downloaded")

    reconcile_models(conn, settings)

    assert get_model(conn, "org/model", "llama.cpp")["status"] == "downloaded"


def test_reconcile_marks_stale_rows_missing(tmp_path):
    settings = _settings(tmp_path)
    conn = init_db(tmp_path / "db.sqlite")
    upsert_model(conn, "org/model", "llama.cpp", "hf", str(tmp_path / "gone"), "downloaded")
    upsert_model(conn, "org/other", "llama.cpp", "hf", str(tmp_path / "gone.gguf"),
                 "downloaded", gguf_filename="gone.gguf")

    reconcile_models(conn, settings)

    assert get_model(conn, "org/model", "llama.cpp")["status"] == "missing"
    assert get_model(conn, "org/other", "llama.cpp")["status"] == "missing"


def test_reconcile_keeps_gguf_dir_row_when_file_present(tmp_path):
    settings = _settings(tmp_path)
    gguf = settings.resolved_gguf_dir / "model.gguf"
    gguf.parent.mkdir(parents=True)
    gguf.write_bytes(b"x" * 100)
    conn = init_db(tmp_path / "db.sqlite")
    upsert_model(conn, "org/model", "llama.cpp", "hf", str(gguf), "downloaded",
                 gguf_filename="model.gguf", size_bytes=100)

    reconcile_models(conn, settings)

    assert get_model(conn, "org/model", "llama.cpp")["status"] == "downloaded"


def test_remove_model_deletes_whole_repo_and_snapshot(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    snap = _make_snapshot(settings, "org/model")
    conn = init_db(tmp_path / "db.sqlite")
    upsert_model(conn, "org/model", "llama.cpp", "hf", str(snap), "downloaded")
    monkeypatch.setattr("app.sync.hf_bin", lambda: None)

    asyncio.run(remove_model(conn, settings, "org/model"))

    assert get_model(conn, "org/model", "llama.cpp") is None
    assert not snap.exists()


def test_remove_model_noop_when_repo_has_no_rows(tmp_path, monkeypatch):
    """remove_model on a repo with no DB rows must not delete anything."""
    settings = _settings(tmp_path)
    snap = _make_snapshot(settings, "org/untracked")
    conn = init_db(tmp_path / "db.sqlite")
    monkeypatch.setattr("app.sync.hf_bin", lambda: None)

    asyncio.run(remove_model(conn, settings, "org/untracked"))

    assert snap.exists()
    assert list_models(conn) == []


def test_remove_llama_deletes_gguf_file(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    gguf = settings.resolved_gguf_dir / "model.gguf"
    gguf.parent.mkdir(parents=True)
    gguf.write_bytes(b"x" * 100)
    conn = init_db(tmp_path / "db.sqlite")
    upsert_model(conn, "org/model", "llama.cpp", "hf", str(gguf), "downloaded",
                 gguf_filename="model.gguf")
    monkeypatch.setattr("app.sync.hf_bin", lambda: None)

    asyncio.run(remove_model(conn, settings, "org/model"))

    assert get_model(conn, "org/model", "llama.cpp") is None
    assert not gguf.exists()


class FakeRmProcess:
    def __init__(self, rc=0, out=b""):
        self._rc = rc
        self._out = out
        self.returncode = None

    async def communicate(self):
        self.returncode = self._rc
        return self._out, None


def test_remove_model_uses_hf_cache_rm_when_cli_present(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _make_snapshot(settings, "org/model")
    conn = init_db(tmp_path / "db.sqlite")
    upsert_model(conn, "org/model", "llama.cpp", "hf", str(snapshot_dir_for(settings, "org/model")), "downloaded")

    captured: dict = {}
    monkeypatch.setattr("app.sync.hf_bin", lambda: "/usr/bin/hf")

    async def fake_create(*cmd, **kw):
        captured["cmd"] = list(cmd)
        return FakeRmProcess(rc=0)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    async def run():
        await remove_model(conn, settings, "org/model")

    asyncio.run(run())

    assert captured["cmd"] == [
        "/usr/bin/hf", "cache", "rm", "hf://models/org/model", "-y",
        "--cache-dir", str(settings.hf_cache_dir),
    ]
    assert get_model(conn, "org/model", "llama.cpp") is None


def test_remove_model_hf_cache_rm_failure_keeps_rows(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _make_snapshot(settings, "org/model")
    conn = init_db(tmp_path / "db.sqlite")
    upsert_model(conn, "org/model", "llama.cpp", "hf", str(snapshot_dir_for(settings, "org/model")), "downloaded")

    monkeypatch.setattr("app.sync.hf_bin", lambda: "/usr/bin/hf")

    async def fake_create(*cmd, **kw):
        return FakeRmProcess(rc=1, out=b"repo not found")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    async def run():
        await remove_model(conn, settings, "org/model")

    with pytest.raises(RuntimeError, match="repo not found"):
        asyncio.run(run())
    assert get_model(conn, "org/model", "llama.cpp") is not None


def test_remove_model_falls_back_to_rmtree_when_cli_missing(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    snap = _make_snapshot(settings, "org/model")
    conn = init_db(tmp_path / "db.sqlite")
    upsert_model(conn, "org/model", "llama.cpp", "hf", str(snap), "downloaded")
    monkeypatch.setattr("app.sync.hf_bin", lambda: None)

    asyncio.run(remove_model(conn, settings, "org/model"))

    assert get_model(conn, "org/model", "llama.cpp") is None
    assert not snap.exists()


def test_remove_model_rmtree_when_cli_exits_zero_but_leaves_snapshot(tmp_path, monkeypatch):
    """hf cache rm can exit 0 without deleting (bare repo_id not matched); fall back to rmtree."""
    settings = _settings(tmp_path)
    snap = _make_snapshot(settings, "org/model")
    conn = init_db(tmp_path / "db.sqlite")
    upsert_model(conn, "org/model", "llama.cpp", "hf", str(snap), "downloaded")

    monkeypatch.setattr("app.sync.hf_bin", lambda: "/usr/bin/hf")

    async def fake_create(*cmd, **kw):
        return FakeRmProcess(rc=0)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    asyncio.run(remove_model(conn, settings, "org/model"))

    assert get_model(conn, "org/model", "llama.cpp") is None
    assert not snap.exists()


def test_remove_model_gguf_dir_file_when_no_snapshot(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    gguf = settings.resolved_gguf_dir / "model.gguf"
    gguf.parent.mkdir(parents=True)
    gguf.write_bytes(b"x" * 100)
    conn = init_db(tmp_path / "db.sqlite")
    upsert_model(conn, "org/model", "llama.cpp", "hf", str(gguf), "downloaded",
                 gguf_filename="model.gguf")

    monkeypatch.setattr("app.sync.hf_bin", lambda: "/usr/bin/hf")
    called = []

    async def fake_create(*cmd, **kw):
        called.append(cmd)
        return FakeRmProcess(rc=0)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create)

    asyncio.run(remove_model(conn, settings, "org/model"))

    assert called == []
    assert get_model(conn, "org/model", "llama.cpp") is None
    assert not gguf.exists()


def test_remove_gguf_file_removes_one_row_and_file(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    snap_dir = snapshot_dir_for(settings, "org/model") / "snapshots" / "main"
    snap_dir.mkdir(parents=True)
    for name in ("a.gguf", "b.gguf"):
        (snap_dir / name).write_bytes(b"x" * 100)
    conn = init_db(tmp_path / "db.sqlite")
    for name in ("a.gguf", "b.gguf"):
        upsert_model(conn, "org/model", "llama.cpp", "hf", str(snap_dir / name),
                     "downloaded", gguf_filename=name)
    monkeypatch.setattr("app.sync.hf_bin", lambda: "/usr/bin/hf")

    asyncio.run(remove_gguf_file(conn, settings, "org/model", "llama.cpp", "a.gguf"))

    rows = get_models(conn, "org/model", "llama.cpp")
    assert {r["gguf_filename"] for r in rows} == {"b.gguf"}
    assert not (snap_dir / "a.gguf").exists()
    assert (snap_dir / "b.gguf").exists()


def test_remove_gguf_file_noop_when_row_missing(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    snap_dir = snapshot_dir_for(settings, "org/model") / "snapshots" / "main"
    snap_dir.mkdir(parents=True)
    (snap_dir / "a.gguf").write_bytes(b"x" * 100)
    conn = init_db(tmp_path / "db.sqlite")
    upsert_model(conn, "org/model", "llama.cpp", "hf", str(snap_dir / "a.gguf"),
                 "downloaded", gguf_filename="a.gguf")
    monkeypatch.setattr("app.sync.hf_bin", lambda: "/usr/bin/hf")

    called = []

    async def fail_create(*cmd, **kw):
        called.append(cmd)
        raise AssertionError("hf cache rm must not run for per-file removal")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fail_create)

    asyncio.run(remove_gguf_file(conn, settings, "org/model", "llama.cpp", "nope.gguf"))

    assert called == []
    assert len(get_models(conn, "org/model", "llama.cpp")) == 1
    assert (snap_dir / "a.gguf").exists()


def test_remove_gguf_file_never_runs_hf_cache_rm(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    gguf = settings.resolved_gguf_dir / "model.gguf"
    gguf.parent.mkdir(parents=True)
    gguf.write_bytes(b"x" * 100)
    conn = init_db(tmp_path / "db.sqlite")
    upsert_model(conn, "org/model", "llama.cpp", "hf", str(gguf), "downloaded",
                 gguf_filename="model.gguf")
    monkeypatch.setattr("app.sync.hf_bin", lambda: "/usr/bin/hf")

    called = []

    async def fail_create(*cmd, **kw):
        called.append(cmd)
        raise AssertionError("hf cache rm must not run for per-file removal")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fail_create)

    asyncio.run(remove_gguf_file(conn, settings, "org/model", "llama.cpp", "model.gguf"))

    assert called == []
    assert get_models(conn, "org/model", "llama.cpp") == []
    assert not gguf.exists()


def test_remove_gguf_file_does_not_unlink_outside_safe_roots(tmp_path):
    settings = _settings(tmp_path)
    outside = tmp_path / "elsewhere" / "model.gguf"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"x" * 100)
    conn = init_db(tmp_path / "db.sqlite")
    upsert_model(conn, "org/model", "llama.cpp", "hf", str(outside), "downloaded",
                 gguf_filename="model.gguf")

    asyncio.run(remove_gguf_file(conn, settings, "org/model", "llama.cpp", "model.gguf"))

    assert get_models(conn, "org/model", "llama.cpp") == []
    assert outside.exists()


def test_hf_cache_root_falls_back_to_home(tmp_path):
    class SettingsLike:
        hf_cache_dir = None

    root = _hf_cache_root(SettingsLike())
    assert root == Path.home() / ".cache" / "huggingface" / "hub"


def test_reconcile_creates_one_row_per_gguf(tmp_path):
    settings = _settings(tmp_path)
    _make_snapshot(settings, "org/model", ggufs=["a.gguf", "b.gguf"],
                   readme="# model\n\nllama-server -m a.gguf\n")
    conn = init_db(tmp_path / "db.sqlite")

    reconcile_models(conn, settings)

    rows = get_models(conn, "org/model", "llama.cpp")
    assert {r["gguf_filename"] for r in rows if r["status"] == "downloaded"} == {"a.gguf", "b.gguf"}


def test_list_models_status_filter(tmp_path):
    conn = init_db(tmp_path / "db.sqlite")
    upsert_model(conn, "org/model", "llama.cpp", "hf", "/x", "downloaded")
    upsert_model(conn, "org/other", "llama.cpp", "hf", "/y", "missing")
    assert len(list_models(conn)) == 2
    downloaded = list_models(conn, status="downloaded")
    assert len(downloaded) == 1
    assert downloaded[0]["server_id"] == "llama.cpp"
