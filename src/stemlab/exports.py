"""Re-encode a stored stem as the format the listener downloads: FLAC, WAV or 320 kbps MP3."""

import shutil
import subprocess

import numpy as np
import soundfile as sf

from stemlab.inference import FULL_SCALE

MP3_KBPS = 320
SUFFIX = {"flac": ".flac", "wav": ".wav", "mp3": ".mp3"}
MEDIA_TYPES = {".flac": "audio/flac", ".wav": "audio/wav", ".mp3": "audio/mpeg"}


class ExportUnavailable(RuntimeError):
    """The requested format cannot be produced on this machine."""


def formats():
    """Formats this machine can write. MP3 needs ffmpeg with libmp3lame."""
    return [name for name in SUFFIX if name != "mp3" or shutil.which("ffmpeg")]


def convert(source, fmt, target):
    """Write source (a stored stem) to target as fmt. target must end with SUFFIX[fmt].

    The result carries no tags; the caller copies the song's onto it (see tags.py).
    """
    if fmt not in formats():
        raise ExportUnavailable(
            "MP3 export needs ffmpeg installed on the server."
            if fmt == "mp3"
            else "Unknown export format."
        )
    if fmt == "mp3":
        _mp3(source, target)
        return
    audio, rate = sf.read(source, dtype="float32", always_2d=True)
    # Stems from before FLAC are float and may exceed full scale; integer files cannot.
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > FULL_SCALE:
        audio = audio * (FULL_SCALE / peak)
    sf.write(target, audio, rate, format=fmt.upper(), subtype="PCM_24")


def _mp3(source, target):
    command = [
        "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source),
        "-vn", "-map_metadata", "-1", "-c:a", "libmp3lame", "-b:a", f"{MP3_KBPS}k",
        str(target),
    ]  # fmt: skip
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise RuntimeError(f"MP3 encoding failed: {result.stderr.strip()[-300:]}")
