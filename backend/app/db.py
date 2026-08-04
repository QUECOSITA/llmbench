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
    downloaded_at TEXT,
    UNIQUE(repo_id, server_id)
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


def init_db(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.executescript(
        "INSERT OR IGNORE INTO servers(id, display_name) VALUES "
        "('llama.cpp','llama.cpp'), ('vllm','vLLM'), ('sglang','sglang');"
    )
    conn.commit()
    return conn


def _row(conn: sqlite3.Connection, sql: str, params=()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def upsert_model(conn, repo_id, server_id, format, local_path, status,
                 gguf_filename=None, size_bytes=None, downloaded_at=None):
    conn.execute(
        """
        INSERT INTO models(repo_id, server_id, format, local_path, status, gguf_filename, size_bytes, downloaded_at)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(repo_id, server_id) DO UPDATE SET
            format=excluded.format, local_path=excluded.local_path, status=excluded.status,
            gguf_filename=excluded.gguf_filename, size_bytes=excluded.size_bytes,
            downloaded_at=excluded.downloaded_at
        """,
        (repo_id, server_id, format, str(local_path), status, gguf_filename, size_bytes, downloaded_at),
    )
    conn.commit()


def get_model(conn, repo_id, server_id):
    return _row(conn, "SELECT * FROM models WHERE repo_id=? AND server_id=?", (repo_id, server_id))


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


def list_runs(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY id DESC")]
