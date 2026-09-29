"""Opt-in real-model smoke test: uv run --extra cuda python scripts/verify_inference.py."""

import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from stemlab.inference import separate
from stemlab.outputs import STEMS

with tempfile.TemporaryDirectory(prefix="stemlab-inference-") as directory:
    root = Path(directory)
    time = np.arange(44100 * 3) / 44100
    signal = 0.15 * np.sin(2 * np.pi * 220 * time) + 0.08 * np.sin(2 * np.pi * 880 * time)
    sf.write(root / "input.wav", np.stack([signal, signal], axis=1), 44100)
    separate(root / "input.wav", root / "stems")
    for name in STEMS:
        data, rate = sf.read(root / "stems" / f"{name}.wav", always_2d=True)
        assert rate == 44100 and data.shape == (len(time), 2)
        assert np.isfinite(data).all()
    print("Real model inference: four valid WAV stems generated.")
