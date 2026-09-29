import sqlite3

import numpy as np
import pytest
import soundfile as sf

from stemlab import jobs
from stemlab.config import settings
from stemlab.inference import write_outputs
from stemlab.outputs import STEMS, output_plan


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
