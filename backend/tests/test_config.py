from app.config import Settings


def test_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMBENCH_DATA_DIR", str(tmp_path))
    s = Settings()
    assert s.data_dir == tmp_path
    assert s.gguf_dir == tmp_path / "gguf"
    assert s.hf_cache_dir is None
    assert s.benchmark_timeout_s == 60
    assert s.workload_file.name == "coding_prompts.jsonl"


def test_llama_cpp_bin_dir_default_none():
    s = Settings()
    assert s.llama_cpp_bin_dir is None


def test_llama_cpp_bin_dir_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMBENCH_LLAMA_CPP_BIN_DIR", str(tmp_path))
    s = Settings()
    assert s.llama_cpp_bin_dir == tmp_path


def test_speed_bench_settings_defaults():
    s = Settings()
    assert s.speed_bench_script is None
    assert s.speed_bench_timeout_s == 300
    assert s.speed_bench_osl == 4096


def test_speed_bench_settings_env(monkeypatch):
    monkeypatch.setenv("LLMBENCH_SPEED_BENCH_TIMEOUT_S", "450")
    monkeypatch.setenv("LLMBENCH_SPEED_BENCH_OSL", "256")
    s = Settings()
    assert s.speed_bench_timeout_s == 450
    assert s.speed_bench_osl == 256
