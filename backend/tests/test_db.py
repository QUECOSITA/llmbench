import sqlite3

import pytest

from app.db import init_db, upsert_model, get_model, get_models, list_models, create_run, finish_run, save_result, list_runs, get_results_for_run, create_config, fail_stale_runs, get_run_status, set_run_status, get_active_run, clear_history, list_configs, delete_model_row


def test_model_crud(tmp_path):
    conn = init_db(tmp_path / "test.db")
    upsert_model(conn, repo_id="org/model", server_id="llama.cpp", format="hf", local_path="/x", status="missing")
    m = get_model(conn, "org/model", "llama.cpp")
    assert m["status"] == "missing"
    upsert_model(conn, repo_id="org/model", server_id="llama.cpp", format="hf", local_path="/x", status="downloaded")
    m = get_model(conn, "org/model", "llama.cpp")
    assert m["status"] == "downloaded"
    assert len(list_models(conn)) == 1
    conn.close()


def test_multiple_gguf_rows_for_same_repo_and_server(tmp_path):
    conn = init_db(tmp_path / "test.db")
    upsert_model(conn, "org/model", "llama.cpp", "hf", "/x/a.gguf", "downloaded",
                 gguf_filename="a.gguf", size_bytes=100)
    upsert_model(conn, "org/model", "llama.cpp", "hf", "/x/b.gguf", "downloaded",
                 gguf_filename="b.gguf", size_bytes=200)
    rows = get_models(conn, "org/model", "llama.cpp", status="downloaded")
    assert {r["gguf_filename"] for r in rows} == {"a.gguf", "b.gguf"}
    conn.close()


def test_delete_model_row_removes_only_targeted_gguf(tmp_path):
    conn = init_db(tmp_path / "test.db")
    upsert_model(conn, "org/model", "llama.cpp", "hf", "/x/a.gguf", "downloaded",
                 gguf_filename="a.gguf", size_bytes=100)
    upsert_model(conn, "org/model", "llama.cpp", "hf", "/x/b.gguf", "downloaded",
                 gguf_filename="b.gguf", size_bytes=200)
    upsert_model(conn, "org/model", "llama.cpp", "hf", "/x", "downloaded")

    delete_model_row(conn, "org/model", "llama.cpp", "a.gguf")

    rows = get_models(conn, "org/model", "llama.cpp")
    assert {r["gguf_filename"] for r in rows if r["gguf_filename"]} == {"b.gguf"}
    assert any(r["gguf_filename"] is None for r in rows)
    conn.close()


def test_upsert_null_gguf_is_idempotent(tmp_path):
    conn = init_db(tmp_path / "test.db")
    upsert_model(conn, "org/model", "llama.cpp", "hf", "/x", "downloaded")
    upsert_model(conn, "org/model", "llama.cpp", "hf", "/x", "missing")
    assert len(list_models(conn)) == 1
    conn.close()


def test_migrate_legacy_models_table_preserves_history(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_id TEXT NOT NULL,
            server_id TEXT NOT NULL,
            format TEXT NOT NULL,
            local_path TEXT NOT NULL,
            status TEXT NOT NULL,
            gguf_filename TEXT,
            size_bytes INTEGER,
            downloaded_at TEXT,
            UNIQUE(repo_id, server_id)
        );
        CREATE TABLE runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_id TEXT NOT NULL,
            requested_n INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            status TEXT NOT NULL DEFAULT 'queued'
        );
        CREATE TABLE configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id),
            server_id TEXT NOT NULL,
            model_id INTEGER REFERENCES models(id),
            flag_conf_json TEXT NOT NULL,
            serving_command TEXT NOT NULL,
            bench_command TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO models(repo_id, server_id, format, local_path, status, gguf_filename, size_bytes) "
        "VALUES (?,?,?,?,?,?,?)",
        ("org/deleted", "llama.cpp", "hf", "/gone", "missing", None, None),
    )
    conn.execute("DELETE FROM models WHERE id = 1")
    conn.execute(
        "INSERT INTO models(repo_id, server_id, format, local_path, status, gguf_filename, size_bytes) "
        "VALUES (?,?,?,?,?,?,?)",
        ("org/legacy", "llama.cpp", "hf", "/x", "downloaded", "a.gguf", 100),
    )
    conn.execute("INSERT INTO runs(repo_id, requested_n) VALUES ('org/legacy', 2)")
    conn.execute(
        "INSERT INTO configs(run_id, server_id, model_id, flag_conf_json, serving_command, bench_command) "
        "VALUES (1, 'llama.cpp', 2, '[]', 'serve', 'bench')"
    )
    conn.commit()
    conn.close()

    migrated = init_db(db_path)
    models = list_models(migrated)
    assert [m["gguf_filename"] for m in models] == ["a.gguf"]
    assert models[0]["id"] == 2
    config_row = migrated.execute(
        "SELECT c.id, c.model_id, m.repo_id FROM configs c "
        "LEFT JOIN models m ON m.id = c.model_id WHERE c.id = 1"
    ).fetchone()
    assert config_row is not None
    assert config_row["model_id"] == 2
    assert config_row["repo_id"] == "org/legacy"
    upsert_model(migrated, "org/legacy", "llama.cpp", "hf", "/z", "downloaded",
                 gguf_filename="c.gguf")
    assert max(m["id"] for m in list_models(migrated)) > 2
    index_names = [r[1] for r in migrated.execute("PRAGMA index_list('models')")]
    assert "uq_models_repo_server" in index_names
    assert "uq_models_repo_server_gguf" in index_names
    upsert_model(migrated, "org/legacy", "llama.cpp", "hf", "/y", "downloaded",
                 gguf_filename="b.gguf")
    assert len(get_models(migrated, "org/legacy", "llama.cpp")) == 3
    migrated.close()


