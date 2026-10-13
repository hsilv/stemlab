"""Tags and cover art of audio files, read with ffprobe and copied with ffmpeg.

A file made from a song (an instrumental, a stem, an extended edit) should read as that
song in a DJ library: same artist, album, genre, year and cover, and a title that says what
this version is. Everything here needs ffmpeg and ffprobe; without them nothing is copied.
"""

import json
import shutil
import subprocess
from pathlib import Path

TIMEOUT = 120
# What a version adds to the song's title: "Song (Instrumental)".
VERSION_NAMES = {
    "vocals": "Vocals",
    "drums": "Drums",
    "bass": "Bass",
    "other": "Other",
    "instrumental": "Instrumental",
    "mix": "Custom mix",
    "extended": "Extended",
}
# Tags that describe the audio or the tool that wrote it, not the song. Tempo and key are
# measured per file, so a copy keeps its own.
_NOT_COPIED = {
    "encoder", "encoded_by", "tsse", "tenc", "major_brand", "minor_version",
    "compatible_brands", "creation_time", "duration", "tlen", "length", "bpm", "tbpm",
    "initialkey", "tkey",
}  # fmt: skip
_TEMPO = {"bpm": ("bpm", "tbpm"), "key": ("initialkey", "tkey")}
# How each container names tempo and key.
_TEMPO_NAMES = {
    ".flac": {"bpm": "BPM", "key": "INITIALKEY"},
    ".mp3": {"bpm": "TBPM", "key": "TKEY"},
    ".wav": {"bpm": "TBPM", "key": "TKEY"},
}
# What ffprobe calls each container, by the suffix its files should have.
_CONTAINERS = {"mp3": ".mp3", "flac": ".flac", "wav": ".wav"}
COVER_FORMATS = {".mp3", ".flac"}
FORMATS = set(_TEMPO_NAMES)


class TagError(RuntimeError):
    """The file could not be read or written."""


def available():
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def read(path):
    """{"tags": {name: text} (names lower case, tool tags left out), "tempo", "cover", "container"}.

    tempo holds the file's own "bpm" and "key" when it has them; container is ".mp3", ".flac" or
    ".wav" by what is inside the file, whatever it is named, and None for anything else.
    """
    command = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_entries", "format=format_name:format_tags:stream=codec_type", str(path),
    ]  # fmt: skip
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT)
        data = json.loads(result.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise TagError("Could not read this file.") from exc
    if result.returncode or not data.get("streams"):
        raise TagError("This is not a readable audio file.")
    raw = {
        str(name).lower(): str(value)
        for name, value in data.get("format", {}).get("tags", {}).items()
    }
    tempo = {
        label: next((raw[name] for name in names if raw.get(name)), None)
        for label, names in _TEMPO.items()
    }
    tags = {
        name: value
        for name, value in raw.items()
        if name not in _NOT_COPIED and not name.startswith("replaygain") and value
    }
    cover = any(stream.get("codec_type") == "video" for stream in data["streams"])
    names = str(data.get("format", {}).get("format_name", "")).split(",")
    container = next((suffix for name, suffix in _CONTAINERS.items() if name in names), None)
    return {
        "tags": tags,
        "tempo": {k: v for k, v in tempo.items() if v},
        "cover": cover,
        "container": container,
    }


def key_tag(key_name):
    """A key as DJ software writes it: 'A minor' is 'Am', 'Bb major' is 'Bb'. None without one."""
    if not key_name:
        return None
    tonic, _, mode = key_name.partition(" ")
    return tonic + ("m" if mode == "minor" else "")


def output_arguments(row, stem):
    """copy() arguments for one output of a job: its version name and the job's tempo and key."""
    return {
        "version": VERSION_NAMES.get(stem),
        "tempo": {"bpm": row.get("bpm"), "key": key_tag(row.get("key_name"))},
        "fallback_title": Path(row["filename"]).stem,
    }


def version_title(title, version):
    """The title with what this version is: 'Song' becomes 'Song (Instrumental)'."""
    if not version or not title:
        return title
    if title.lower().endswith(f"({version.lower()})"):
        return title
    return f"{title} ({version})"


def copy(source, target, *, version=None, tempo=None, cover=True, fallback_title=None):
    """Write source's tags and cover onto target (an mp3, flac or wav), replacing its own.

    version is added to the title in parentheses. tempo ({"bpm", "key"}) overrides the tempo
    and key the target already has; those two are never taken from source. fallback_title
    stands in when source has no title. Returns what was written.
    """
    target = Path(target)
    suffix = target.suffix.lower()
    if suffix not in FORMATS:
        raise TagError("Tags can be written to MP3, FLAC and WAV files.")
    given, own = read(source), read(target)
    tags = dict(given["tags"])
    title = tags.get("title") or fallback_title
    if title:
        tags["title"] = version_title(title, version)
    wanted = {**own["tempo"], **{k: v for k, v in (tempo or {}).items() if v}}
    for label, value in wanted.items():
        tags[_TEMPO_NAMES[suffix][label]] = f"{float(value):.2f}" if label == "bpm" else str(value)
    with_cover = cover and given["cover"] and suffix in COVER_FORMATS
    command = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(target)]
    if with_cover:
        command += ["-i", str(source)]
    command += ["-map", "0:a"]
    if with_cover:
        command += ["-map", "1:v", "-c:v", "copy", "-disposition:v", "attached_pic"]
    command += ["-c:a", "copy", "-map_metadata", "-1"]
    if suffix == ".wav":
        command += ["-write_id3v2", "1"]
    if suffix == ".mp3":
        command += ["-id3v2_version", "3"]
    for name, value in tags.items():
        command += ["-metadata", f"{name}={value}"]
    written = target.with_name(f"{target.stem}.tagged{suffix}")
    command.append(str(written))
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        written.unlink(missing_ok=True)
        raise TagError("Could not write the tags.") from exc
    if result.returncode:
        written.unlink(missing_ok=True)
        raise TagError(f"Could not write the tags: {result.stderr.strip()[-200:]}")
    written.replace(target)
    return {"title": tags.get("title"), "fields": len(tags), "cover": with_cover}


def extract_cover(path, target):
    """Write the cover of path to target (a .png or .jpg path); False when there is none."""
    command = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-i",
        str(path),
        "-an",
        "-c:v",
        "copy",
        "-frames:v",
        "1",
        str(target),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and Path(target).is_file()
