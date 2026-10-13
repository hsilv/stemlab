import pytest

from stemlab.playlist import order_tracks


def track(filename, bpm, camelot, key_name="A minor", path=None, valence=None, energy=None):
    return {
        "path": path if path is not None else f"/music/{filename}",
        "filename": filename,
        "bpm": float(bpm),
        "camelot": camelot,
        "key_name": key_name,
        "valence": valence,
        "energy": energy,
    }


def names(order):
    return [row["filename"] for row in order]


def test_empty_pool_returns_an_empty_list():
    assert order_tracks([]) == []


def test_first_row_is_not_a_break_and_has_no_band():
    order = order_tracks([track("only.wav", 120, "8A", key_name=None)])
    assert order == [
        {
            "path": "/music/only.wav",
            "filename": "only.wav",
            "bpm": 120.0,
            "camelot": "8A",
            "key_name": None,
            "valence": None,
            "energy": None,
            "break": False,
            "band": None,
        }
    ]


def test_opener_is_the_slowest_bpm_then_filename():
    order = order_tracks(
        [
            track("c.wav", 100, "8A"),
            track("fast.wav", 140, "9A"),
            track("a.wav", 100, "7A"),
        ]
    )
    assert names(order)[0] == "a.wav"
    assert order[0]["break"] is False
    assert order[0]["band"] is None


def test_missing_pin_falls_back_to_the_slowest_bpm():
    slow = track("slow.wav", 90, "8A")
    fast = track("fast.wav", 140, "8A")
    assert names(order_tracks([fast, slow], pinned="/music/missing.wav"))[0] == "slow.wav"


def test_pin_is_the_opener_and_the_path_rebuilds_from_it():
    slow = track("slow.wav", 100, "8A")
    pinned = track("pinned.wav", 128, "1A")
    other = track("other.wav", 128, "2A")
    order = order_tracks([slow, other, pinned], pinned=pinned["path"])
    assert names(order) == ["pinned.wav", "other.wav", "slow.wav"]
    assert order[0]["break"] is False
    assert order[0]["band"] is None
    assert order[1]["break"] is False
    assert order[2]["break"] is True


@pytest.mark.parametrize(
    ("opener_key", "next_key"),
    [
        ("12A", "1A"),
        ("1A", "12A"),
        ("12B", "1B"),
        ("1B", "12B"),
        ("12A", "11A"),
        ("12A", "12B"),
        ("8A", "7A"),
        ("8A", "9A"),
        ("8A", "8B"),
    ],
)
def test_camelot_neighbors_join_without_a_break(opener_key, next_key):
    order = order_tracks([track("next.wav", 108, next_key), track("opener.wav", 100, opener_key)])
    assert names(order) == ["opener.wav", "next.wav"]
    assert order[1]["break"] is False
    assert order[1]["band"] is None


def test_twelve_meets_one_ahead_of_a_one_step_letter_flip():
    order = order_tracks(
        [
            track("flip.wav", 108, "1B"),
            track("wrap.wav", 108, "1A"),
            track("opener.wav", 100, "12A"),
        ]
    )
    assert names(order) == ["opener.wav", "wrap.wav", "flip.wav"]
    assert order[1]["break"] is False
    assert order[2]["break"] is False


def test_one_step_with_a_letter_flip_is_a_break():
    order = order_tracks([track("flip.wav", 108, "1B"), track("opener.wav", 100, "12A")])
    assert names(order) == ["opener.wav", "flip.wav"]
    assert order[1]["break"] is True
    assert order[1]["band"] is None


def test_written_tempo_within_eight_percent_passes():
    order = order_tracks([track("next.wav", 138, "8A"), track("opener.wav", 128, "8A")])
    assert names(order) == ["opener.wav", "next.wav"]
    assert order[1]["break"] is False
    assert order[1]["band"] is None


def test_written_tempo_past_eight_percent_is_a_break():
    order = order_tracks([track("next.wav", 139, "8A"), track("opener.wav", 128, "8A")])
    assert names(order) == ["opener.wav", "next.wav"]
    assert order[1]["break"] is True
    assert order[1]["band"] is None


def test_closer_written_tempo_beats_the_eight_percent_edge():
    order = order_tracks(
        [
            track("edge.wav", 138, "8A"),
            track("closer.wav", 130, "9A"),
            track("opener.wav", 128, "8A"),
        ]
    )
    assert names(order)[1] == "closer.wav"
    assert order[1]["break"] is False
    assert order[1]["band"] is None


def test_double_tempo_at_the_eight_percent_edge_passes():
    order = order_tracks([track("next.wav", 216, "8A"), track("opener.wav", 100, "8A")])
    assert names(order) == ["opener.wav", "next.wav"]
    assert order[1]["break"] is False
    assert order[1]["band"] == "double"


def test_double_tempo_past_the_eight_percent_edge_is_a_break():
    order = order_tracks([track("next.wav", 217, "8A"), track("opener.wav", 100, "8A")])
    assert names(order) == ["opener.wav", "next.wav"]
    assert order[1]["break"] is True
    assert order[1]["band"] == "double"


