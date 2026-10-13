import numpy as np
import pytest
import soundfile as sf

from stemlab.inference import CONTEXT_SECONDS, read_section

RATE = 1000


@pytest.fixture
def track(tmp_path):
    path = tmp_path / "track.wav"
    sf.write(
        path, np.arange(60 * RATE, dtype="float32")[:, None] / (60 * RATE), RATE, subtype="FLOAT"
    )
    return path


def test_whole_track_has_no_trim(track):
    data, rate, trim = read_section(track)
    assert (len(data), rate, trim) == (60 * RATE, RATE, None)


def test_section_adds_context_and_reports_exact_trim(track):
    data, rate, trim = read_section(track, 20, 30)
    assert len(data) == (10 + 2 * CONTEXT_SECONDS) * RATE
    assert trim == (CONTEXT_SECONDS, 10)
    first = round(trim[0] * rate)
    # The kept slice starts exactly at the requested cue.
    assert data[first, 0] == pytest.approx(20 / 60)


def test_context_is_clamped_at_track_edges(track):
    data, rate, trim = read_section(track, 2, 58)
    assert len(data) == 60 * RATE
    assert trim == (2, 56)


def test_restrict_keeps_only_the_bag_members_for_the_wanted_stems():
    torch = pytest.importorskip("torch")
    apply = pytest.importorskip("demucs.apply")
    from stemlab.inference import restrict

    class Member(torch.nn.Module):
        sources = ["drums", "bass", "other", "vocals"]
        samplerate = 44100
        audio_channels = 2

    members = [Member() for _ in range(4)]
    weights = [[1 if i == k else 0 for k in range(4)] for i in range(4)]
    bag = apply.BagOfModels(members, weights)
    only_vocals = restrict(bag, {"vocals"})
    assert only_vocals.models[0] is members[3] and len(only_vocals.models) == 1
    instruments = restrict(bag, {"drums", "bass", "other"})
    assert list(instruments.models) == members[:3]
    assert restrict(members[0], {"vocals"}) is members[0]  # a single model is used as is


def test_every_model_choice_maps_to_demucs_models():
    from stemlab.config import DEMUCS_MODELS, MODELS

    assert set(DEMUCS_MODELS) == set(MODELS)
    assert all(names for names in DEMUCS_MODELS.values())


def test_a_direct_instrumental_choice_is_used_whole_for_no_vocals(monkeypatch):
    """The model's instrumental is written as the output; Demucs and the vocal models do not run."""
    import numpy as np

    from stemlab import inference, roformer
    from stemlab.outputs import output_plan

    heard = {}

    def fake_instrumental(mix, choice, announce):
        heard["choice"] = choice
        return mix * 0.5

    monkeypatch.setattr(roformer, "separate_instrumental", fake_instrumental)
    monkeypatch.setattr(
        roformer, "separate_vocals", lambda *a: (_ for _ in ()).throw(AssertionError)
    )
    monkeypatch.setattr(inference, "run_demucs", lambda *a: (_ for _ in ()).throw(AssertionError))
    audio = (np.random.default_rng(1).standard_normal((4410, 2)) * 0.1).astype("float32")

    class Model:
        samplerate, audio_channels = 44100, 2
        sources = ["drums", "bass", "other", "vocals"]

    separated = inference.estimate(
        audio,
        44100,
        [object()],
        "cpu",
        Model(),
        output_plan("instrumental"),
        "ensemble",
        "direct_resurrection",
        0,
        0.25,
        lambda text: None,
    )
    assert heard["choice"] == "direct_resurrection"
    np.testing.assert_allclose(
        separated[Model.sources.index("other")].numpy(), audio.T * 0.5, atol=1e-6
    )
    assert float(separated[Model.sources.index("vocals")].abs().max()) == 0.0


@pytest.mark.parametrize("spelling", ["Instrumental", "instrumental", "other"])
def test_the_instrumental_is_found_whatever_the_checkpoint_calls_it(monkeypatch, spelling):
    import numpy as np

    from stemlab import roformer

    inst, voice = np.ones((2, 8), "float32"), np.zeros((2, 8), "float32")
    monkeypatch.setattr(roformer, "_need_cuda", lambda: None)
    monkeypatch.setattr(roformer, "_demix", lambda mix, filename: {"Vocals": voice, spelling: inst})
    found = roformer.separate_instrumental(inst, "direct_resurrection", lambda text: None)
    assert found is inst
    monkeypatch.setattr(roformer, "_demix", lambda mix, filename: {"Vocals": voice})
    with pytest.raises(RuntimeError, match="no instrumental"):
        roformer.separate_instrumental(inst, "direct_resurrection", lambda text: None)
