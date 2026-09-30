import sqlite3

import numpy as np
import pytest
import soundfile as sf

from stemlab import jobs
from stemlab.config import settings
from stemlab.inference import splice, write_outputs
from stemlab.outputs import STEMS, is_instrumental, output_plan


@pytest.mark.parametrize(
    "mode,keep,expected",
    [
        ("all", None, list(STEMS)),
        ("vocals", None, ["vocals"]),
        ("instrumental", None, ["instrumental"]),
        ("custom", ["vocals", "bass"], ["mix"]),
    ],
)
def test_output_wavs_contain_exactly_selected_sources(tmp_path, mode, keep, expected):
    sources = {
        name: np.full((2, 16000), value, dtype="float32")
        for name, value in zip(STEMS, [0.125, 0.25, 0.5, 1.0], strict=True)
    }
    plan = output_plan(mode, keep)
    result = write_outputs(sources, 16000, tmp_path, plan)
    assert [stem.name for stem in result] == expected
    assert sorted(path.stem for path in tmp_path.iterdir()) == sorted(expected)
    for group in plan:
        data, rate = sf.read(tmp_path / f"{group['id']}.wav", dtype="float32")
        assert rate == 16000
        # Includes values > 1 to ensure mixes are not clipped or normalized.
        np.testing.assert_array_equal(data, sum(sources[name] for name in group["sources"]).T)


@pytest.mark.parametrize(
    "mode,keep",
    [
        ("unknown", None),
        ("custom", None),
        ("custom", []),
        ("custom", ["piano"]),
        ("custom", ["vocals", "vocals"]),
        ("all", ["bass"]),
    ],
)
def test_reject_invalid_output_plans(mode, keep):
    with pytest.raises(ValueError):
        output_plan(mode, keep)


def test_existing_jobs_migrate_to_all_stems(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    with sqlite3.connect(tmp_path / "jobs.sqlite3") as db:
        db.execute("""CREATE TABLE jobs (
            id TEXT PRIMARY KEY, filename TEXT, status TEXT, stage TEXT, created REAL,
            updated REAL, duration REAL, sample_rate INTEGER, channels INTEGER,
            error TEXT, task_id TEXT)""")
        db.execute(
            "INSERT INTO jobs VALUES ('old', 'song.wav', 'completed', 'Ready', "
            "1, 1, 3, 44100, 2, NULL, 'task')"
        )
    row = jobs.get("old")
    assert row["mode"] == "all" and row["keep"] is None
    assert row["status"] == "completed"
    assert len(output_plan(row["mode"], row["keep"])) == 4
    assert jobs.get("old") == row  # Migration is idempotent.


def test_splice_keeps_the_original_outside_the_section_and_fades_inner_edges():
    rate = 1000
    original = np.full((2, 10 * rate), 0.5, dtype="float32")
    processed = np.full((2, 2 * rate), 0.0, dtype="float32")
    result = splice(original, processed, 4 * rate, rate)
    assert result.shape == original.shape
    np.testing.assert_array_equal(result[:, : 4 * rate], original[:, : 4 * rate])
    np.testing.assert_array_equal(result[:, 6 * rate :], original[:, 6 * rate :])
    np.testing.assert_array_equal(result[:, 4 * rate + 10 : 6 * rate - 10], 0.0)
    # Inner edges ramp between the two signals instead of jumping.
    assert 0 < result[0, 4 * rate + 5] < 0.5
    assert 0 < result[0, 6 * rate - 5] < 0.5


def test_lay_places_each_range_and_leaves_the_gap():
    from stemlab.inference import lay

    rate = 1000
    original = np.full((2, 20 * rate), 0.5, dtype="float32")
    silence = np.zeros((2, 5 * rate), dtype="float32")
    result = lay(original, [(silence, 0), (silence, 10 * rate)], rate)
    np.testing.assert_array_equal(result[:, 6 * rate : 9 * rate], original[:, 6 * rate : 9 * rate])
    np.testing.assert_array_equal(result[:, rate : 4 * rate], 0)
    np.testing.assert_array_equal(result[:, 11 * rate : 14 * rate], 0)


def test_splice_does_not_fade_at_the_edges_of_the_song():
    rate = 1000
    original = np.full((2, 4 * rate), 0.5, dtype="float32")
    processed = np.zeros((2, 4 * rate), dtype="float32")
    np.testing.assert_array_equal(splice(original, processed, 0, rate), processed)


def test_write_outputs_with_backdrop_returns_the_whole_song(tmp_path):
    rate = 1000
    original = np.full((2, 6 * rate), 0.25, dtype="float32")
    sources = {name: np.full((2, 2 * rate), 0.1, dtype="float32") for name in STEMS}
    plan = output_plan("instrumental")
    write_outputs(sources, rate, tmp_path, plan, original, 2 * rate)
    data, _ = sf.read(tmp_path / "instrumental.wav", dtype="float32")
    assert data.shape == (6 * rate, 2)
    assert data[0, 0] == 0.25 and data[-1, 0] == 0.25
    assert data[3 * rate, 0] == pytest.approx(0.3)  # drums + bass + other = 3 × 0.1


def test_jobs_from_the_single_roformer_model_choice_are_converted(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    with sqlite3.connect(tmp_path / "jobs.sqlite3") as db:
        db.execute("""CREATE TABLE jobs (
            id TEXT PRIMARY KEY, filename TEXT, status TEXT, stage TEXT, created REAL,
            updated REAL, duration REAL, sample_rate INTEGER, channels INTEGER,
            error TEXT, task_id TEXT, mode TEXT NOT NULL DEFAULT 'all', keep TEXT,
            model TEXT NOT NULL DEFAULT 'htdemucs', shifts INTEGER NOT NULL DEFAULT 0,
            overlap REAL NOT NULL DEFAULT 0.25)""")
        for name, model in (("roformer", "roformer_htdemucs_ft"), ("demucs", "htdemucs_ft")):
            db.execute(
                "INSERT INTO jobs (id, filename, status, stage, created, updated, duration, "
                "sample_rate, channels, error, task_id, model) "
                "VALUES (?, 'a.wav', 'completed', 'Ready', 1, 1, 3, 44100, 2, NULL, 't', ?)",
                (name, model),
            )
    roformer, demucs = jobs.get("roformer"), jobs.get("demucs")
    assert (roformer["model"], roformer["vocals"], roformer["instruments_from"]) == (
        "htdemucs_ft",
        "ensemble",
        "residual",
    )
    assert (demucs["model"], demucs["vocals"]) == ("htdemucs_ft", "demucs")


@pytest.mark.parametrize(
    "mode,keep,expected",
    [
        ("instrumental", None, True),
        ("custom", ["drums", "bass", "other"], True),
        ("custom", ["drums", "bass"], False),
        ("custom", ["vocals", "drums", "bass", "other"], False),
        ("vocals", None, False),
        ("all", None, False),
    ],
)
def test_only_the_full_instrumental_is_the_inverse_of_the_vocals(mode, keep, expected):
    assert is_instrumental(output_plan(mode, keep)) is expected
