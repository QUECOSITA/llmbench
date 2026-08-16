import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS servers (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS models (
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
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id TEXT NOT NULL,
    requested_n INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'queued'
);
CREATE TABLE IF NOT EXISTS configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    server_id TEXT NOT NULL,
    model_id INTEGER REFERENCES models(id),
    flag_conf_json TEXT NOT NULL,
    serving_command TEXT NOT NULL,
    bench_command TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id INTEGER NOT NULL REFERENCES configs(id),
    prompt_processing_tps REAL,
    decode_tps REAL,
    duration_s REAL,
    output_snippet TEXT,
    status TEXT NOT NULL
);
"""


def _migrate_models_table(conn):
    """Drop the legacy one-row-per-(repo,server) uniqueness so multiple .gguf
    rows per repo/server can coexist. Rebuilds the table only when the legacy
    autoindex exists; otherwise just creates the partial unique indexes."""
    index_names = [row[1] for row in conn.execute("PRAGMA index_list('models')")]
    if "sqlite_autoindex_models_1" in index_names:
        conn.execute("ALTER TABLE models RENAME TO models_old")
        conn.execute(
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
            )
            """
        )
        conn.execute(
            """
            INSERT INTO models (repo_id, server_id, format, local_path, status,
                                gguf_filename, size_bytes, downloaded_at)
            SELECT repo_id, server_id, format, local_path, status,
                   gguf_filename, size_bytes, downloaded_at
            FROM models_old
            """
        )
        conn.execute("DROP TABLE models_old")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_models_repo_server "
        "ON models(repo_id, server_id) WHERE gguf_filename IS NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_models_repo_server_gguf "
        "ON models(repo_id, server_id, gguf_filename) WHERE gguf_filename IS NOT NULL"
    )
    conn.commit()


def init_db(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _migrate_models_table(conn)
    conn.executescript(
        "INSERT OR IGNORE INTO servers(id, display_name) VALUES "
        "('llama.cpp','llama.cpp');"
    )
    conn.commit()
    return conn


def _row(conn: sqlite3.Connection, sql: str, params=()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def upsert_model(conn, repo_id, server_id, format, local_path, status,
                 gguf_filename=None, size_bytes=None, downloaded_at=None):
    if gguf_filename is None:
        row = conn.execute(
            "SELECT id FROM models WHERE repo_id=? AND server_id=? AND gguf_filename IS NULL",
            (repo_id, server_id)).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM models WHERE repo_id=? AND server_id=? AND gguf_filename=?",
            (repo_id, server_id, gguf_filename)).fetchone()
    if row:
        conn.execute(
            "UPDATE models SET format=?, local_path=?, status=?, size_bytes=?, downloaded_at=? WHERE id=?",
            (format, str(local_path), status, size_bytes, downloaded_at, row["id"]))
    else:
        conn.execute(
            "INSERT INTO models(repo_id, server_id, format, local_path, status, "
            "gguf_filename, size_bytes, downloaded_at) VALUES (?,?,?,?,?,?,?,?)",
            (repo_id, server_id, format, str(local_path), status, gguf_filename, size_bytes, downloaded_at))
    conn.commit()


def get_model(conn, repo_id, server_id):
    return _row(
        conn,
        "SELECT * FROM models WHERE repo_id=? AND server_id=? ORDER BY gguf_filename",
        (repo_id, server_id),
    )


def get_models(conn, repo_id, server_id=None, status=None):
    if server_id is None:
        rows = conn.execute(
            "SELECT * FROM models WHERE repo_id=? ORDER BY server_id, gguf_filename",
            (repo_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM models WHERE repo_id=? AND server_id=? ORDER BY gguf_filename",
            (repo_id, server_id)).fetchall()
    out = [dict(r) for r in rows]
    if status is not None:
        out = [m for m in out if m["status"] == status]
    return out


def list_models(conn, status=None):
    if status is None:
        return [dict(r) for r in conn.execute("SELECT * FROM models ORDER BY server_id, repo_id")]
    return [dict(r) for r in conn.execute(
        "SELECT * FROM models WHERE status=? ORDER BY server_id, repo_id", (status,))]


def delete_model(conn, repo_id, server_id):
    conn.execute("DELETE FROM models WHERE repo_id=? AND server_id=?", (repo_id, server_id))
    conn.commit()


def create_run(conn, repo_id, requested_n):
    cur = conn.execute("INSERT INTO runs(repo_id, requested_n) VALUES (?,?)", (repo_id, requested_n))
    conn.commit()
    return cur.lastrowid


def set_run_status(conn, run_id, status):
    conn.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))
    conn.commit()


def finish_run(conn, run_id, status):
    set_run_status(conn, run_id, status)


def create_config(conn, run_id, server_id, model_id, flag_conf_json, serving_command, bench_command):
    cur = conn.execute(
        "INSERT INTO configs(run_id, server_id, model_id, flag_conf_json, serving_command, bench_command) VALUES (?,?,?,?,?,?)",
        (run_id, server_id, model_id, json.dumps(flag_conf_json), serving_command, bench_command),
    )
    conn.commit()
    return cur.lastrowid


def list_configs(conn, run_id):
    rows = conn.execute("SELECT * FROM configs WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["flag_conf"] = json.loads(d.pop("flag_conf_json"))
        out.append(d)
    return out


def save_result(conn, config_id, prompt_processing_tps, decode_tps, duration_s, output_snippet, status):
    conn.execute(
        "INSERT INTO results(config_id, prompt_processing_tps, decode_tps, duration_s, output_snippet, status) VALUES (?,?,?,?,?,?)",
        (config_id, prompt_processing_tps, decode_tps, duration_s, output_snippet, status),
    )
    conn.commit()


def get_results_for_run(conn, run_id):
    rows = conn.execute(
        """
        SELECT c.id AS config_id, c.server_id, c.flag_conf_json,
               c.serving_command, r.prompt_processing_tps, r.decode_tps,
               r.duration_s, r.status AS result_status
        FROM configs c LEFT JOIN results r ON r.config_id = c.id
        WHERE c.run_id=? ORDER BY r.decode_tps DESC, c.id
        """, (run_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["flag_conf"] = json.loads(d.pop("flag_conf_json"))
        out.append(d)
    return out


def get_run_status(conn, run_id):
    row = conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
    return row["status"] if row else None


def get_run(conn, run_id):
    row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def get_active_run(conn):
    return _row(
        conn,
        "SELECT * FROM runs WHERE status IN ('running', 'queued') ORDER BY id DESC",
    )


def list_runs(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY id DESC")]


def fail_stale_runs(conn):
    """Mark runs left in 'running' or 'queued' state (e.g. from a crashed/
    restarted process) as failed so they no longer appear as in-flight."""
    conn.execute("UPDATE runs SET status='failed' WHERE status IN ('running', 'queued')")
    conn.commit()


def clear_history(conn):
    """Delete all benchmark runs, configs, and results. Keeps models/servers."""
    conn.execute("DELETE FROM results")
    conn.execute("DELETE FROM configs")
    conn.execute("DELETE FROM runs")
    conn.commit()
