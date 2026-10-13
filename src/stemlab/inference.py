"""Isolated inference process. Heavy dependencies never load in the API."""

import argparse
import logging
import os
from pathlib import Path

import numpy as np
import soundfile as sf

from stemlab.config import DEMUCS_MODELS, instrumental_only, settings
from stemlab.outputs import STEM_SUFFIX, is_instrumental, output_plan
from stemlab.separation import Stem

# Short crossfade at the inner edges of a section so the switch to the original does not click.
FADE_SECONDS = 0.01
# Just under full scale so the 24-bit encoder never rounds a peak past it.
FULL_SCALE = 0.999
# Extra audio read on each side of a section so the models are not cut cold at its edges.
CONTEXT_SECONDS = 5


def read_section(source, start=None, end=None):
    """Read audio (frames, channels) with context, plus (lead, length) seconds to keep.

    The trim is None for the whole track.
    """
    with sf.SoundFile(source) as audio:
        rate, frames = audio.samplerate, audio.frames
    if start is None:
        return (*sf.read(source, dtype="float32", always_2d=True), None)
    first = max(0, round((start - CONTEXT_SECONDS) * rate))
    last = min(frames, round((end + CONTEXT_SECONDS) * rate))
    data, rate = sf.read(source, start=first, stop=last, dtype="float32", always_2d=True)
    return data, rate, (start - first / rate, end - start)


def parse_ranges(text):
    """Parse '0-5,10-15' into [(start, end), ...]."""
    if not text or not text.strip():
        raise ValueError("Name each range as start-end, separated by commas.")
    spans = []
    for part in text.split(","):
        piece = part.strip()
        if piece.count("-") != 1:
            raise ValueError("Name each range as start-end, separated by commas.")
        raw_start, raw_end = piece.split("-")
        try:
            spans.append((float(raw_start), float(raw_end)))
        except ValueError as exc:
            raise ValueError("Range times must be numbers.") from exc
    return spans


def separate(
    source: Path,
    output: Path,
    mode="all",
    keep=None,
    model_name=settings.model,
    vocals_from=settings.vocals,
    instruments_from=settings.instruments_from,
    shifts=settings.shifts,
    overlap=settings.overlap,
    start=None,
    end=None,
    ranges=None,
) -> list[Stem]:
    plan = output_plan(mode, keep)
    spans = list(ranges) if ranges else None
    if not spans and (start is not None or end is not None):
        spans = [(start, end)]
    models, device, model = open_models(model_name)
    if spans and len(spans) > 1:
        return separate_ranges(
            source,
            output,
            mode,
            plan,
            models,
            device,
            model,
            vocals_from,
            instruments_from,
            shifts,
            overlap,
            spans,
        )
    start, end = spans[0] if spans else (None, None)
    audio, rate, trim = read_section(source, start, end)
    separated = estimate(
        audio,
        rate,
        models,
        device,
        model,
        plan,
        vocals_from,
        instruments_from,
        shifts,
        overlap,
        stage,
    )
    if trim:
        first = round(trim[0] * model.samplerate)
        separated = separated[..., first : first + round(trim[1] * model.samplerate)]
    # A single result (not all stems) keeps the whole song: the effect only covers the section.
    backdrop = None
    if trim and mode != "all":
        stage("Restoring the rest of the song")
        backdrop = song_at_model_rate(source, model)
    stage("Writing FLAC stems")
    return write_outputs(
        dict(zip(model.sources, separated.cpu().numpy(), strict=True)),
        model.samplerate,
        output,
        plan,
        backdrop,
        round((start or 0) * model.samplerate),
    )


def open_models(model_name):
    os.environ.setdefault("TORCH_HOME", str(settings.data_dir / "models"))
    import torch
    from demucs.pretrained import get_model

    torch.set_num_threads(settings.cpu_threads)
    device = settings.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA was requested but is unavailable. Install the cuda extra and driver."
        )
    models = [get_model(name) for name in DEMUCS_MODELS[model_name]]
    for member in models:
        member.eval()
    return models, device, models[0]