def test_run_and_results(tmp_path):
    conn = init_db(tmp_path / "test.db")
    upsert_model(conn, repo_id="org/model", server_id="llama.cpp", format="hf", local_path="/x", status="downloaded")
    run_id = create_run(conn, repo_id="org/model", requested_n=2)
    assert run_id == 1
    finish_run(conn, run_id, status="completed")
    cfg_id = create_config(conn, run_id=run_id, server_id="llama.cpp", model_id=1,
                           flag_conf_json=[{"flag": "--ctx-size", "value": "8192"}],
                           serving_command="llama-server --hf-repo org/model --hf-file model.gguf --ctx-size 8192",
                           bench_command="llama-bench -m model.gguf ...")
    save_result(conn, config_id=cfg_id, prompt_processing_tps=1200.0, decode_tps=86.4,
                duration_s=30.0, output_snippet="", status="ok")
    results = get_results_for_run(conn, run_id)
    assert len(results) == 1
    assert results[0]["decode_tps"] == 86.4
    assert list_runs(conn)[0]["status"] == "completed"
    conn.close()


def test_get_results_ranking(tmp_path):
    conn = init_db(tmp_path / "test.db")
    upsert_model(conn, repo_id="org/model", server_id="llama.cpp", format="hf", local_path="/x", status="downloaded")
    run_id = create_run(conn, repo_id="org/model", requested_n=2)
    slow_cfg = create_config(conn, run_id=run_id, server_id="llama.cpp", model_id=1,
                             flag_conf_json=[{"flag": "--ctx-size", "value": "8192"}],
                             serving_command="llama-server --hf-repo org/model --hf-file model.gguf --ctx-size 8192",
                             bench_command="bench")
    fast_cfg = create_config(conn, run_id=run_id, server_id="llama.cpp", model_id=1,
                             flag_conf_json=[{"flag": "--ctx-size", "value": "4096"}],
                             serving_command="llama-server --hf-repo org/model --hf-file model.gguf --ctx-size 4096",
                             bench_command="bench")
    save_result(conn, config_id=slow_cfg, prompt_processing_tps=1000.0, decode_tps=50.0,
                duration_s=30.0, output_snippet="", status="ok")
    save_result(conn, config_id=fast_cfg, prompt_processing_tps=2000.0, decode_tps=90.0,
                duration_s=30.0, output_snippet="", status="ok")
    results = get_results_for_run(conn, run_id)
    assert [r["config_id"] for r in results] == [fast_cfg, slow_cfg]
    assert results[0]["decode_tps"] == 90.0
    conn.close()


def test_flag_conf_parsed_in_results(tmp_path):
    conn = init_db(tmp_path / "test.db")
    upsert_model(conn, repo_id="org/model", server_id="llama.cpp", format="hf", local_path="/x", status="downloaded")
    run_id = create_run(conn, repo_id="org/model", requested_n=1)
    cfg_id = create_config(conn, run_id=run_id, server_id="llama.cpp", model_id=1,
                           flag_conf_json=[{"flag": "--ctx-size", "value": "8192"}],
                           serving_command="llama-server --hf-repo org/model --hf-file model.gguf --ctx-size 8192",
                           bench_command="bench")
    save_result(conn, config_id=cfg_id, prompt_processing_tps=1200.0, decode_tps=86.4,
                duration_s=30.0, output_snippet="", status="ok")
    row = get_results_for_run(conn, run_id)[0]
    assert row["flag_conf"] == [{"flag": "--ctx-size", "value": "8192"}]
    assert isinstance(row["flag_conf"], list)
    assert "flag_conf_json" not in row
    conn.close()