def test_half_band_when_the_next_track_is_the_lower_octave():
    low = track("low.wav", 100, "8A")
    high = track("high.wav", 216, "8A")
    order = order_tracks([low, high], pinned=high["path"])
    assert names(order) == ["high.wav", "low.wav"]
    assert order[1]["break"] is False
    assert order[1]["band"] == "half"


def test_same_octave_beats_an_exact_double():
    order = order_tracks(
        [
            track("exact.wav", 240, "8A"),
            track("near.wav", 126, "9A"),
            track("opener.wav", 120, "8A"),
        ]
    )
    assert names(order) == ["opener.wav", "near.wav", "exact.wav"]
    assert order[1]["break"] is False
    assert order[1]["band"] is None
    assert order[2]["break"] is False
    assert order[2]["band"] == "double"


def test_smaller_same_octave_gap_wins_and_a_key_step_does_not():
    order = order_tracks(
        [
            track("same.wav", 129, "8A"),
            track("closer.wav", 122, "9A"),
            track("opener.wav", 120, "8A"),
        ]
    )
    assert names(order)[1] == "closer.wav"
    assert order[1]["break"] is False


def test_shifted_band_uses_the_smaller_gap():
    opener = track("opener.wav", 100, "8A")
    order = order_tracks(
        [
            track("half.wav", 54, "9A"),
            track("double.wav", 190, "8A"),
            opener,
        ],
        pinned=opener["path"],
    )
    assert names(order)[1] == "double.wav"
    assert order[1]["break"] is False
    assert order[1]["band"] == "double"


def test_equal_legal_gaps_use_the_filename():
    order = order_tracks(
        [
            track("b.wav", 104, "8A"),
            track("a.wav", 104, "9A"),
            track("opener.wav", 100, "8A"),
        ]
    )
    assert names(order) == ["opener.wav", "a.wav", "b.wav"]
    assert order[1]["break"] is False
    assert order[2]["break"] is False


def test_breaks_rank_same_code_then_one_step_then_a_key_jump():
    order = order_tracks(
        [
            track("two.wav", 120, "10A"),
            track("one.wav", 160, "9A"),
            track("same.wav", 160, "8A"),
            track("opener.wav", 120, "8A"),
        ]
    )
    assert names(order) == ["opener.wav", "same.wav", "one.wav", "two.wav"]
    assert [row["break"] for row in order] == [False, True, False, True]


def test_break_prefers_a_same_octave_key_jump_over_an_exact_double():
    order = order_tracks(
        [
            track("exact.wav", 240, "10A"),
            track("near.wav", 126, "10A"),
            track("opener.wav", 120, "8A"),
        ]
    )
    assert names(order) == ["opener.wav", "near.wav", "exact.wav"]
    assert order[1]["break"] is True
    assert order[1]["band"] is None
    assert order[2]["break"] is False
    assert order[2]["band"] == "double"


def test_equal_break_ranks_use_the_filename():
    order = order_tracks(
        [
            track("b.wav", 160, "3B"),
            track("a.wav", 160, "3B"),
            track("opener.wav", 120, "8A"),
        ]
    )
    assert names(order) == ["opener.wav", "a.wav", "b.wav"]
    assert order[1]["break"] is True
    assert order[2]["break"] is False


def test_each_track_appears_once_and_key_name_is_copied():
    rows = [
        track("a.wav", 100, "8A", key_name="A minor"),
        track("b.wav", 104, "8B", key_name=None),
        track("c.wav", 170, "3A", key_name="D minor"),
    ]
    order = order_tracks(rows)
    assert [row["path"] for row in order] == ["/music/a.wav", "/music/b.wav", "/music/c.wav"]
    assert [row["key_name"] for row in order] == ["A minor", None, "D minor"]
    assert rows[0]["filename"] == "a.wav"


def test_a_much_sadder_track_is_not_next_even_when_key_and_tempo_fit():
    order = order_tracks(
        [
            track("a-happy.wav", 100, "8B", valence=0.8),
            track("b-sad.wav", 100, "8B", valence=0.3),
            track("c-happy.wav", 102, "8B", valence=0.7),
        ]
    )
    # b-sad is the closest in tempo after a-happy but 0.5 darker, so it waits.
    assert names(order) == ["a-happy.wav", "c-happy.wav", "b-sad.wav"]
    assert [row["break"] for row in order] == [False, False, True]


def test_a_gentle_mood_change_is_not_a_break():
    order = order_tracks(
        [track("a.wav", 100, "8B", valence=0.5), track("b.wav", 100, "8B", valence=0.65)]
    )
    assert order[1]["break"] is False


def test_tracks_without_a_mood_fit_anywhere():
    order = order_tracks(
        [track("a.wav", 100, "8B", valence=0.9), track("b.wav", 100, "8B", valence=None)]
    )
    assert order[1]["break"] is False


def test_a_break_still_keeps_the_mood_when_it_can():
    # Neither follower fits the key, so the next row is a break; it takes the one that keeps
    # the mood even though the other has the nearer key.
    order = order_tracks(
        [
            track("a.wav", 100, "8B", valence=0.8),
            track("b-near-key-sad.wav", 100, "9B", valence=0.2),
            track("c-far-key-happy.wav", 100, "3B", valence=0.75),
        ]
    )
    assert names(order)[1] == "c-far-key-happy.wav"
    assert order[1]["break"] is True