def song_at_model_rate(source, model):
    import torch
    from demucs.audio import convert_audio

    everything, everything_rate = sf.read(source, dtype="float32", always_2d=True)
    return convert_audio(
        torch.from_numpy(everything.T.copy()),
        everything_rate,
        model.samplerate,
        model.audio_channels,
    ).numpy()


def estimate(
    audio,
    rate,
    models,
    device,
    model,
    plan,
    vocals_from,
    instruments_from,
    shifts,
    overlap,
    announce,
):
    """Return model-rate stem estimates for one buffer. announce(text) reports the stage."""
    import torch
    from demucs.audio import convert_audio

    mix = convert_audio(
        torch.from_numpy(audio.T.copy()), rate, model.samplerate, model.audio_channels
    )
    label = torch.cuda.get_device_name(0) if device == "cuda" else "CPU"
    announce(f"Separating on {label}")
    sources = model.sources

    def demucs(heard, wanted):
        """Average the chosen Demucs models' estimates of the wanted stems."""
        return torch.stack(
            [run_demucs(member, heard, device, shifts, overlap, wanted) for member in models]
        ).mean(0)

    needed = {name for group in plan for name in group["sources"]}
    instruments = needed - {"vocals"}
    if mix.mean(0).std() < 1e-8:
        # Silence / constant signals cannot be normalized safely.
        separated = torch.zeros(len(sources), *mix.shape)
        separated[sources.index("other")] = mix
    elif instruments_from.startswith("direct_") and is_instrumental(plan):
        from stemlab.roformer import separate_instrumental

        # One model hears the whole instrumental; write_outputs sums drums, bass and other, so it
        # can all sit in one of them.
        separated = torch.zeros(len(sources), *mix.shape)
        separated[sources.index("other")] = torch.from_numpy(
            separate_instrumental(mix.numpy(), instruments_from, announce)
        )
    elif vocals_from == "demucs":
        separated = demucs(mix, needed)
    else:
        from stemlab.roformer import separate_vocals

        # Skip whatever the requested output does not use.
        vocals = None
        if instrumental_only(instruments_from) and not is_instrumental(plan):
            raise ValueError("That choice only works for No vocals.")
        if "vocals" in needed or (instruments and instruments_from != "mix"):
            vocals = torch.from_numpy(separate_vocals(mix.numpy(), vocals_from, announce))
        separated = torch.zeros(len(sources), *mix.shape)
        if instruments and instruments_from == "inverse":
            # Everything the vocal model left in the track. write_outputs sums drums, bass and
            # other, so it can all sit in one of them.
            separated[sources.index("other")] = mix - vocals
        elif instruments:
            announce("Separating drums, bass and other instruments")
            # From the residual, Demucs sees no vocals at all, so they cannot bleed into its stems.
            heard = mix - vocals if instruments_from == "residual" else mix
            # clone(): inference-mode tensors cannot be modified in place outside it.
            separated = demucs(heard, instruments).clone()
        if "vocals" in needed:
            separated[sources.index("vocals")] = vocals
    return separated


