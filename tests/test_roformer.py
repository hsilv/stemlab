import numpy as np
import pytest

from stemlab.roformer import vocals_of


@pytest.mark.parametrize("name", ["vocals", "Vocals"])
def test_vocals_found_regardless_of_capitalization(name):
    vocals = np.ones((2, 4))
    assert vocals_of({"Instrumental": np.zeros((2, 4)), name: vocals}) is vocals


def test_missing_vocals_is_a_clear_error():
    with pytest.raises(RuntimeError, match="no vocals stem"):
        vocals_of({"other": np.zeros((2, 4))})


def test_every_roformer_vocal_choice_has_checkpoints():
    from stemlab.config import VOCAL_MODELS
    from stemlab.roformer import CHECKPOINTS

    assert set(CHECKPOINTS) == set(VOCAL_MODELS) - {"demucs"}


def test_resurrection_gives_the_vocals_stem_of_an_instrumental_first_model(monkeypatch):
    import numpy as np

    from stemlab import roformer

    voice, other = np.ones((2, 8), "float32"), np.zeros((2, 8), "float32")
    seen = []
    monkeypatch.setattr(roformer, "_need_cuda", lambda: None)
    monkeypatch.setattr(
        roformer, "_demix", lambda mix, name: seen.append(name) or {"other": other, "vocals": voice}
    )
    found = roformer.separate_vocals(voice, "resurrection", lambda text: None)
    assert found is voice or (found == voice).all()
    assert seen == [roformer.RESURRECTION]
    assert roformer.INSTRUMENTALS["direct_resurrection"] == roformer.RESURRECTION
