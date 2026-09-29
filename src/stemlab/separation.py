"""Common output type and contract for source-separation engines."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Stem:
    name: str
    path: Path


class Separator(Protocol):
    def separate(self, source: Path, output_dir: Path) -> list[Stem]:
        """Read WAV/MP3 audio and return generated WAV files inside output_dir."""
        ...
