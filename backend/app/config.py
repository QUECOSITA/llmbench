from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLMBENCH_", extra="ignore")

    data_dir: Path = Path.home() / ".llmbench"
    gguf_dir: Path = Path("gguf")
    hf_cache_dir: Path | None = None
    benchmark_timeout_s: int = 60
    workload_file: Path = Path(__file__).resolve().parents[1] / "data" / "coding_prompts.jsonl"

    @model_validator(mode="after")
    def _resolve_gguf_dir(self) -> "Settings":
        if not self.gguf_dir.is_absolute():
            self.gguf_dir = self.data_dir / self.gguf_dir
        return self

    @property
    def resolved_gguf_dir(self) -> Path:
        return self.gguf_dir if self.gguf_dir.is_absolute() else self.data_dir / self.gguf_dir
