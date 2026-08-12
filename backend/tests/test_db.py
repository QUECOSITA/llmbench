import sqlite3

import pytest

from app.db import init_db, upsert_model, get_model, list_models, create_run, finish_run, save_result, list_runs, get_results_for_run, create_config, fail_stale_runs, get_run_status, set_run_status, get_active_run, clear_history, list_configs


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
