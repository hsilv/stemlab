"""BPM, Camelot key and a 4/4 downbeat for one track.

The full mix is measured here. A short htdemucs pass is optional and stays in the
process entry point, which is the only place that takes the GPU lock.

Tempo: the Beat This! network, when it can run, says which pulse is the beat and which
beats start a bar (it does not confuse a 3-3-2 dembow with a faster tempo). A
log-compressed multiband onset envelope then locks the period and phase to the audible
hits, by a comb fold and a least-squares fit, for a sub-frame BPM. Without the network
the envelope's autocorrelation, weighted toward a tempo prior, chooses the beat.
Key: tuning-corrected peak chroma from a long-window spectrum with percussion
median-filtered out, taken from the isolated bass and other stems when a separator is
available, scored against two key-profile sets.
"""

import argparse
import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np
import soundfile as sf

from stemlab import filelock
from stemlab.config import settings

# How much audio a separator is asked about, by kind. Drums settle a tempo in less time than
# harmony needs to settle a key.
_WINDOW_SECONDS = {"drums": 45.0, "harmonic": 90.0}
# The GPU belongs to a running separation job first; analysis waits this long, then goes on
# with the full mix alone.
_LOCK_WAIT_SECONDS = 30.0
_MIN_BPM = 55.0
_MAX_BPM = 240.0
# Log-tempo preference centered on a sync tempo, wide enough that a steady click track
# separates from its half-time reading.
_SYNC_BPM = 120.0
_SYNC_WIDTH = 0.6
_OCTAVE_TIE = 0.85
# Onset envelope.
_ONSET_WINDOW = 0.046
_ONSET_HOP = 0.010
_BANDS = 40
_BAND_LOW_HZ = 30.0
_BAND_HIGH_HZ = 12000.0
_BASS_HZ = 200.0
_DYNAMIC_RANGE_DB = 60.0
_LOCAL_MEAN_SECONDS = 1.0
# Grid fit.
_FOLD_BINS = 64
_FIT_WINDOW = 0.15
# Share of a beat a peak may sit from the fit; it narrows on each pass.
_FIT_TOLERANCES = (0.08, 0.05, 0.03, 0.03)
_MIN_FIT_BEATS = 8
# A segment of this many beats holds the grid when its onsets sit on it.
_SEGMENT_BEATS = 16
_SEGMENT_QUIET = 0.25
# Least share of a segment's onset energy that must land within a frame of the grid.
_ON_GRID_SHARE = 0.15
# Attack search around a beat, and the smoothing that keeps a hit from being noise.
_FIT_AGREE = 0.003
# Flux lands before the hit, so a hit on the very first sample sits this far before frame 0.
_LEAD_FRAMES = 4
_ATTACK_RADIUS = 0.04
_ATTACK_SMOOTH = 0.002
# A section this large that is off the winning grid is named in the warning.
_OFF_GRID = 0.1
_DOWNBEAT_FLAT = 1.12
# Share of the network's downbeats that must agree on which beat of four starts a bar.
_DOWNBEAT_VOTE = 0.6
# A network beat is on the grid within this share of a beat; a stretch holds the grid when at
# least this share of its network beats are.
_TRACKED_TOLERANCE = 0.2
_TRACKED_SHARE = 0.5
# Beats the network must find before its tempo is taken over the signal's own.
_MIN_TRACKED_BEATS = 16
# Key. Window is long for low-note resolution; hop is half of it.
_TONAL_WINDOW = 0.186
_TONAL_LOW_HZ = 60.0
_TONAL_HIGH_HZ = 2000.0
_HARMONIC_FRAMES = 9
_PEAK_FLOOR = 0.1
_TUNING_BINS = 25
# A runner-up key this close behind the winner is a close call, unless the two mix together
# anyway (see _compatible): then the winner is as good a reading as any.
_KEY_MARGIN = 0.05
# ...and only when the winner fits well: a noisy, harmony-less chroma also has a compatible
# runner-up close behind, but never fits a key this closely.
_COMPATIBLE_FIT = 0.6
_KEY_FLOOR = 0.45
# (max - min) / mean of the chroma. A click track is flat; a chord is not.
_HARMONY_SPAN = 0.2
# Mood. Each measure is stretched onto 0..1 between a low and a high that a typical track
# falls between, then weighted. Valence is mostly mode (major lifts it) with brightness,
# consonance and tempo; energy is tempo, loudness, onset activity and brightness.
_MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11)
_MINOR_STEPS = (0, 2, 3, 5, 7, 8, 10)
_MOOD_RANGE = {
    "lean": (-0.2, 0.2),
    "bpm": (70.0, 140.0),
    "loud": (-30.0, -9.0),
    "active": (0.2, 0.65),
    "bright": (2000.0, 5000.0),
    "diatonic": (0.55, 0.9),
}
_MODE_WEIGHT = 0.4
_VALENCE_WEIGHTS = {"bright": 0.25, "diatonic": 0.2, "bpm": 0.15}
_ENERGY_WEIGHTS = {"bpm": 0.3, "loud": 0.3, "active": 0.25, "bright": 0.15}
_GRID_WARNING = "Part of the track does not hold this grid."
_NO_TEMPO = "A steady tempo was not found."

