"""Validated output plans shared by the API, worker and inference process."""

STEMS = ("vocals", "drums", "bass", "other")
MODES = ("all", "vocals", "instrumental", "custom", "extend", "generate")
# New jobs write FLAC. Jobs finished before that hold float WAV files under the same names.
STEM_SUFFIX = ".flac"
LEGACY_STEM_SUFFIX = ".wav"
LABELS = {"vocals": "Vocals", "drums": "Drums", "bass": "Bass", "other": "Other instruments"}


def is_instrumental(plan):
    """True when the output is exactly drums + bass + other summed: the inverse of the vocals."""
    return len(plan) == 1 and set(plan[0]["sources"]) == set(STEMS[1:])


def output_plan(mode="all", keep=None):
    if mode not in MODES:
        raise ValueError("Unknown separation mode.")
    if mode != "custom" and keep is not None:
        raise ValueError("Choose sources only when using Custom mix.")
    if mode == "all":
        groups = [(stem, LABELS[stem], [stem]) for stem in STEMS]
    elif mode == "vocals":
        groups = [("vocals", "Vocals only", ["vocals"])]
    elif mode == "instrumental":
        groups = [("instrumental", "Instrumental (no vocals)", list(STEMS[1:]))]
    elif mode == "extend":
        groups = [("extended", "Extended edit", list(STEMS))]
    elif mode == "generate":
        groups = [("backing", "Backing track", list(STEMS))]
    else:
        if not keep or len(keep) != len(set(keep)) or any(stem not in STEMS for stem in keep):
            raise ValueError("Select at least one source, without duplicates, from the four stems.")
        sources = [stem for stem in STEMS if stem in keep]
        groups = [("mix", "Custom mix", sources)]
    return [{"id": name, "label": label, "sources": sources} for name, label, sources in groups]


def stem_file(folder, stem_id):
    """The stored file for one output, whichever format the job was written in; None if absent."""
    for suffix in (STEM_SUFFIX, LEGACY_STEM_SUFFIX):
        path = folder / f"{stem_id}{suffix}"
        if path.is_file():
            return path
    return None
