"""Isolated inference process. Heavy dependencies never load in the API."""

import argparse
import os
from pathlib import Path

import numpy as np
import soundfile as sf

from stemlab.config import settings
from stemlab.outputs import output_plan
from stemlab.separation import Stem


def separate(source: Path, output: Path, mode="all", keep=None) -> list[Stem]:
    plan = output_plan(mode, keep)
    os.environ.setdefault("TORCH_HOME", str(settings.data_dir / "models"))
    import torch
    from demucs.apply import apply_model
    from demucs.audio import convert_audio
    from demucs.pretrained import get_model

    torch.set_num_threads(settings.cpu_threads)
    device = settings.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA was requested but is unavailable. Install the cuda extra and driver."
        )
    model = get_model("htdemucs")
    model.eval()
    audio, rate = sf.read(source, dtype="float32", always_2d=True)
    mix = convert_audio(
        torch.from_numpy(audio.T.copy()), rate, model.samplerate, model.audio_channels
    )
    reference = mix.mean(0)
    mean, scale = reference.mean(), reference.std()
    label = torch.cuda.get_device_name(0) if device == "cuda" else "CPU"
    print(f"STAGE:Separating on {label}", flush=True)
    if scale < 1e-8:
        # Silence / constant signals cannot be normalized safely.
        separated = torch.zeros(len(model.sources), *mix.shape)
        separated[model.sources.index("other")] = mix
    else:
        with torch.inference_mode():
            separated = (
                apply_model(
                    model,
                    ((mix - mean) / scale)[None],
                    device=device,
                    shifts=0,
                    split=True,
                    overlap=0.25,
                    segment=7,
                    progress=False,
                )[0]
                * scale
                + mean
            )
    print("STAGE:Writing WAV stems", flush=True)
    return write_outputs(
        dict(zip(model.sources, separated.cpu().numpy(), strict=True)),
        model.samplerate,
        output,
        plan,
    )


def write_outputs(sources, sample_rate, output, plan):
    """Combine channel-first model estimates without changing relative gains."""
    output.mkdir(parents=True, exist_ok=True)
    # Float WAV preserves model output without clipping or individual stem normalization.
    files = []
    for group in plan:
        # Sum model sources before encoding; never normalize each source independently.
        signal = np.zeros_like(sources[group["sources"][0]])
        for name in group["sources"]:
            signal += sources[name]
        samples = signal.T
        if not np.isfinite(samples).all():
            raise ValueError("Model produced invalid samples")
        path = output / f"{group['id']}.wav"
        sf.write(path, samples, sample_rate, subtype="FLOAT")
        files.append(Stem(group["id"], path))
    return files


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", default="all")
    parser.add_argument("--keep")
    args = parser.parse_args()
    separate(args.source, args.output, args.mode, args.keep.split(",") if args.keep else None)