# Key profiles, tonic at pitch class 0 (C): Krumhansl-Kessler and Temperley. Their
# correlations are averaged so one profile's bias does not decide a close call.
_PROFILES = (
    (
        np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]),
        np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]),
    ),
    (
        np.array([5.0, 2.0, 3.5, 2.0, 4.5, 4.0, 2.0, 4.5, 2.0, 3.5, 1.5, 4.0]),
        np.array([5.0, 2.0, 3.5, 4.5, 2.0, 4.0, 2.0, 4.5, 3.5, 2.0, 1.5, 4.0]),
    ),
)
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
    # Feeling of the music, each 0 to 1: valence (dark to bright) and energy (calm to driving).
    valence: float | None = None
    energy: float | None = None

    def to_dict(self):
        return {
            "bpm": self.bpm,
            "camelot": self.camelot,
            "key_name": self.key_name,
            "downbeat": self.downbeat,
            "warning": self.warning,
            "valence": self.valence,
            "energy": self.energy,
        }


class _Onsets(NamedTuple):
    """Onset strength per frame: all bands, and the bass bands alone."""

    full: np.ndarray
    bass: np.ndarray
    frame_rate: float
    mono: np.ndarray
    sample_rate: int


class _Tempo(NamedTuple):
    bpm: float | None
    downbeat: float | None
    disagrees: bool
    weak: bool
    # The other octave when it scored nearly as well as the winner. Isolation may pick it.
    rival: float | None


class _Tonal(NamedTuple):
    chroma: np.ndarray
    times: np.ndarray
    # Share of each frame's chroma held by its strongest pitch class.
    focus: np.ndarray


class _Key(NamedTuple):
    camelot: str | None
    key_name: str | None
    weak: bool
    # Best major fit less best minor fit: positive leans major, negative minor, near zero is
    # a toss-up between relative keys that the name alone would hide.
    lean: float = 0.0


@contextmanager
def inference_lock(wait=None):
    """Exclusive lock shared with a separation job so only one model is on the GPU.

    wait: seconds to keep trying before raising TimeoutError; None waits as long as it takes.
    """
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with (settings.data_dir / "inference.lock").open("a") as handle:
        deadline = None if wait is None else time.monotonic() + wait
        while not filelock.try_lock(handle.fileno()):
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("The separator is busy.")
            time.sleep(0.5)
        try:
            yield
        finally:
            filelock.unlock(handle.fileno())


def measure(samples, sample_rate, announce, separate_window=None, track_beats=None):
    """Return a Reading for float32 samples shaped (frames, channels).

    announce(stage) reports a stage. Tempo, phase and key are measured on the whole mix.
    track_beats(samples, sample_rate), when given, returns (beats, downbeats) in seconds or
    None; its answer decides which pulse is the beat and which beats start a bar, and the
    signal fixes the exact period. separate_window(kind, start, end) returns audio or None:
    "harmonic" (bass and other stems, about 90 seconds) is where the key is read when it
    can be, and "drums" (about 45 seconds) breaks an octave tie when no tracker answered.
    The full-song reading stays the base: a slice only chooses between readings the full
    mix already made, or fills a key it could not call. This function does not import torch
    and does not take the GPU lock.
    """
    announce("Reading tempo and key")
    mono = _mono(samples)
    if sample_rate <= 0 or len(mono) == 0:
        return Reading(None, None, None, None, _NO_TEMPO)
    duration = len(mono) / sample_rate
    onsets = _onsets(mono, sample_rate)
    tempo = None
    if track_beats is not None:
        tempo = _tempo_from_beats(onsets, duration, track_beats(samples, sample_rate))
    if tempo is None:
        tempo = _tempo_of(onsets, duration)
        if separate_window is not None and tempo.weak:
            start, end = _span(
                onsets.full, _times(len(onsets.full), onsets.frame_rate), duration, "drums"
            )
            tempo = _with_isolated_tempo(
                tempo, onsets, duration, sample_rate, separate_window("drums", start, end)
            )
    tonal = _tonal(mono, sample_rate)
    key = _key_of(tonal.chroma, duration)
    if separate_window is not None:
        start, end = _span(tonal.focus, tonal.times, duration, "harmonic")
        key = _with_isolated_key(key, sample_rate, separate_window("harmonic", start, end))
    return _reading(tempo, key, _mood(mono, sample_rate, onsets, tonal, tempo, key))


