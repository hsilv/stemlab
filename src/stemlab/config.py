from pathlib import Path
from typing import Literal, get_args

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Drums, bass and other come from Demucs. Vocals come from Demucs too, or from Roformer models.
Model = Literal["htdemucs", "htdemucs_ft", "hdemucs_mmi", "ft_mmi"]
MODELS = get_args(Model)
# The Demucs models behind each choice; several are run and averaged.
DEMUCS_MODELS: dict[Model, tuple[str, ...]] = {
    "htdemucs": ("htdemucs",),
    "htdemucs_ft": ("htdemucs_ft",),
    "hdemucs_mmi": ("hdemucs_mmi",),
    "ft_mmi": ("htdemucs_ft", "hdemucs_mmi"),
}
Vocals = Literal["demucs", "melband", "bs", "beta4", "bs1296", "ensemble", "ensemble_all"]
VOCAL_MODELS = get_args(Vocals)
# Where drums, bass and other come from when vocals come from Roformer: Demucs run on the mix
# minus the vocals, Demucs run on the mix, or (No vocals only) the mix minus the vocals itself.
InstrumentsFrom = Literal["residual", "mix", "inverse"]
INSTRUMENT_SOURCES = get_args(InstrumentsFrom)
# "inverse" only fits some outputs, so it cannot be the default for every job.
DefaultInstrumentsFrom = Literal["residual", "mix"]
MAX_SHIFTS = 5
OVERLAP_RANGE = (0.1, 0.9)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STEMLAB_", env_file=".env", extra="ignore")

    broker_url: str = "redis://localhost:6379/0"
    result_backend: str = "redis://localhost:6379/1"
    data_dir: Path = Path("data")
    mixxx_db: Path = Path.home() / ".mixxx" / "mixxxdb.sqlite"
    max_upload_mb: int = Field(default=200, gt=0)
    max_duration_seconds: int = Field(default=900, gt=0)
    job_timeout_seconds: int = Field(default=7200, gt=0)
    cpu_threads: int = Field(default=4, gt=0)
    port: int = Field(default=8000, ge=1, le=65535)
    model: Model = "htdemucs_ft"
    vocals: Vocals = "ensemble"
    instruments_from: DefaultInstrumentsFrom = "residual"
    shifts: int = Field(default=2, ge=0, le=MAX_SHIFTS)
    overlap: float = Field(default=0.5, ge=OVERLAP_RANGE[0], le=OVERLAP_RANGE[1])
    device: Literal["auto", "cpu", "cuda"] = "auto"
    queue_mode: Literal["celery", "local"] = "celery"


settings = Settings()
