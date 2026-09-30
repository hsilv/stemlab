"""Validated output plans shared by the API, worker and inference process."""

STEMS = ("vocals", "drums", "bass", "other")
MODES = ("all", "vocals", "instrumental", "custom")
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
    else:
        if not keep or len(keep) != len(set(keep)) or any(stem not in STEMS for stem in keep):
            raise ValueError("Select at least one source, without duplicates, from the four stems.")
        sources = [stem for stem in STEMS if stem in keep]
        groups = [("mix", "Custom mix", sources)]
    return [{"id": name, "label": label, "sources": sources} for name, label, sources in groups]
