"""BPM, Camelot key and a 4/4 downbeat for one track.

The full mix is measured here. A short htdemucs pass is optional and stays in the
process entry point, which is the only place that takes the GPU lock.
"""

import argparse
import fcntl
import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np
import soundfile as sf

from stemlab.config import settings

# Onset grid. The beat rate is refined from the span of accepted beats, not from this hop.
_N_FFT = 4096
_HOP = 512
_ISOLATION_SECONDS = 45.0
_MIN_BPM = 55.0
_MAX_BPM = 240.0
# Log-tempo preference centered on a sync tempo, wide enough that a steady click track
# separates from its half-time reading.
_SYNC_BPM = 120.0
_SYNC_WIDTH = 0.6
# A section this large that is off the winning grid is named in the warning.
_OFF_GRID = 0.1
_OCTAVE_TIE = 0.85
_KEY_MARGIN = 0.06
_KEY_FLOOR = 0.45
# (max - min) / mean of the chroma. A click track is flat; a chord is not.
_HARMONY_SPAN = 0.2
_GRID_WARNING = "Part of the track does not hold this grid."
_NO_TEMPO = "A steady tempo was not found."

# Krumhansl-Kessler profiles, tonic at pitch class 0 (C).
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
# Camelot code for each tonic pitch class. Names follow the wheel's usual spellings.
_MAJOR_CODE = ("8B", "3B", "10B", "5B", "12B", "7B", "2B", "9B", "4B", "11B", "6B", "1B")
_MINOR_CODE = ("5A", "12A", "7A", "2A", "9A", "4A", "11A", "6A", "1A", "8A", "3A", "10A")
_KEY_NAME = {
    "1A": "Ab minor",
    "2A": "Eb minor",
    "3A": "Bb minor",
    "4A": "F minor",
    "5A": "C minor",
    "6A": "G minor",
    "7A": "D minor",
    "8A": "A minor",
    "9A": "E minor",
    "10A": "B minor",
    "11A": "F# minor",
    "12A": "Db minor",
    "1B": "B major",
    "2B": "Gb major",
    "3B": "Db major",
    "4B": "Ab major",
    "5B": "Eb major",
    "6B": "Bb major",
    "7B": "F major",
    "8B": "C major",
    "9B": "G major",
    "10B": "D major",
    "11B": "A major",
    "12B": "E major",
}


@dataclass(frozen=True)
class Reading:
    """One track's tempo, key and grid. bpm is two decimals; warning is empty when it holds."""

    bpm: float | None
    camelot: str | None
    key_name: str | None
    downbeat: float | None
    warning: str

    def to_dict(self):
        return {
            "bpm": self.bpm,
            "camelot": self.camelot,
            "key_name": self.key_name,
            "downbeat": self.downbeat,
            "warning": self.warning,
        }


class _Tempo(NamedTuple):
    bpm: float | None
    downbeat: float | None
    disagrees: bool
    weak: bool


class _Key(NamedTuple):
    camelot: str | None
    key_name: str | None
    margin: float
    weak: bool