def test_foreign_keys_enforced(tmp_path):
    conn = init_db(tmp_path / "test.db")
    with pytest.raises(sqlite3.IntegrityError):
        create_config(conn, run_id=999, server_id="llama.cpp", model_id=None,
                      flag_conf_json=[], serving_command="x", bench_command="y")
    conn.close()


def test_fail_stale_runs_marks_inflight_runs_failed(tmp_path):
    conn = init_db(tmp_path / "test.db")
    running_id = create_run(conn, repo_id="org/model", requested_n=1)
    set_run_status(conn, running_id, "running")
    done_id = create_run(conn, repo_id="org/model", requested_n=1)
    finish_run(conn, done_id, status="completed")
    assert get_run_status(conn, running_id) == "running"

    fail_stale_runs(conn)

    assert get_run_status(conn, running_id) == "failed"
    assert get_run_status(conn, done_id) == "completed"
    conn.close()


def test_get_active_run_returns_most_recent_inflight(tmp_path):
    conn = init_db(tmp_path / "test.db")
    old_id = create_run(conn, repo_id="org/old", requested_n=2)
    set_run_status(conn, old_id, "running")
    done_id = create_run(conn, repo_id="org/done", requested_n=1)
    finish_run(conn, done_id, status="completed")
    new_id = create_run(conn, repo_id="org/new", requested_n=3)
    set_run_status(conn, new_id, "queued")

    active = get_active_run(conn)
    assert active is not None
    assert active["id"] == new_id
    assert active["repo_id"] == "org/new"
    assert active["status"] == "queued"
    conn.close()


def test_get_active_run_none_when_nothing_inflight(tmp_path):
    conn = init_db(tmp_path / "test.db")
    run_id = create_run(conn, repo_id="org/model", requested_n=1)
    finish_run(conn, run_id, status="completed")
    assert get_active_run(conn) is None
    conn.close()


def test_clear_history_empties_runs_but_keeps_models(tmp_path):
    conn = init_db(tmp_path / "test.db")
    upsert_model(conn, repo_id="org/model", server_id="llama.cpp", format="hf", local_path="/x", status="downloaded")
    run_id = create_run(conn, repo_id="org/model", requested_n=2)
    finish_run(conn, run_id, status="completed")
    cfg_id = create_config(conn, run_id=run_id, server_id="llama.cpp", model_id=1,
                           flag_conf_json=[], serving_command="x", bench_command="y")
    save_result(conn, config_id=cfg_id, prompt_processing_tps=1200.0, decode_tps=86.4,
                duration_s=30.0, output_snippet="", status="ok")
    assert len(list_runs(conn)) == 1
    assert len(list_configs(conn, run_id)) == 1

    clear_history(conn)

    assert list_runs(conn) == []
    assert list_configs(conn, run_id) == []
    assert len(list_models(conn)) == 1
    conn.close()


def test_repair_dangling_configs_fk(tmp_path):
    db_path = tmp_path / "corrupt.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_id TEXT NOT NULL,
            server_id TEXT NOT NULL,
            format TEXT NOT NULL,
            local_path TEXT NOT NULL,
            status TEXT NOT NULL,
            gguf_filename TEXT,
            size_bytes INTEGER,
            downloaded_at TEXT
        );
        CREATE TABLE runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_id TEXT NOT NULL,
            requested_n INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            status TEXT NOT NULL DEFAULT 'queued'
        );
        CREATE TABLE configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id),
            server_id TEXT NOT NULL,
            model_id INTEGER REFERENCES "models_old"(id),
            flag_conf_json TEXT NOT NULL,
            serving_command TEXT NOT NULL,
            bench_command TEXT NOT NULL
        );
        CREATE TABLE results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_id INTEGER NOT NULL REFERENCES configs(id),
            prompt_processing_tps REAL,
            decode_tps REAL,
            duration_s REAL,
            output_snippet TEXT,
            status TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO models(repo_id, server_id, format, local_path, status, gguf_filename) "
        "VALUES (?,?,?,?,?,?)",
        ("org/model", "llama.cpp", "hf", "/x/a.gguf", "downloaded", "a.gguf"),
    )
    conn.execute("INSERT INTO runs(repo_id, requested_n) VALUES ('org/model', 1)")
    conn.execute(
        "INSERT INTO configs(run_id, server_id, model_id, flag_conf_json, serving_command, bench_command) "
        "VALUES (1, 'llama.cpp', NULL, '[]', 'serve', 'bench')"
    )
    conn.execute(
        "INSERT INTO results(config_id, prompt_processing_tps, decode_tps, duration_s, output_snippet, status) "
        "VALUES (1, 1200.0, 86.4, 30.0, '', 'ok')"
    )
    conn.commit()
    conn.close()

    conn = init_db(db_path)
    fk_tables = {row[2] for row in conn.execute("PRAGMA foreign_key_list('configs')")}
    assert fk_tables == {"runs", "models"}
    model = conn.execute("SELECT repo_id FROM models WHERE id=1").fetchone()
    assert model["repo_id"] == "org/model"
    assert conn.execute("SELECT COUNT(*) FROM configs").fetchone()[0] == 1
    results = get_results_for_run(conn, 1)
    assert len(results) == 1
    assert results[0]["decode_tps"] == 86.4
    cfg_id = create_config(conn, run_id=1, server_id="llama.cpp", model_id=None,
                           flag_conf_json=[], serving_command="x", bench_command="y")
    assert cfg_id == 2
    conn.close()


