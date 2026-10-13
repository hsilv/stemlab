"""Write one backing track with ACE-Step; the process a "generate" job runs.

Run with the ACE-Step environment's interpreter (see config.ace_step_dir) and `-P`, so that this
folder's modules cannot shadow ACE-Step's own imports. It therefore imports nothing from stemlab.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

# The slow sft model (50 steps) with the language model sounds far better than the 8-step turbo
# model without it; about 10 GB of VRAM at its peak.
MODEL = "acestep-v15-sft"
LANGUAGE_MODEL = "acestep-5Hz-lm-1.7B"
STEPS = 50
# A longer reference costs memory without telling the model more about the style.
REFERENCE_SECONDS = 30


def announce(stage):
    print(f"STAGE:{stage}", file=sys.stderr, flush=True)


def reference_excerpt(path, folder):
    """The middle REFERENCE_SECONDS of the reference, as a WAV in folder."""
    with sf.SoundFile(path) as audio:
        length = REFERENCE_SECONDS * audio.samplerate
        audio.seek(max(0, (audio.frames - length) // 2))
        block = audio.read(length, dtype="float32", always_2d=True)
        rate = audio.samplerate
    excerpt = Path(folder) / "reference.wav"
    sf.write(excerpt, block, rate)
    return excerpt


def parse(argv=None):
    """The arguments, with every path made absolute: main changes directory into ACE-Step."""
    parser = argparse.ArgumentParser(description="Generate a backing track with ACE-Step.")
    parser.add_argument("output", type=Path, help="folder to write backing.flac into")
    parser.add_argument("--ace-dir", type=Path, required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args(argv)
    args.output = args.output.resolve()
    args.ace_dir = args.ace_dir.resolve()
    args.reference = args.reference.resolve() if args.reference else None
    return args


def main(argv=None):
    args = parse(argv)

    checkout = args.ace_dir / "ace"
    os.environ["ACESTEP_CHECKPOINTS_DIR"] = str(args.ace_dir / "checkpoints")
    os.chdir(checkout)
    # Without this PyTorch keeps about 1 GB of freed memory it cannot reuse; this keeps the peak
    # near 12 GB with a reference. It must be set before PyTorch starts.
    os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
    announce("Loading ACE-Step")
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.llm_inference import LLMHandler
    from loguru import logger

    # Its progress chatter would push the STAGE lines out of the part of the log the worker reads.
    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    import torch

    # The language model loads through a full-precision copy, which needs about 7 GB for a
    # moment before it settles at 3.5 GB: load it first, while the GPU is empty.
    language = LLMHandler()
    message, ready = language.initialize(
        checkpoint_dir=str(args.ace_dir / "checkpoints"),
        lm_model_path=LANGUAGE_MODEL,
        backend="pt",
        device="cuda",
        dtype=torch.bfloat16,
    )
    if not ready:
        raise RuntimeError(f"ACE-Step's language model did not start: {message}")
    handler = AceStepHandler()
    message, ready = handler.initialize_service(
        project_root=str(checkout), config_path=MODEL, device="cuda"
    )
    if not ready:
        raise RuntimeError(f"ACE-Step did not start: {message}")
    with tempfile.TemporaryDirectory() as scratch:
        reference = reference_excerpt(args.reference, scratch) if args.reference else None
        params = GenerationParams(
            caption=args.prompt,
            lyrics="[Instrumental]",
            instrumental=True,
            reference_audio=str(reference) if reference else None,
            duration=args.duration,
            seed=args.seed,
            inference_steps=STEPS,
            thinking=True,
        )
        announce("Generating")
        result = generate_music(
            handler,
            language,
            params,
            GenerationConfig(batch_size=1, audio_format="flac"),
            save_dir=scratch,
        )
    if not result.success or not result.audios:
        raise RuntimeError(f"ACE-Step failed: {result.error}")
    announce("Writing FLAC")
    audio = result.audios[0]
    signal = audio["tensor"].float().cpu().numpy()
    if not np.isfinite(signal).all():
        raise ValueError("Model produced invalid samples")
    args.output.mkdir(parents=True, exist_ok=True)
    sf.write(
        args.output / "backing.flac",
        signal.T,
        audio["sample_rate"],
        format="FLAC",
        subtype="PCM_24",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