def _mood_features(mono, sample_rate, onsets, tonal, tempo, key):
    """Raw measures of how the music feels, or None without a steady tempo or a key it can call.

    lean: how far the key profile fits major over minor (see _Key). diatonic: share of the
    pitch-class energy that falls on the key's seven scale notes. bright: centroid of the
    long-term spectrum, in hertz. loud: mean level of the audible stretches, in dBFS.
    active: mean onset strength.
    """
    if tempo.bpm is None or key.camelot is None or key.weak:
        return None
    is_major = key.camelot.endswith("B")
    codes = _MAJOR_CODE if is_major else _MINOR_CODE
    tonic = codes.index(key.camelot)
    scale = [(tonic + step) % 12 for step in (_MAJOR_STEPS if is_major else _MINOR_STEPS)]
    total = float(tonal.chroma.sum())
    if total <= 0:
        return None
    n_fft = _pow2(sample_rate * _ONSET_WINDOW)
    spectrum = None
    count = 0
    for batch in _stft(mono, n_fft, n_fft):
        spectrum = batch.sum(axis=0) if spectrum is None else spectrum + batch.sum(axis=0)
        count += len(batch)
    hertz = np.arange(len(spectrum)) * sample_rate / n_fft
    second = max(1, int(sample_rate))
    blocks = len(mono) // second
    rms = np.sqrt(np.mean(mono[: blocks * second].reshape(blocks, second) ** 2, axis=1))
    levels = 20 * np.log10(rms[rms > 1e-4]) if np.any(rms > 1e-4) else np.array([-60.0])
    return {
        "lean": key.lean,
        "diatonic": float(tonal.chroma[scale].sum() / total),
        "bright": float((spectrum * hertz).sum() / max(float(spectrum.sum()), 1e-9)),
        "loud": float(levels.mean()),
        "active": float(onsets.full.mean()),
        "bpm": tempo.bpm,
    }


def _mood(mono, sample_rate, onsets, tonal, tempo, key):
    """(valence, energy), each 0 to 1, from the measures above; (None, None) without them."""
    raw = _mood_features(mono, sample_rate, onsets, tonal, tempo, key)
    if raw is None:
        return None, None
    unit = {name: _unit(raw[name], *_MOOD_RANGE[name]) for name in _MOOD_RANGE}
    energy = sum(weight * unit[name] for name, weight in _ENERGY_WEIGHTS.items())
    valence = _MODE_WEIGHT * unit["lean"] + sum(
        weight * unit[name] for name, weight in _VALENCE_WEIGHTS.items()
    )
    return round(float(valence), 3), round(float(energy), 3)


def _unit(value, low, high):
    return float(min(1.0, max(0.0, (value - low) / (high - low))))


def _reading(tempo, key, mood=(None, None)):
    if tempo.bpm is None:
        warning = _NO_TEMPO
    elif tempo.disagrees:
        warning = _GRID_WARNING
    else:
        warning = ""
    bpm = None if tempo.bpm is None else float(f"{tempo.bpm:.2f}")
    downbeat = None if tempo.downbeat is None else float(f"{tempo.downbeat:.4f}")
    # A close call between keys is not a reading.
    camelot = None if key.weak else key.camelot
    key_name = None if key.weak else key.key_name
    return Reading(bpm, camelot, key_name, downbeat, warning, *mood)


def _with_isolated_tempo(tempo, onsets, duration, sample_rate, stem):
    """Break an octave tie with the drums and bass stem; the grid is refit on the full mix."""
    if stem is None or tempo.bpm is None or tempo.rival is None:
        return tempo
    heard = _coarse_tempo(_onsets(_mono(stem), sample_rate))[0]
    if heard is None:
        return tempo
    if abs(np.log2(tempo.rival / heard)) >= abs(np.log2(tempo.bpm / heard)):
        return tempo
    refit = _grid_tempo(onsets, tempo.rival, duration)
    if refit.bpm is None:
        return tempo
    return refit._replace(weak=refit.disagrees, rival=tempo.bpm)


def _with_isolated_key(key, sample_rate, stem):
    if stem is None:
        return key
    heard = _key_of(_tonal(_mono(stem), sample_rate).chroma, len(stem) / sample_rate)
    # Without drums and voices the chroma is the chords and the bass line; the full mix
    # answers only when that reading is a close call.
    return key if heard.weak else heard


def _mono(samples):
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim == 1:
        return np.ascontiguousarray(audio)
    return np.ascontiguousarray(audio.mean(axis=1))


def _times(count, rate):
    return np.arange(count) / rate


def _pow2(value):
    return 1 << max(4, int(round(np.log2(max(value, 16)))))


