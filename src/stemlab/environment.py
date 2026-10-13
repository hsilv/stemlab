"""Where things live on this operating system."""

import os
import sys
from pathlib import Path


def venv_python(venv):
    """The interpreter of a virtual environment folder."""
    if sys.platform == "win32":
        return Path(venv) / "Scripts" / "python.exe"
    return Path(venv) / "bin" / "python"


def default_mixxx_db():
    """Where Mixxx keeps its library by default."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        folder = Path(base) if base else Path.home() / "AppData" / "Local"
        return folder / "Mixxx" / "mixxxdb.sqlite"
    return Path.home() / ".mixxx" / "mixxxdb.sqlite"
