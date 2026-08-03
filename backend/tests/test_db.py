from app.db import init_db, upsert_model, get_model, list_models, create_run, finish_run, save_result, list_runs, get_results_for_run, create_config


def test_model_crud(tmp_path):
    conn = init_db(tmp_path / "test.db")
    upsert_model(conn, repo_id="org/model", server_id="vllm", format="hf", local_path="/x", status="missing")
    m = get_model(conn, "org/model", "vllm")
    assert m["status"] == "missing"
    upsert_model(conn, repo_id="org/model", server_id="vllm", format="hf", local_path="/x", status="downloaded")
    m = get_model(conn, "org/model", "vllm")
    assert m["status"] == "downloaded"
    assert len(list_models(conn)) == 1
    conn.close()


def test_run_and_results(tmp_path):
    conn = init_db(tmp_path / "test.db")
    run_id = create_run(conn, repo_id="org/model", requested_n=2)
    assert run_id == 1
    finish_run(conn, run_id, status="completed")
    cfg_id = create_config(conn, run_id=run_id, server_id="vllm", model_id=1,
                           flag_conf_json=[{"flag": "--max-model-len", "value": "8192"}],
                           serving_command="vllm serve org/model --max-model-len 8192",
                           bench_command="python -m vllm.benchmarks.benchmark_throughput ...")
    save_result(conn, config_id=cfg_id, prompt_processing_tps=1200.0, decode_tps=86.4,
                duration_s=30.0, output_snippet="", status="ok")
    results = get_results_for_run(conn, run_id)
    assert len(results) == 1
    assert results[0]["decode_tps"] == 86.4
    assert list_runs(conn)[0]["status"] == "completed"
    conn.close()
