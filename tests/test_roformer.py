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