def _stft(mono, n_fft, hop):
    """Yield magnitude batches, frames centered so a hit on sample 0 sits under the peak."""
    padded = np.pad(mono, (n_fft // 2, n_fft // 2))
    count = 1 + len(mono) // hop
    while count > 1 and (count - 1) * hop + n_fft > len(padded):
        count -= 1
    window = np.hanning(n_fft).astype(np.float32)
    view = np.lib.stride_tricks.as_strided(
        padded,
        shape=(count, n_fft),
        strides=(padded.strides[0] * hop, padded.strides[0]),
    )
    for start in range(0, count, 256):
        frames = np.array(view[start : start + 256], dtype=np.float32, copy=True)
        frames *= window
        yield np.abs(np.fft.rfft(frames, axis=1))


def _onsets(mono, sample_rate):
    """Half-wave flux of log band energies, less its local mean. Quiet hits count too."""
    n_fft = _pow2(sample_rate * _ONSET_WINDOW)
    hop = max(1, int(round(sample_rate * _ONSET_HOP)))
    top = min(_BAND_HIGH_HZ, sample_rate / 2)
    edges = np.unique(
        np.round(np.geomspace(_BAND_LOW_HZ, top, _BANDS + 1) * n_fft / sample_rate).astype(int)
    )
    bands = np.concatenate(
        [np.add.reduceat(m, edges[:-1], axis=1) for m in _stft(mono, n_fft, hop)]
    )
    db = 20 * np.log10(bands + 1e-9)
    db = np.maximum(db, db.max() - _DYNAMIC_RANGE_DB)
    flux = np.maximum(0.0, np.diff(db, axis=0, prepend=db.min()))
    bass = edges[1:] * sample_rate / n_fft <= _BASS_HZ
    frame_rate = sample_rate / hop
    return _Onsets(
        _detrend(flux.mean(axis=1), frame_rate),
        _detrend(flux[:, bass].mean(axis=1) if bass.any() else flux.mean(axis=1), frame_rate),
        frame_rate,
        mono,
        sample_rate,
    )


def _detrend(envelope, frame_rate):
    width = max(3, int(frame_rate * _LOCAL_MEAN_SECONDS)) | 1
    padded = np.pad(envelope, (width // 2, width // 2), mode="edge")
    sums = np.cumsum(np.insert(padded, 0, 0.0))
    local = (sums[width:] - sums[:-width]) / width
    return np.maximum(0.0, envelope - local[: len(envelope)]).astype(np.float64)


def _prior(bpm):
    return np.exp(-0.5 * (np.log2(bpm / _SYNC_BPM) / _SYNC_WIDTH) ** 2)


def _autocorrelation(centered):
    """Positive lags of the autocorrelation. Every sample of centered contributes."""
    length = len(centered)
    size = 1 << (2 * length - 1).bit_length()
    spectrum = np.fft.rfft(centered, n=size)
    corr = np.fft.irfft(spectrum * np.conjugate(spectrum), n=size)[:length]
    return corr / np.arange(length, 0, -1)


def _parabolic(values, index):
    """Sub-sample position of the peak at index."""
    if index <= 0 or index >= len(values) - 1:
        return float(index)
    left, middle, right = float(values[index - 1]), float(values[index]), float(values[index + 1])
    denom = left - 2 * middle + right
    if abs(denom) < 1e-12:
        return float(index)
    return index + float(np.clip(0.5 * (left - right) / denom, -0.5, 0.5))


def _periodicity(envelope):
    """Autocorrelation scaled to 1 at lag 0; zeros for a flat envelope."""
    centered = envelope - float(envelope.mean())
    energy = float(np.dot(centered, centered))
    if energy <= 1e-12:
        return np.zeros(len(envelope))
    return _autocorrelation(centered) / (energy / len(envelope))


def _coarse_tempo(onsets):
    """(bpm, rival bpm) from the enhanced autocorrelation, or (None, None).

    Kick and full-band periodicity are summed: syncopated snares pull the full mix toward
    a 4:3 ratio, while the kick keeps the beat. A beat lag is rewarded for the bar-level
    lags that repeat with it. The rival is the other octave, when it scores within
    _OCTAVE_TIE of the winner.
    """
    if len(onsets.full) < 8:
        return None, None
    corr = _periodicity(onsets.full) + _periodicity(onsets.bass)
    if not np.any(corr):
        return None, None
    rate = onsets.frame_rate
    min_lag = max(1, int(np.floor(rate * 60 / _MAX_BPM)))
    max_lag = min(len(corr) // 4 - 1, int(np.ceil(rate * 60 / _MIN_BPM)))
    if max_lag <= min_lag + 2:
        return None, None
    lags = np.arange(min_lag, max_lag + 1)
    enhanced = corr[lags] + 0.5 * corr[2 * lags] + 0.25 * corr[4 * lags]
    scores = enhanced * _prior(60.0 * rate / lags)
    best = int(np.argmax(scores))
    if scores[best] <= 0:
        return None, None
    lag = _parabolic(scores, best) + min_lag
    bpm = 60.0 * rate / lag
    rival = None
    for scale in (2, 0.5):
        other = int(round(lags[best] * scale))
        if other < min_lag or other > max_lag:
            continue
        if scores[other - min_lag] > _OCTAVE_TIE * scores[best]:
            rival = 60.0 * rate / other
    return float(bpm), rival


def _tempo_of(onsets, duration):
    if duration < 2 or len(onsets.full) <= 8:
        return _Tempo(None, None, False, True, None)
    bpm, rival = _coarse_tempo(onsets)
    if bpm is None:
        return _Tempo(None, None, False, True, None)
    tempo = _grid_tempo(onsets, bpm, duration)
    return tempo._replace(weak=tempo.weak or rival is not None, rival=rival)


def _tempo_from_beats(onsets, duration, tracked):
    """Tempo, grid and bar from a network's beats, or None when it found too few to trust.

    The network gives the pulse to a few percent and the bar phase; the signal then fixes
    the period and the audible position of each hit exactly.
    """
    if tracked is None or duration < 2:
        return None
    beats, downbeats = tracked
    if len(beats) < _MIN_TRACKED_BEATS:
        return None
    gaps = np.diff(beats)
    middle = float(np.median(gaps))
    if middle <= 0:
        return None
    steady = gaps[np.abs(gaps / middle - 1) < 0.05]
    if len(steady) < _MIN_TRACKED_BEATS - 1:
        return None
    bpm = 60.0 / float(np.mean(steady))
    if not _MIN_BPM <= bpm <= _MAX_BPM:
        return None
    tempo = _grid_tempo(onsets, bpm, duration, downbeats, beats)
    return tempo if tempo.bpm is not None else None


def _fold(envelope, period, size=_FOLD_BINS):
    """Envelope summed by phase within one beat, lightly smoothed around the circle."""
    phase = (np.arange(len(envelope)) / period) % 1.0
    folded = np.bincount((phase * size).astype(int), weights=envelope, minlength=size)
    return folded + np.roll(folded, 1) + np.roll(folded, -1)


def _lock_period(envelope, rate, bpm):
    """Period in frames that piles the envelope up best, near bpm."""
    best_score, best_period = -1.0, 60.0 * rate / bpm
    for span, step in ((0.03, 0.0005), (0.0006, 0.00005)):
        center = best_period
        for shift in np.arange(-span, span + step / 2, step):
            period = center * (1 + shift)
            score = float(_fold(envelope, period).max())
            if score > best_score:
                best_score, best_period = score, period
    return best_period


def _grid_tempo(onsets, bpm, duration, downbeats=None, tracked=None):
    """Lock the grid near bpm, fit it to real onset peaks, then read downbeat and fidelity."""
    rate = onsets.frame_rate
    envelope = onsets.full
    period = _lock_period(envelope, rate, bpm)
    origin = float(np.argmax(_fold(envelope, period))) / _FOLD_BINS * period
    fit = None
    for _ in range(3):
        fit = _fit_peaks(envelope, period, origin) or fit
        if fit is None:
            return _Tempo(None, None, False, True, None)
        period, origin = fit
    beats = origin + period * np.arange(int((len(envelope) - origin) / period) + 1)
    beats = beats[beats < len(envelope)]
    seconds, step = _hit_grid(onsets, beats, period)
    visible = beats >= 0
    if tracked is None:
        disagrees = _disagrees(envelope, beats[visible], period)
    else:
        disagrees = _disagrees(envelope, beats[visible], period, tracked, seconds[visible], step)
    downbeat = _downbeat(onsets, beats, seconds, step, duration, downbeats)
    return _Tempo(60.0 / step, downbeat, disagrees, disagrees, None)


def _fit_peaks(envelope, period, origin):
    """Least-squares (period, origin) of the onset peaks that sit near the grid."""
    count = int((len(envelope) - origin) / period) + 1
    index = np.arange(count)
    guess = origin + period * index
    width = max(1, int(_FIT_WINDOW * period))
    inside = (guess >= width) & (guess < len(envelope) - width - 1)
    index, guess = index[inside], guess[inside]
    if len(index) < _MIN_FIT_BEATS:
        return None
    offsets = np.arange(-width, width + 1)
    around = np.round(guess).astype(int)[:, None] + offsets
    window = envelope[around]
    top = np.argmax(window, axis=1)
    rows = np.arange(len(index))
    peak = around[rows, top]
    heights = window[rows, top]
    before, after = envelope[peak - 1], envelope[peak + 1]
    # Centroid of the three frames around the peak; steadier than a parabola on a spike.
    shift = (after - before) / (before + heights + after + 1e-12)
    where = peak + np.clip(shift, -0.5, 0.5)
    keep = (
        heights >= 0.3 * float(np.median(heights[heights > 0]))
        if (heights > 0).any()
        else heights > 0
    )
    for tolerance in _FIT_TOLERANCES:
        if int(keep.sum()) < _MIN_FIT_BEATS:
            return None
        slope, intercept = np.polyfit(index[keep], where[keep], 1, w=heights[keep])
        keep = keep & (np.abs(where - (intercept + slope * index)) < tolerance * period)
    if int(keep.sum()) < _MIN_FIT_BEATS:
        return None
    slope, intercept = np.polyfit(index[keep], where[keep], 1, w=heights[keep])
    if slope <= 0:
        return None
    # Move the origin to the first beat at or after _LEAD_FRAMES before the start.
    first = int(np.ceil((-_LEAD_FRAMES - intercept) / slope))
    return float(slope), float(intercept + slope * first)


def _disagrees(envelope, beats, period, tracked=None, grid=None, step=None):
    """True when a substantial stretch with real onsets does not sit on the grid.

    Without a tracker the share of onset energy near the grid says so. With one, the share
    of its beats near the grid does: the network hears beats where onset energy is sparse
    or syncopated, which the energy share mistakes for a stretch off the grid.
    """
    last_frame = len(envelope) - 1
    # What chance alone would put within a frame of the grid, with a wide margin.
    floor = max(_ON_GRID_SHARE, 9.0 / period) if tracked is None else _TRACKED_SHARE
    segments = []
    for start in range(0, len(beats), _SEGMENT_BEATS):
        chunk = np.round(beats[start : start + _SEGMENT_BEATS]).astype(int)
        if len(chunk) < _SEGMENT_BEATS // 2:
            continue
        first, last = chunk[0], chunk[-1]
        total = float(envelope[first : last + 1].sum())
        if tracked is None:
            near = sum(float(envelope[np.clip(chunk + s, 0, last_frame)].sum()) for s in (-1, 0, 1))
            share = near / total if total > 0 else 0.0
        else:
            share = _tracked_share(tracked, grid, step, start, len(chunk))
        segments.append((total, share, int(last - first)))
    if not segments:
        return False
    loud = float(np.median([total / span for total, _share, span in segments if span > 0]))
    off = sum(
        span
        for total, share, span in segments
        if span > 0 and total / span >= _SEGMENT_QUIET * loud and share < floor
    )
    return off / len(envelope) >= _OFF_GRID


def _tracked_share(tracked, grid, step, start, count):
    """Share of the network's beats, inside one stretch of the grid, that sit on a grid line.

    1.0 when it found none there: no beats is no evidence against the grid.
    """
    inside = tracked[
        (tracked >= grid[start] - step / 2) & (tracked <= grid[start + count - 1] + step / 2)
    ]
    if len(inside) == 0:
        return 1.0
    nearest = np.abs(inside[:, None] - grid[start : start + count][None, :]).min(axis=1)
    return float(np.mean(nearest < _TRACKED_TOLERANCE * step))


def attack_positions(mono, rate, centers, radius):
    """(index, seconds, strength) of the steepest rectified-waveform rise near each center.

    centers and radius are in seconds. Spectral flux lands a little before a hit; the
    waveform shows the hit itself, to a sample. Centers too close to an edge are skipped.
    """
    width = max(1, int(_ATTACK_SMOOTH * rate))
    sharp = np.abs(np.diff(mono, n=2, prepend=mono[:2]))
    sums = np.cumsum(np.insert(sharp, 0, 0.0))
    smooth = (sums[width:] - sums[:-width]) / width
    reach = int(radius * rate)
    found = []
    for index, center in enumerate(np.asarray(centers) * rate):
        middle = int(round(center))
        lo, hi = middle - reach - width, middle + reach + width
        if lo < 0 or hi >= len(smooth):
            continue
        rise = smooth[lo + 2 * width : hi + 1] - smooth[lo : hi + 1 - 2 * width]
        peak = int(np.argmax(rise))
        found.append((index, (lo + width + peak + width / 2) / rate, float(rise[peak])))
    return np.array(found).reshape(-1, 3).T


def _attacks(onsets, beats, period):
    """(beat index, seconds, strength) of the audible hit near each beat of the grid."""
    radius = min(_ATTACK_RADIUS, 0.35 * period / onsets.frame_rate)
    return attack_positions(onsets.mono, onsets.sample_rate, beats / onsets.frame_rate, radius)


def _hit_grid(onsets, beats, period):
    """(beat times in seconds, seconds per beat) with the grid moved onto the audible hits.

    The envelope fixes the period to within a fraction of a percent. The hits then give
    the exact slope over the whole track, and the median offset when too few agree.
    """
    frame = onsets.frame_rate
    plain = beats / frame
    step = period / frame
    index, hit, strength = _attacks(onsets, beats, period)
    if len(index) < _MIN_FIT_BEATS:
        return plain, step
    keep = strength >= 0.3 * float(np.median(strength))
    fit = None
    for tolerance in _FIT_TOLERANCES:
        if int(keep.sum()) < _MIN_FIT_BEATS:
            break
        fit = np.polyfit(index[keep], hit[keep], 1, w=strength[keep])
        keep = keep & (np.abs(hit - np.polyval(fit, index)) < tolerance * step)
    if fit is not None and int(keep.sum()) >= _MIN_FIT_BEATS:
        fit = np.polyfit(index[keep], hit[keep], 1, w=strength[keep])
        if abs(fit[0] / step - 1) < _FIT_AGREE:
            return fit[1] + fit[0] * np.arange(len(beats)), float(fit[0])
    return plain + float(np.median(hit[keep] - plain[index.astype(int)][keep])), step


def _tracked_phase(seconds, step, downbeats):
    """Which beat of four starts a bar, by the network's downbeats; None unless most agree."""
    if downbeats is None or len(downbeats) < 2:
        return None
    index = np.round((np.asarray(downbeats) - seconds[0]) / step).astype(int)
    votes = np.bincount(index % 4, minlength=4)
    if votes.max() < _DOWNBEAT_VOTE * len(index):
        return None
    return int(np.argmax(votes))


def _downbeat(onsets, beats, seconds, step, duration, downbeats=None):
    """Start of the first bar: the network's downbeats decide which beat of four it is, else
    whichever of four beat phases carries the most onset weight."""
    if len(beats) < 4:
        return None
    last = len(onsets.full) - 1
    strength = np.zeros(len(beats))
    for shift in (-1, 0, 1):
        at = np.clip(np.round(beats).astype(int) + shift, 0, last)
        strength = np.maximum(strength, onsets.full[at] + onsets.bass[at])
    scores = np.array([strength[phase::4].mean() for phase in range(4)])
    tracked = _tracked_phase(seconds, step, downbeats)
    if tracked is not None:
        anchor = float(seconds[tracked])
    elif scores.max() > _DOWNBEAT_FLAT * scores.mean():
        anchor = float(seconds[int(np.argmax(scores))])
    else:
        # No phase stands out: the first beat with real weight is the bar's first beat.
        solid = np.flatnonzero(strength >= 0.5 * np.percentile(strength, 90))
        anchor = float(seconds[solid[0]])
    bar = 4 * step
    first = anchor % bar
    # A bar edge a few milliseconds early is the bar edge, not a full bar late.
    if bar - first < 0.02:
        first = 0.0
    return first if first <= duration else None


def _tonal(mono, sample_rate):
    """Pitch-class energy per frame from tuning-corrected spectral peaks.

    The window is long enough to separate low notes. Each bin is the median over a few
    frames, which drops drum hits and keeps held notes.
    """
    n_fft = _pow2(sample_rate * _TONAL_WINDOW)
    hop = n_fft // 2
    low = max(1, int(np.ceil(_TONAL_LOW_HZ * n_fft / sample_rate)))
    high = min(n_fft // 2 - 2, int(_TONAL_HIGH_HZ * n_fft / sample_rate))
    magnitude = np.concatenate([m[:, low - 1 : high + 2] for m in _stft(mono, n_fft, hop)])
    harmonic = _median_over_time(magnitude)
    core = harmonic[:, 1:-1]
    left, right = harmonic[:, :-2], harmonic[:, 2:]
    floor = _PEAK_FLOOR * core.max(axis=1, keepdims=True)
    rows, cols = np.nonzero((core > left) & (core >= right) & (core > floor))
    mid = core[rows, cols]
    a, c = left[rows, cols], right[rows, cols]
    denom = a - 2 * mid + c
    delta = np.where(np.abs(denom) > 1e-12, 0.5 * (a - c) / np.where(denom == 0, 1, denom), 0.0)
    delta = np.clip(delta, -0.5, 0.5)
    frequency = (cols + low + delta) * sample_rate / n_fft
    weight = np.maximum(mid - 0.25 * (a - c) * delta, 0.0)
    pitch = 69 + 12 * np.log2(frequency / 440.0)
    pitch = pitch - _tuning(pitch, weight)
    pitch_class = np.round(pitch).astype(int) % 12
    frames = np.bincount(
        rows * 12 + pitch_class, weights=weight, minlength=len(harmonic) * 12
    ).reshape(-1, 12)
    total = frames.sum(axis=1)
    focus = frames.max(axis=1) / np.where(total > 0, total, 1.0)
    return _Tonal(frames.sum(axis=0), _times(len(frames), sample_rate / hop), focus)


def _median_over_time(magnitude):
    half = _HARMONIC_FRAMES // 2
    out = np.empty_like(magnitude)
    for start in range(0, len(magnitude), 512):
        stop = min(len(magnitude), start + 512)
        padded = magnitude[max(0, start - half) : stop + half]
        padded = np.pad(
            padded,
            ((max(0, half - start), max(0, stop + half - len(magnitude))), (0, 0)),
            mode="edge",
        )
        windows = np.lib.stride_tricks.sliding_window_view(padded, _HARMONIC_FRAMES, axis=0)
        out[start:stop] = np.median(windows, axis=-1)
    return out


def _tuning(pitch, weight):
    """Offset in semitones, within half a semitone, where the peaks cluster."""
    if len(pitch) == 0:
        return 0.0
    deviation = pitch - np.round(pitch)
    histogram = np.bincount(
        ((deviation + 0.5) * _TUNING_BINS).astype(int) % _TUNING_BINS,
        weights=weight,
        minlength=_TUNING_BINS,
    )
    histogram = histogram + np.roll(histogram, 1) + np.roll(histogram, -1)
    return float((np.argmax(histogram) + 0.5) / _TUNING_BINS - 0.5)


def _key_of(chroma, duration):
    """One key from the chroma of every frame. A short stretch does not get its own vote."""
    best = _best_key(chroma)
    if duration < 2 or best is None:
        return _Key(None, None, True)
    code, margin, runner_up, lean, fit = best
    rescued = fit >= _COMPATIBLE_FIT and _compatible(code, runner_up)
    weak = margin < _KEY_MARGIN and not rescued
    return _Key(code, _KEY_NAME[code], weak, lean)


def _compatible(first, second):
    """True when two Camelot codes mix together: the same number, or next to each other
    on the wheel in the same mode. Between those the key's name matters less than its place."""
    number_a, mode_a = int(first[:-1]), first[-1]
    number_b, mode_b = int(second[:-1]), second[-1]
    if number_a == number_b:
        return True
    return mode_a == mode_b and (number_a - number_b) % 12 in (1, 11)


def _best_key(chroma):
    if chroma is None or float(np.sum(chroma)) <= 0:
        return None
    level = float(np.mean(chroma))
    if level <= 0 or float(np.max(chroma) - np.min(chroma)) / level < _HARMONY_SPAN:
        return None
    scored = []
    for shift in range(12):
        major = np.mean([_corr(chroma, np.roll(pair[0], shift)) for pair in _PROFILES])
        minor = np.mean([_corr(chroma, np.roll(pair[1], shift)) for pair in _PROFILES])
        scored.append((float(major), _MAJOR_CODE[shift]))
        scored.append((float(minor), _MINOR_CODE[shift]))
    scored.sort(reverse=True)
    if scored[0][0] < _KEY_FLOOR:
        return None
    best_major = max(score for score, code in scored if code.endswith("B"))
    best_minor = max(score for score, code in scored if code.endswith("A"))
    return (
        scored[0][1],
        scored[0][0] - scored[1][0],
        scored[1][1],
        best_major - best_minor,
        scored[0][0],
    )


def _corr(left, right):
    left = left - float(np.mean(left))
    right = right - float(np.mean(right))
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(left, right) / denom)


def _span(activity, times, duration, kind):
    """The busiest stretch for a separator of this kind, as (start, end) seconds."""
    length = _WINDOW_SECONDS[kind]
    if duration <= length or len(times) < 2:
        return 0.0, float(duration)
    width = max(1, int(round(length / np.median(np.diff(times)))))
    if width >= len(activity):
        return 0.0, float(duration)
    scored = np.convolve(activity, np.ones(width), mode="valid")
    start = float(times[min(int(np.argmax(scored)), len(times) - 1)])
    return start, min(float(duration), start + length)


def _separator(samples, sample_rate, announce):
    """separate_window for the process entry point. The lock is taken only here."""

    def separate_window(kind, start, end):
        announce("Waiting for the separator")
        try:
            with inference_lock(wait=_LOCK_WAIT_SECONDS):
                announce("Isolating drums and bass" if kind == "drums" else "Isolating the harmony")
                first = max(0, int(round(start * sample_rate)))
                last = min(len(samples), int(round(end * sample_rate)))
                from stemlab.inference import isolate_window

                return isolate_window(samples[first:last], sample_rate, kind)
        except TimeoutError:
            return None
        except Exception:
            logging.getLogger(__name__).exception("Isolating %s failed", kind)
            return None

    return separate_window


def _beat_tracker(announce):
    """track_beats for the process entry point; the network is imported only here."""

    def track(samples, sample_rate):
        announce("Tracking the beat")
        from stemlab.inference import track_beats

        return track_beats(samples, sample_rate)

    return track


def _announce(stage):
    print(f"STAGE:{stage}", file=sys.stderr, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read BPM, key and downbeat for one audio file.")
    parser.add_argument("source", type=Path)
    args = parser.parse_args(argv)
    _announce("Checking the file")
    samples, sample_rate = sf.read(args.source, dtype="float32", always_2d=True)
    # Stdout carries only the reading. Libraries print to it (a model download announces itself
    # there), so everything else goes to stderr until the reading is ready.
    result, reading_stream = os.dup(1), sys.stdout
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    try:
        reading = measure(
            samples,
            sample_rate,
            _announce,
            _separator(samples, sample_rate, _announce),
            _beat_tracker(_announce),
        )
    finally:
        sys.stdout = reading_stream
        os.dup2(result, 1)
        os.close(result)
    json.dump(reading.to_dict(), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