def separate_ranges(
    source,
    output,
    mode,
    plan,
    models,
    device,
    model,
    vocals_from,
    instruments_from,
    shifts,
    overlap,
    spans,
):
    """Separate each range and lay it back on the song. One model load, one pass per range."""
    pieces = []
    total = len(spans)
    for index, (start, end) in enumerate(spans, start=1):

        def announce(text, index=index):
            stage(f"Range {index} of {total}: {text}")

        audio, rate, trim = read_section(source, start, end)
        separated = estimate(
            audio,
            rate,
            models,
            device,
            model,
            plan,
            vocals_from,
            instruments_from,
            shifts,
            overlap,
            announce,
        )
        if trim:
            first = round(trim[0] * model.samplerate)
            separated = separated[..., first : first + round(trim[1] * model.samplerate)]
        pieces.append(
            (
                dict(zip(model.sources, separated.cpu().numpy(), strict=True)),
                round(start * model.samplerate),
            )
        )
    song = song_at_model_rate(source, model)
    channels, frames = song.shape
    output.mkdir(parents=True, exist_ok=True)
    if mode != "all":
        stage("Restoring the rest of the song")
        group = plan[0]
        parts = []
        for sources, offset in pieces:
            signal = np.zeros((channels, sources[group["sources"][0]].shape[1]), dtype="float32")
            for name in group["sources"]:
                signal += sources[name]
            parts.append((signal, offset))
        laid = [(lay(song, parts, model.samplerate), group)]
    else:
        laid = []
        for group in plan:
            name = group["sources"][0]
            base = np.zeros((channels, frames), dtype="float32")
            laid.append(
                (
                    lay(
                        base,
                        [(sources[name], offset) for sources, offset in pieces],
                        model.samplerate,
                    ),
                    group,
                )
            )
    stage("Writing FLAC stems")
    return encode_all(laid, model.samplerate, output)


def stage(text):
    print(f"STAGE:{text}", flush=True)


def restrict(model, wanted):
    """Keep only the models of a bag that contribute to the wanted stems.

    htdemucs_ft is a bag with one model per stem, so this skips the others.
    """
    from demucs.apply import BagOfModels

    if not isinstance(model, BagOfModels):
        return model
    stems = [model.sources.index(name) for name in wanted]
    keep = [i for i, row in enumerate(model.weights) if any(row[k] for k in stems)]
    return BagOfModels([model.models[i] for i in keep], [model.weights[i] for i in keep])


def run_demucs(model, mix, device, shifts, overlap, wanted):
    """Return Demucs estimates for a channel-first mix, undoing the input standardization.

    Only the wanted stems are computed; the others are zeros.
    """
    import torch
    from demucs.apply import apply_model

    sources = model.sources
    model = restrict(model, wanted)

    mean, scale = mix.mean(0).mean(), mix.mean(0).std()
    if scale < 1e-8:
        return torch.zeros(len(sources), *mix.shape)
    with torch.inference_mode():
        estimates = (
            apply_model(
                model,
                ((mix - mean) / scale)[None],
                device=device,
                shifts=shifts,
                split=True,
                overlap=overlap,
                segment=7,
                progress=False,
            )[0]
            * scale
            + mean
        )
        # Stems from models that were left out are undefined (0/0), so replace them outright.
        keep = torch.tensor([name in wanted for name in sources], device=estimates.device)
        return torch.where(keep[:, None, None], estimates, torch.zeros_like(estimates))


def lay(base, parts, sample_rate):
    """Place each (signal, offset) onto base, crossfading only edges inside the song."""
    result = base
    for signal, offset in parts:
        result = splice(result, signal, offset, sample_rate)
    return result