@contextmanager
def inference_lock():
    """Exclusive lock shared with a separation job so only one model is on the GPU."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with (settings.data_dir / "inference.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def measure(samples, sample_rate, announce, separate_window=None):
    """Return a Reading for float32 samples shaped (frames, channels).

    announce(stage) reports a stage. Tempo, phase and key are measured on the whole
    mix. separate_window(kind, start, end), when given, is asked for a weak tempo
    (kind "drums") or a weak key (kind "instrumental") on about 45 seconds. That
    slice is not a substitute for the full-song reading. This function does not
    import torch and does not take the GPU lock.
    """
    announce("Reading tempo and key")
    mono = _mono(samples)
    if sample_rate <= 0 or len(mono) == 0:
        return Reading(None, None, None, None, _NO_TEMPO)
    duration = len(mono) / sample_rate
    magnitude, flux, times = _spectrum(mono, sample_rate)
    beats, strengths = _beats(mono, sample_rate, flux, times)
    tempo = _tempo_of(sample_rate, flux, beats, strengths, duration)
    key = _key_of(magnitude, flux, sample_rate, duration)
    if separate_window is not None and tempo.weak:
        start, end = _loudest_span(flux, times, duration)
        separate_window("drums", start, end)
    if separate_window is not None and key.weak:
        start, end = _tonal_span(magnitude, times, duration)
        separate_window("instrumental", start, end)
    return _reading(tempo, key)


def _reading(tempo, key):
    if tempo.bpm is None:
        warning = _NO_TEMPO
    elif tempo.disagrees:
        warning = _GRID_WARNING
    else:
        warning = ""
    bpm = None if tempo.bpm is None else float(f"{tempo.bpm:.2f}")
    downbeat = None if tempo.downbeat is None else float(f"{tempo.downbeat:.4f}")
    # A close call between keys is not a reading. Isolation may replace it with a clear one.
    camelot = None if key.weak else key.camelot
    key_name = None if key.weak else key.key_name
    return Reading(bpm, camelot, key_name, downbeat, warning)


def _mono(samples):
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim == 1:
        return np.ascontiguousarray(audio)
    return np.ascontiguousarray(audio.mean(axis=1))


def _spectrum(mono, sample_rate):
    """Magnitude spectrogram and half-wave spectral flux.

    Frames are centered so a hit on the first sample sits under the window peak.
    """
    padded = np.pad(mono, (_N_FFT // 2, _N_FFT // 2))
    frame_count = 1 + len(mono) // _HOP
    while frame_count > 1 and (frame_count - 1) * _HOP + _N_FFT > len(padded):
        frame_count -= 1
    window = np.hanning(_N_FFT).astype(np.float32)
    batches = []
    view = np.lib.stride_tricks.as_strided(
        padded,
        shape=(frame_count, _N_FFT),
        strides=(padded.strides[0] * _HOP, padded.strides[0]),
    )
    for start in range(0, frame_count, 256):
        frames = np.array(view[start : start + 256], dtype=np.float32, copy=True)
        frames *= window
        batches.append(np.abs(np.fft.rfft(frames, axis=1)))
    magnitude = np.concatenate(batches, axis=0)
    previous = np.zeros((1, magnitude.shape[1]))
    flux = np.maximum(0.0, np.diff(magnitude, axis=0, prepend=previous)).sum(axis=1)
    times = np.arange(frame_count) * _HOP / sample_rate
    return magnitude, flux.astype(np.float32), times


def _beats(mono, sample_rate, flux, times):
    if len(flux) < 3 or float(np.max(flux)) <= 0:
        return np.array([]), np.array([])
    core = flux[1:-1]
    local = (core >= flux[:-2]) & (core > flux[2:])
    picked = list(np.flatnonzero(local) + 1)
    if flux[0] >= flux[1]:
        picked.insert(0, 0)
    if len(picked) == 0:
        return np.array([]), np.array([])
    heights = flux[np.array(picked)]
    # Scale the gate from the tall peaks, not the single loudest frame, so one
    # attack does not hide a steady click track sitting under a tone.
    keep_n = max(4, int(float(times[-1]) * 2))
    pool = heights if len(heights) <= keep_n else np.partition(heights, -keep_n)[-keep_n:]
    cutoff = 0.4 * float(np.median(pool))
    baseline = float(np.median(flux))
    if baseline > 0 and cutoff < 4 * baseline:
        return np.array([]), np.array([])
    picked = [index for index, height in zip(picked, heights, strict=True) if height >= cutoff]
    radius = _HOP * 2
    instants = []
    for index in picked:
        center = int(round(times[index] * sample_rate))
        lo = max(0, center - radius)
        hi = min(len(mono), center + radius + 1)
        if lo >= hi:
            continue
        instants.append((lo + int(np.argmax(np.abs(mono[lo:hi])))) / sample_rate)
    instants = np.array(sorted(instants), dtype=np.float64)
    kept_times = []
    kept_strength = []
    for instant in instants:
        sample = min(len(mono) - 1, max(0, int(round(instant * sample_rate))))
        strength = float(abs(mono[sample]))
        if kept_times and instant - kept_times[-1] < 0.2:
            if strength > kept_strength[-1]:
                kept_times[-1] = instant
                kept_strength[-1] = strength
            continue
        kept_times.append(instant)
        kept_strength.append(strength)
    return np.array(kept_times), np.array(kept_strength)


def _tempo_of(sample_rate, flux, beats, strengths, duration):
    """One tempo for the whole onset envelope, then the downbeat on that same span."""
    frame_rate = sample_rate / _HOP
    if duration < 2 or len(flux) <= 8:
        return _Tempo(None, None, False, True)
    rough, tied = _tempo_from_flux(flux, frame_rate)
    if rough is None:
        return _Tempo(None, None, False, True)
    bpm, downbeat = _refine(beats, strengths, rough, duration)
    disagrees = _disagrees(beats, bpm if bpm is not None else rough, duration)
    weak = disagrees or tied or bpm is None
    return _Tempo(bpm, downbeat, disagrees, weak)


def _tempo_from_flux(flux, frame_rate):
    if len(flux) < 8 or float(np.max(flux)) <= 0:
        return None, False
    centered = np.asarray(flux, dtype=np.float64)
    centered -= float(np.mean(centered))
    energy = float(np.dot(centered, centered))
    if energy <= 1e-12:
        return None, False
    corr = _autocorrelation(centered)
    min_lag = max(1, int(np.floor(frame_rate * 60 / _MAX_BPM)))
    max_lag = min(len(corr) - 2, int(np.ceil(frame_rate * 60 / _MIN_BPM)))
    if max_lag <= min_lag + 2:
        return None, False
    lags = np.arange(min_lag, max_lag + 1)
    bpms = 60.0 * frame_rate / lags
    prior = np.exp(-0.5 * (np.log2(bpms / _SYNC_BPM) / _SYNC_WIDTH) ** 2)
    scores = corr[lags] * prior
    best = int(np.argmax(scores))
    lag = _parabolic(corr, int(lags[best]))
    bpm = 60.0 * frame_rate / lag
    tied = False
    best_score = float(scores[best])
    for scale in (2, 0.5):
        other = int(round(lags[best] * scale))
        if other < min_lag or other > max_lag:
            continue
        other_bpm = 60.0 * frame_rate / other
        other_prior = float(np.exp(-0.5 * (np.log2(other_bpm / _SYNC_BPM) / _SYNC_WIDTH) ** 2))
        if float(corr[other]) * other_prior > _OCTAVE_TIE * best_score:
            tied = True
    return float(bpm), tied


def _autocorrelation(centered):
    """Positive lags of the autocorrelation. Every sample of centered contributes."""
    length = len(centered)
    size = 1 << (2 * length - 1).bit_length()
    spectrum = np.fft.rfft(centered, n=size)
    corr = np.fft.irfft(spectrum * np.conjugate(spectrum), n=size)[:length]
    return corr / np.arange(length, 0, -1)


def _parabolic(values, index):
    if index <= 0 or index >= len(values) - 1:
        return float(index)
    left, middle, right = float(values[index - 1]), float(values[index]), float(values[index + 1])
    denom = left - 2 * middle + right
    if abs(denom) < 1e-12:
        return float(index)
    delta = 0.5 * (left - right) / denom
    return index + float(np.clip(delta, -0.5, 0.5))


def _disagrees(beats, bpm, duration):
    """True when a substantial stretch of the whole track misses the full-song period."""
    if bpm is None or bpm <= 0 or duration <= 0 or len(beats) < 2:
        return False
    period = 60.0 / bpm
    off = 0.0
    for earlier, later in zip(beats, beats[1:]):
        gap = float(later - earlier)
        if gap <= 0:
            continue
        steps = int(round(gap / period))
        if steps < 1 or abs(gap / steps - period) > 0.08 * period:
            off += gap
    return off / duration >= _OFF_GRID


def _refine(beats, strengths, rough_bpm, duration):
    """BPM from the span of beats that sit on the winning period, then the downbeat."""
    if rough_bpm <= 0 or len(beats) < 4:
        return None, None
    period = 60.0 / rough_bpm
    chain = [0]
    best = [0]
    best_span = 0.0
    for index in range(1, len(beats)):
        gap = beats[index] - beats[chain[-1]]
        steps = int(round(gap / period))
        if steps >= 1 and abs(gap / steps - period) <= 0.08 * period:
            chain.append(index)
            continue
        span = beats[chain[-1]] - beats[chain[0]]
        if span > best_span:
            best, best_span = chain, span
        chain = [index]
    span = beats[chain[-1]] - beats[chain[0]]
    if span > best_span:
        best = chain
    if len(best) < 4:
        return None, None
    first, last = beats[best[0]], beats[best[-1]]
    steps = int(round((last - first) / period))
    if steps < 1 or last <= first:
        return None, None
    bpm = 60.0 * steps / (last - first)
    downbeat = _downbeat(beats[best], strengths[best], bpm, duration)
    return bpm, downbeat


def _downbeat(times, strengths, bpm, duration):
    if len(times) == 0 or bpm <= 0:
        return None
    period = 60.0 / bpm
    origin = float(times[0])
    indices = np.round((times - origin) / period).astype(int)
    scores = np.zeros(4)
    for index, strength in zip(indices, strengths, strict=True):
        scores[int(index) % 4] += float(strength)
    if float(scores.max()) <= 1.12 * float(np.mean(scores)):
        phase = int(indices[0]) % 4
    else:
        phase = int(np.argmax(scores))
    matches = np.flatnonzero((indices % 4) == phase)
    anchor = float(times[matches[0]])
    bar = 4 * period
    first = anchor - np.floor(anchor / bar + 1e-9) * bar
    if first < -1e-3:
        first += bar
    first = max(0.0, float(first))
    if first > duration:
        return None
    return first


def _key_of(magnitude, flux, sample_rate, duration):
    """One key from the chroma of every frame. A short stretch does not get its own vote."""
    chroma = _chroma(magnitude, flux, sample_rate)
    best = _best_key(chroma)
    if duration < 2 or best is None:
        return _Key(None, None, 0.0, True)
    code, _name, margin = best
    weak = margin < _KEY_MARGIN
    return _Key(code, _KEY_NAME[code], margin, weak)


def _best_key(chroma):
    if chroma is None or float(np.sum(chroma)) <= 0:
        return None
    level = float(np.mean(chroma))
    if level <= 0 or float(np.max(chroma) - np.min(chroma)) / level < _HARMONY_SPAN:
        return None
    scored = []
    for shift in range(12):
        scored.append((_corr(chroma, np.roll(_MAJOR, shift)), _MAJOR_CODE[shift]))
        scored.append((_corr(chroma, np.roll(_MINOR, shift)), _MINOR_CODE[shift]))
    scored.sort(reverse=True)
    margin = scored[0][0] - scored[1][0]
    if scored[0][0] < _KEY_FLOOR:
        return None
    return scored[0][1], _KEY_NAME[scored[0][1]], margin


def _chroma(magnitude, flux, sample_rate):
    if len(magnitude) == 0:
        return None
    weights = magnitude
    if len(flux) == len(magnitude) and float(np.max(flux)) > 0:
        cutoff = float(np.median(flux) + 4 * np.std(flux))
        tonal = flux < cutoff
        if int(np.sum(tonal)) >= 4:
            weights = magnitude[tonal]
    # One sample per semitone. Summing raw FFT bins favors pitch classes that own more bins.
    frame_sum = weights.sum(axis=0)
    chroma = np.zeros(12, dtype=np.float64)
    for midi in range(36, 96):
        freq = 440.0 * 2.0 ** ((midi - 69) / 12.0)
        bin_index = int(round(freq * _N_FFT / sample_rate))
        if bin_index <= 0 or bin_index >= len(frame_sum) - 1:
            continue
        chroma[midi % 12] += float(frame_sum[bin_index - 1 : bin_index + 2].max())
    return chroma


def _corr(left, right):
    left = left - float(np.mean(left))
    right = right - float(np.mean(right))
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(left, right) / denom)


def _loudest_span(flux, times, duration):
    return _span(flux, times, duration, high=True)


def _tonal_span(magnitude, times, duration):
    freqs_ready = magnitude.shape[1] if magnitude.ndim == 2 else 0
    if freqs_ready == 0 or duration <= _ISOLATION_SECONDS:
        return 0.0, float(duration)
    # Concentration of energy in the loudest bin of each frame: a tonal stretch, not a hit.
    peak = magnitude.max(axis=1)
    total = magnitude.sum(axis=1) + 1e-12
    return _span(peak / total, times, duration, high=True)


def _span(activity, times, duration, high):
    if duration <= _ISOLATION_SECONDS or len(times) < 2:
        return 0.0, float(duration)
    width = max(1, int(round(_ISOLATION_SECONDS / np.median(np.diff(times)))))
    if width >= len(activity):
        return 0.0, float(duration)
    scored = np.convolve(activity, np.ones(width), mode="valid")
    index = int(np.argmax(scored) if high else np.argmin(scored))
    start = float(times[min(index, len(times) - 1)])
    end = min(float(duration), start + _ISOLATION_SECONDS)
    return start, end


def _separator(samples, sample_rate, announce):
    """separate_window for the process entry point. The lock is taken only here."""

    def separate_window(kind, start, end):
        announce("Waiting for the separator")
        with inference_lock():
            stage = "Isolating drums and bass" if kind == "drums" else "Isolating the instrumental"
            announce(stage)
            first = max(0, int(round(start * sample_rate)))
            last = min(len(samples), int(round(end * sample_rate)))
            from stemlab.inference import isolate_window

            return isolate_window(samples[first:last], sample_rate, kind)

    return separate_window


def _announce(stage):
    print(f"STAGE:{stage}", file=sys.stderr, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read BPM, key and downbeat for one audio file.")
    parser.add_argument("source", type=Path)
    args = parser.parse_args(argv)
    _announce("Checking the file")
    samples, sample_rate = sf.read(args.source, dtype="float32", always_2d=True)
    reading = measure(samples, sample_rate, _announce, _separator(samples, sample_rate, _announce))
    json.dump(reading.to_dict(), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