def test_repair_configs_fk_noop_on_healthy_db(tmp_path):
    db_path = tmp_path / "healthy.db"
    conn = init_db(db_path)
    conn.close()
    conn = init_db(db_path)
    fk_tables = {row[2] for row in conn.execute("PRAGMA foreign_key_list('configs')")}
    assert fk_tables == {"runs", "models"}
    conn.close()


def test_migrate_results_adds_agentic_tps(tmp_path):
    db_path = tmp_path / "legacy-results.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE servers (id TEXT PRIMARY KEY, display_name TEXT NOT NULL);
        CREATE TABLE models (id INTEGER PRIMARY KEY AUTOINCREMENT, repo_id TEXT NOT NULL,
            server_id TEXT NOT NULL, format TEXT NOT NULL, local_path TEXT NOT NULL,
            status TEXT NOT NULL, gguf_filename TEXT, size_bytes INTEGER, downloaded_at TEXT);
        CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, repo_id TEXT NOT NULL,
            requested_n INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')),
            status TEXT NOT NULL DEFAULT 'queued');
        CREATE TABLE configs (id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES runs(id), server_id TEXT NOT NULL,
            model_id INTEGER REFERENCES models(id), flag_conf_json TEXT NOT NULL,
            serving_command TEXT NOT NULL, bench_command TEXT NOT NULL);
        CREATE TABLE results (id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_id INTEGER NOT NULL REFERENCES configs(id),
            prompt_processing_tps REAL, decode_tps REAL, duration_s REAL,
            output_snippet TEXT, status TEXT NOT NULL);
        """
    )
    conn.execute("INSERT INTO runs(repo_id, requested_n) VALUES ('org/model', 1)")
    conn.execute(
        "INSERT INTO configs(run_id, server_id, model_id, flag_conf_json, serving_command, bench_command) "
        "VALUES (1, 'llama.cpp', NULL, '[]', 'serve', 'bench')"
    )
    conn.execute(
        "INSERT INTO results(config_id, prompt_processing_tps, decode_tps, duration_s, output_snippet, status) "
        "VALUES (1, 1200.0, 86.4, 30.0, '', 'ok')"
    )
    conn.commit()
    conn.close()

    conn = init_db(db_path)
    cols = [row[1] for row in conn.execute("PRAGMA table_info('results')")]
    assert "agentic_tps" in cols
    rows = get_results_for_run(conn, 1)
    assert rows[0]["agentic_tps"] is None
    assert rows[0]["decode_tps"] == 86.4
    conn.close()


def test_save_and_rank_by_agentic_tps(tmp_path):
    conn = init_db(tmp_path / "test.db")
    upsert_model(conn, repo_id="org/model", server_id="llama.cpp", format="hf",
                 local_path="/x", status="downloaded")
    run_id = create_run(conn, repo_id="org/model", requested_n=2)
    slow_agentic = create_config(conn, run_id=run_id, server_id="llama.cpp", model_id=1,
                                 flag_conf_json=[], serving_command="s", bench_command="b")
    fast_agentic = create_config(conn, run_id=run_id, server_id="llama.cpp", model_id=1,
                                 flag_conf_json=[], serving_command="s", bench_command="b")
    raw_fast = create_config(conn, run_id=run_id, server_id="llama.cpp", model_id=1,
                             flag_conf_json=[], serving_command="s", bench_command="b")
    save_result(conn, config_id=slow_agentic, prompt_processing_tps=None, decode_tps=None,
                duration_s=64.0, output_snippet="", status="ok", agentic_tps=20.0)
    save_result(conn, config_id=fast_agentic, prompt_processing_tps=None, decode_tps=None,
                duration_s=64.0, output_snippet="", status="ok", agentic_tps=50.0)
    save_result(conn, config_id=raw_fast, prompt_processing_tps=2000.0, decode_tps=90.0,
                duration_s=30.0, output_snippet="", status="ok")
    results = get_results_for_run(conn, run_id)
    assert [r["config_id"] for r in results] == [raw_fast, fast_agentic, slow_agentic]
    assert results[0]["agentic_tps"] is None
    assert results[0]["decode_tps"] == 90.0
    assert results[1]["agentic_tps"] == 50.0
    conn.close()