def splice(whole, part, offset, sample_rate):
    """Return whole with part placed at offset, crossfading only edges inside the song."""
    length = min(part.shape[1], whole.shape[1] - offset)
    part = part[:, :length]
    fade = min(round(FADE_SECONDS * sample_rate), length // 2)
    ramp = np.linspace(0, 1, fade, endpoint=False, dtype=whole.dtype)
    weight = np.ones(length, dtype=whole.dtype)
    if offset > 0:
        weight[:fade] = ramp
    if offset + length < whole.shape[1]:
        weight[length - fade :] = ramp[::-1]
    result = whole.copy()
    result[:, offset : offset + length] = (
        weight * part + (1 - weight) * whole[:, offset : offset + length]
    )
    return result


def write_outputs(sources, sample_rate, output, plan, backdrop=None, offset=0):
    """Combine channel-first model estimates without changing relative gains.

    With a backdrop (the original song), the estimates replace it starting at offset.
    """
    output.mkdir(parents=True, exist_ok=True)
    laid = []
    for group in plan:
        # Sum model sources before encoding; never normalize each source independently.
        signal = np.zeros_like(sources[group["sources"][0]])
        for name in group["sources"]:
            signal += sources[name]
        if backdrop is not None:
            signal = splice(backdrop, signal, offset, sample_rate)
        laid.append((signal, group))
    return encode_all(laid, sample_rate, output)


def isolate_stems(audio, sample_rate, model_name="htdemucs", shifts=0, overlap=0.25):
    """The four stems of one in-memory buffer, each channel-first at its sample rate.

    audio is float32 (frames, channels). Nothing is written. Used for the short stretches an
    extended edit loops, so only those are ever separated.
    """
    import torch
    from demucs.audio import convert_audio

    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 1:
        audio = audio[:, None]
    channels, frames = audio.shape[1], audio.shape[0]
    _models, device, model = open_models(model_name)
    mix = convert_audio(
        torch.from_numpy(np.ascontiguousarray(audio.T)),
        sample_rate,
        model.samplerate,
        model.audio_channels,
    )
    estimates = run_demucs(model, mix, device, shifts, overlap, set(model.sources))
    stems = {}
    for name, estimate in zip(model.sources, estimates, strict=True):
        back = convert_audio(estimate.detach().cpu(), model.samplerate, sample_rate, channels)
        stem = np.zeros((channels, frames), dtype=np.float32)
        count = min(frames, back.shape[1])
        stem[:, :count] = back.numpy()[:, :count]
        stems[name] = stem
    return stems


def separate_fragment(
    audio, sample_rate, wanted, inverse, model_name, vocals_from, shifts, overlap, announce=None
):
    """{name: (channels, frames)} for the wanted stems of one in-memory buffer.

    audio is float32 (frames, channels). The voice comes from vocals_from (Demucs or a Roformer
    choice); the instruments from Demucs on the mix. With inverse, the three instruments come as
    one stem, "instrumental": the buffer minus the voice, so nothing the voice model leaves
    out is lost. Used by manual extended edits, where each fragment has its own choices.
    """
    import torch
    from demucs.audio import convert_audio

    announce = announce or stage
    audio = np.asarray(audio, dtype=np.float32)
    channels, frames = audio.shape[1], audio.shape[0]
    models, device, model = open_models(model_name)
    mix = convert_audio(
        torch.from_numpy(np.ascontiguousarray(audio.T)),
        sample_rate,
        model.samplerate,
        model.audio_channels,
    )
    sources = list(wanted)
    plan = [{"id": "fragment", "sources": ["vocals"] if inverse else sources}]
    separated = estimate(
        audio,
        sample_rate,
        models,
        device,
        model,
        plan,
        vocals_from,
        "mix",
        shifts,
        overlap,
        announce,
    )

    def back(stem):
        out = convert_audio(stem.detach().cpu(), model.samplerate, sample_rate, channels).numpy()
        fitted = np.zeros((channels, frames), dtype=np.float32)
        count = min(frames, out.shape[1])
        fitted[:, :count] = out[:, :count]
        return fitted

    if inverse:
        return {"instrumental": back(mix - separated[model.sources.index("vocals")])}
    return {name: back(separated[model.sources.index(name)]) for name in sources}


def isolate_window(audio, sample_rate, kind):
    """Return drums plus bass, or the harmonic stems (bass plus other), for one in-memory buffer.

    Plain htdemucs, no shifts. Nothing is written. audio is float32 (frames, channels)
    and the result matches that shape and sample rate.
    """
    import torch
    from demucs.audio import convert_audio

    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 1:
        audio = audio[:, None]
    if kind == "drums":
        wanted = {"drums", "bass"}
    elif kind == "harmonic":
        wanted = {"bass", "other"}
    else:
        raise ValueError("Window kind must be drums or harmonic.")
    channels, frames = audio.shape[1], audio.shape[0]
    _models, device, model = open_models("htdemucs")
    mix = convert_audio(
        torch.from_numpy(np.ascontiguousarray(audio.T)),
        sample_rate,
        model.samplerate,
        model.audio_channels,
    )
    estimates = run_demucs(model, mix, device, shifts=0, overlap=0.25, wanted=wanted)
    names = list(model.sources)
    if kind == "drums":
        stem = estimates[names.index("drums")] + estimates[names.index("bass")]
    else:
        stem = estimates[names.index("bass")] + estimates[names.index("other")]
    back = convert_audio(stem.detach().cpu(), model.samplerate, sample_rate, channels)
    out = np.ascontiguousarray(back.numpy().T, dtype=np.float32)
    # This load exists only for the window. Drop it once the buffer is on CPU.
    del _models, model, mix, estimates, stem, back
    torch.cuda.empty_cache()
    if len(out) == frames:
        return out
    fitted = np.zeros((frames, channels), dtype=np.float32)
    count = min(frames, len(out))
    fitted[:count] = out[:count]
    return fitted


_beat_tracker = None


def track_beats(audio, sample_rate):
    """(beats, downbeats) in seconds from the Beat This! network, or None if it cannot run.

    The network is small and does not take the GPU lock. It needs the optional beat-this
    package and, the first time, a download of its weights into the model cache; without
    either, the caller falls back to measuring the beat from the signal.
    """
    global _beat_tracker
    try:
        if _beat_tracker is None:
            os.environ.setdefault("TORCH_HOME", str(settings.data_dir / "models"))
            import torch
            from beat_this.inference import Audio2Beats

            device = settings.device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            _beat_tracker = Audio2Beats(checkpoint_path="final0", device=device)
        beats, downbeats = _beat_tracker(np.asarray(audio, dtype=np.float32), sample_rate)
    except Exception:
        logging.getLogger(__name__).exception("Beat tracking unavailable")
        return None
    return np.asarray(beats, dtype=np.float64), np.asarray(downbeats, dtype=np.float64)


def encode_all(laid, sample_rate, output):
    """Write (channel-first signal, group) pairs as 24-bit FLAC, lossless at a third of float WAV.

    Integer audio cannot exceed full scale, so when any output would, all of them share one
    gain. Relative levels stay intact and nothing clips; without overshoot the gain is 1.
    """
    output.mkdir(parents=True, exist_ok=True)
    if not all(np.isfinite(signal).all() for signal, _ in laid):
        raise ValueError("Model produced invalid samples")
    peak = max(float(np.max(np.abs(signal))) for signal, _ in laid)
    gain = min(1.0, FULL_SCALE / peak) if peak > 0 else 1.0
    files = []
    for signal, group in laid:
        path = output / f"{group['id']}{STEM_SUFFIX}"
        sf.write(path, (signal * gain).T, sample_rate, format="FLAC", subtype="PCM_24")
        files.append(Stem(group["id"], path))
    return files


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", default="all")
    parser.add_argument("--keep")
    parser.add_argument("--model", default=settings.model)
    parser.add_argument("--vocals", default=settings.vocals)
    parser.add_argument("--instruments-from", default=settings.instruments_from)
    parser.add_argument("--shifts", type=int, default=settings.shifts)
    parser.add_argument("--overlap", type=float, default=settings.overlap)
    parser.add_argument("--start", type=float)
    parser.add_argument("--end", type=float)
    parser.add_argument("--ranges")
    args = parser.parse_args()
    separate(
        args.source,
        args.output,
        args.mode,
        args.keep.split(",") if args.keep else None,
        args.model,
        args.vocals,
        args.instruments_from,
        args.shifts,
        args.overlap,
        args.start,
        args.end,
        parse_ranges(args.ranges) if args.ranges else None,
    )
