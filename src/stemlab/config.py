from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STEMLAB_", env_file=".env", extra="ignore")

    broker_url: str = "redis://localhost:6379/0"
    result_backend: str = "redis://localhost:6379/1"
    data_dir: Path = Path("data")
    max_upload_mb: int = Field(default=200, gt=0)
    max_duration_seconds: int = Field(default=900, gt=0)
    job_timeout_seconds: int = Field(default=7200, gt=0)
    cpu_threads: int = Field(default=4, gt=0)
    port: int = Field(default=8000, ge=1, le=65535)
    device: Literal["auto", "cpu", "cuda"] = "auto"
    queue_mode: Literal["celery", "local"] = "celery"


settings = Settings()
