"""Vocal estimation with Roformer models. Loaded only inside the inference process."""

import numpy as np

from stemlab.config import settings

MELBAND = "vocals_mel_band_roformer.ckpt"
BS = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
BETA4 = "melband_roformer_big_beta4.ckpt"
BS1296 = "model_bs_roformer_ep_368_sdr_12.9628.ckpt"
# Different models make different errors, so their average beats any one alone.
CHECKPOINTS = {
    "melband": (MELBAND,),
    "bs": (BS,),
    "beta4": (BETA4,),
    "bs1296": (BS1296,),
    "ensemble": (MELBAND, BS),
    "ensemble_all": (MELBAND, BETA4, BS, BS1296),
}
# Number of overlapping prediction windows per chunk (a count, unlike Demucs' fraction).
OVERLAP_WINDOWS = 8
SAMPLE_RATE = 44100


def vocals_of(stems: dict) -> np.ndarray:
    """Pick the vocal estimate; checkpoints spell the stem 'vocals' or 'Vocals'."""
    for name, stem in stems.items():
        if name.lower() == "vocals":
            return stem
    raise RuntimeError(f"Roformer model returned no vocals stem (got {sorted(stems)}).")


def separate_vocals(mix: np.ndarray, choice: str, announce) -> np.ndarray:
    """Return the vocal estimate for a channel-first stereo float32 mix at 44.1 kHz."""
    import torch
    from audio_separator.separator import Separator

    if not torch.cuda.is_available():
        raise RuntimeError("The Roformer pipeline requires CUDA. Use htdemucs_ft on CPU.")
    checkpoints = CHECKPOINTS[choice]
    estimates = []
    for number, filename in enumerate(checkpoints, start=1):
        announce(f"Separating vocals, model {number} of {len(checkpoints)}")
        separator = Separator(
            model_file_dir=str(settings.data_dir / "models" / "roformer"),
            sample_rate=SAMPLE_RATE,
            mdxc_params={
                "segment_size": 256,
                "override_model_segment_size": False,
                "batch_size": None,
                "overlap": OVERLAP_WINDOWS,
                "pitch_shift": 0,
            },
        )
        separator.load_model(model_filename=filename)
        # demix() skips the library's file path, which normalizes peaks and writes integer WAVs.
        estimates.append(vocals_of(separator.model_instance.demix(mix)))
        del separator
        torch.cuda.empty_cache()
    return np.mean(estimates, axis=0)
