"""Vocal estimation with Roformer models. Loaded only inside the inference process."""

import numpy as np

from stemlab.config import settings

MELBAND = "vocals_mel_band_roformer.ckpt"
BS = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
BETA4 = "melband_roformer_big_beta4.ckpt"
BS1296 = "model_bs_roformer_ep_368_sdr_12.9628.ckpt"
# An instrumental model (also an instrumental choice below); its other stem is the vocals.
RESURRECTION = "bs_roformer_instrumental_resurrection_unwa.ckpt"
# Different models make different errors, so their average beats any one alone.
CHECKPOINTS = {
    "melband": (MELBAND,),
    "bs": (BS,),
    "beta4": (BETA4,),
    "bs1296": (BS1296,),
    "resurrection": (RESURRECTION,),
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


# Models that output the instrumental directly, by the "Instruments from" choice that names them.
# Best first by the benchmark in AGENTS.md (a few points of SDR apart; none beat the mix minus the
# vocal ensemble there, so none is the default).
INSTRUMENTALS = {
    "direct_resurrection": RESURRECTION,
    "direct_inst_v2": "melband_roformer_inst_v2.ckpt",
    "direct_bleedless": "mel_band_roformer_instrumental_bleedless_v3_gabox.ckpt",
}


def _demix(mix: np.ndarray, filename: str) -> dict:
    """Every stem one Roformer checkpoint returns for a channel-first stereo float32 mix."""
    import torch
    from audio_separator.separator import Separator

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
    stems = separator.model_instance.demix(mix)
    del separator
    torch.cuda.empty_cache()
    return stems


def _need_cuda():
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("The Roformer pipeline requires CUDA. Use htdemucs_ft on CPU.")


def separate_vocals(mix: np.ndarray, choice: str, announce) -> np.ndarray:
    """Return the vocal estimate for a channel-first stereo float32 mix at 44.1 kHz."""
    _need_cuda()
    checkpoints = CHECKPOINTS[choice]
    estimates = []
    for number, filename in enumerate(checkpoints, start=1):
        announce(f"Separating vocals, model {number} of {len(checkpoints)}")
        estimates.append(vocals_of(_demix(mix, filename)))
    return np.mean(estimates, axis=0)


def separate_instrumental(mix: np.ndarray, choice: str, announce) -> np.ndarray:
    """Return the instrumental a dedicated model hears in a channel-first stereo float32 mix."""
    _need_cuda()
    announce("Separating the instrumental")
    stems = _demix(mix, INSTRUMENTALS[choice])
    # Checkpoints spell it "Instrumental", or just call it "other" beside "vocals".
    for wanted in (lambda name: "inst" in name, lambda name: "voc" not in name):
        for name, stem in stems.items():
            if wanted(name.lower()):
                return stem
    raise RuntimeError(f"Roformer model returned no instrumental stem (got {sorted(stems)}).")
