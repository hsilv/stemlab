import struct
import subprocess
import zlib

import pytest

from stemlab import tags

pytestmark = pytest.mark.skipif(not tags.available(), reason="ffmpeg and ffprobe are not installed")


def png():
    row = b"\x00" + bytes([200, 60, 30]) * 16

    def chunk(kind, data):
        body = kind + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * 16))
        + chunk(b"IEND", b"")
    )


def run(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args], check=True)


@pytest.fixture
def song(tmp_path):
    """An MP3 with the tags of a real release, a cover and its own tempo."""
    (tmp_path / "cover.png").write_bytes(png())
    path = tmp_path / "song.mp3"
    run(
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-i", str(tmp_path / "cover.png"),
        "-map", "0:a", "-map", "1:v", "-c:a", "libmp3lame", "-c:v", "copy", "-id3v2_version", "3",
        "-metadata", "title=Gasolina", "-metadata", "artist=Daddy Yankee",
        "-metadata", "album=Barrio Fino", "-metadata", "genre=Reggaeton", "-metadata", "date=2004",
        "-metadata", "track=3/12", "-metadata", "TBPM=96", "-metadata", "TKEY=Am",
        "-disposition:v", "attached_pic", str(path),
    )  # fmt: skip
    return path


def silent(tmp_path, suffix):
    path = tmp_path / f"target{suffix}"
    codec = {".flac": "flac", ".wav": "pcm_s24le", ".mp3": "libmp3lame"}[suffix]
    run("-f", "lavfi", "-i", "sine=frequency=220:duration=1", "-c:a", codec, str(path))
    return path


def test_read_returns_the_song_tags_its_cover_and_its_own_tempo(song):
    found = tags.read(song)
    assert found["tags"]["title"] == "Gasolina" and found["tags"]["artist"] == "Daddy Yankee"
    assert found["tags"]["album"] == "Barrio Fino" and found["tags"]["date"] == "2004"
    assert found["cover"] is True
    assert found["tempo"] == {"bpm": "96", "key": "Am"}
    # Tempo, key and the tool's own tags are not part of the song's tags.
    assert not {"tbpm", "tkey", "encoder"} & set(found["tags"])


def test_an_unreadable_file_is_refused(tmp_path):
    (tmp_path / "x.mp3").write_bytes(b"not audio")
    with pytest.raises(tags.TagError):
        tags.read(tmp_path / "x.mp3")


@pytest.mark.parametrize("suffix", [".flac", ".mp3", ".wav"])
def test_copy_puts_the_song_on_the_target_with_a_versioned_title(song, tmp_path, suffix):
    target = silent(tmp_path, suffix)
    done = tags.copy(song, target, version="Instrumental", tempo={"bpm": 128.04, "key": "Cm"})
    assert done["title"] == "Gasolina (Instrumental)"
    written = tags.read(target)
    assert written["tags"]["title"] == "Gasolina (Instrumental)"
    assert (written["tags"]["artist"], written["tags"]["album"]) == ("Daddy Yankee", "Barrio Fino")
    assert written["tags"]["genre"] == "Reggaeton" and written["tags"]["date"] == "2004"
    # The target gets the tempo it was measured at, never the original's; WAV has nowhere for it.
    assert written["tempo"] == ({} if suffix == ".wav" else {"bpm": "128.04", "key": "Cm"})
    assert written["cover"] is (suffix != ".wav") and done["cover"] is (suffix != ".wav")


def test_the_audio_of_the_target_is_untouched(song, tmp_path):
    target = silent(tmp_path, ".flac")
    before = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(target), "-f", "md5", "-"],
        capture_output=True, text=True,
    ).stdout  # fmt: skip
    tags.copy(song, target, version="Vocals")
    after = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(target), "-map", "0:a", "-f", "md5", "-"],
        capture_output=True, text=True,
    ).stdout  # fmt: skip
    assert before.strip() == after.strip()


def test_a_copy_keeps_the_targets_own_tempo_unless_told_otherwise(song, tmp_path):
    target = silent(tmp_path, ".flac")
    tags.copy(song, target, tempo={"bpm": 100.0, "key": "Dm"})
    tags.copy(song, target)
    assert tags.read(target)["tempo"] == {"bpm": "100.00", "key": "Dm"}
    tags.copy(song, target, tempo={"bpm": 120.0})
    assert tags.read(target)["tempo"] == {"bpm": "120.00", "key": "Dm"}


def test_the_cover_can_be_left_out_and_the_title_falls_back(tmp_path):
    bare = tmp_path / "bare.flac"
    run("-f", "lavfi", "-i", "sine=duration=1", "-c:a", "flac", str(bare))
    target = silent(tmp_path, ".mp3")
    done = tags.copy(bare, target, version="Extended", fallback_title="My Song")
    assert done["title"] == "My Song (Extended)" and done["cover"] is False


def test_cover_off_and_the_version_is_not_added_twice(song, tmp_path):
    target = silent(tmp_path, ".flac")
    tags.copy(song, target, cover=False)
    assert tags.read(target)["tags"]["title"] == "Gasolina"
    assert tags.read(target)["cover"] is False
    assert tags.version_title("Song (Instrumental)", "Instrumental") == "Song (Instrumental)"
    assert tags.version_title("Song", None) == "Song"


def test_extract_cover_writes_an_image_or_says_there_is_none(song, tmp_path):
    assert tags.extract_cover(song, tmp_path / "out.png") is True
    assert (tmp_path / "out.png").read_bytes().startswith(b"\x89PNG")
    bare = silent(tmp_path, ".flac")
    assert tags.extract_cover(bare, tmp_path / "none.png") is False


def test_other_containers_are_refused(song, tmp_path):
    (tmp_path / "x.ogg").write_bytes(b"")
    with pytest.raises(tags.TagError):
        tags.copy(song, tmp_path / "x.ogg")


# The Tags booth's API


from fastapi.testclient import TestClient  # noqa: E402

from stemlab import jobs  # noqa: E402
from stemlab.config import settings  # noqa: E402
from stemlab.main import app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "queue_mode", "local")
    with TestClient(app) as client:
        yield client


def stage(client, path, name=None):
    response = client.post(
        f"/api/tags/files?filename={name or path.name}", content=path.read_bytes()
    )
    assert response.status_code == 201, response.text
    return response.json()["ref"]


def test_an_upload_is_recognized_by_its_content_and_shows_its_tags(client, song):
    ref = stage(client, song, name="no-extension-at-all")
    shown = client.get("/api/tags", params={"ref": ref}).json()
    assert shown["name"] == "no-extension-at-all" and shown["container"] == ".mp3"
    assert shown["tags"]["title"] == "Gasolina" and shown["cover"] is True
    assert shown["tempo"] == {"bpm": "96", "key": "Am"} and shown["version"] is None
    cover = client.get("/api/tags/cover", params={"ref": ref})
    assert cover.status_code == 200 and cover.content.startswith(b"\x89PNG")


def test_something_that_is_not_audio_is_refused(client):
    response = client.post("/api/tags/files?filename=notes.mp3", content=b"just words")
    assert response.status_code == 422
    assert not list((settings.data_dir / "tagtool").iterdir())


def test_copying_gives_a_tagged_copy_and_leaves_both_originals_alone(client, song, tmp_path):
    source = stage(client, song)
    target_path = silent(tmp_path, ".flac")
    before = target_path.read_bytes()
    target = stage(client, target_path, name="Instrumental.flac")
    response = client.post(
        "/api/tags/copy", json={"source": source, "target": target, "version": "Instrumental"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/flac"
    result = tmp_path / "result.flac"
    result.write_bytes(response.content)
    written = tags.read(result)
    assert written["tags"]["title"] == "Gasolina (Instrumental)" and written["cover"] is True
    assert written["tags"]["artist"] == "Daddy Yankee"
    assert target_path.read_bytes() == before
    # Neither staged file is changed, and the result folder is cleaned up.
    assert tags.read(client_path(client, target))["tags"] == {}
    assert not list((settings.data_dir / "tagtool" / "scratch").iterdir())


def client_path(client, ref):
    return next((settings.data_dir / "tagtool" / ref.split(":")[1]).glob("file.*"))


def test_the_cover_can_be_left_out_and_no_version_adds_nothing(client, song, tmp_path):
    source, target = stage(client, song), stage(client, silent(tmp_path, ".mp3"), "t.mp3")
    response = client.post(
        "/api/tags/copy", json={"source": source, "target": target, "version": "", "cover": False}
    )
    result = tmp_path / "result.mp3"
    result.write_bytes(response.content)
    written = tags.read(result)
    assert written["tags"]["title"] == "Gasolina" and written["cover"] is False


def test_a_crate_output_takes_its_version_name_and_its_own_tempo(client, song, tmp_path):
    original = client.post(
        "/api/jobs?filename=Gasolina.mp3&mode=instrumental&bpm=128.04&downbeat=0&key_name=C%20minor",
        content=song.read_bytes(),
    ).json()
    folder = settings.data_dir / original["id"] / "stems"
    folder.mkdir()
    (folder / "instrumental.flac").write_bytes(silent(tmp_path, ".flac").read_bytes())
    jobs.update(original["id"], status="completed", stage="Ready")
    source, target = f"job:{original['id']}:original", f"job:{original['id']}:instrumental"
    shown = client.get("/api/tags", params={"ref": target}).json()
    assert shown["version"] == "Instrumental" and shown["container"] == ".flac"
    response = client.post("/api/tags/copy", json={"source": source, "target": target})
    assert response.status_code == 200
    result = tmp_path / "out.flac"
    result.write_bytes(response.content)
    written = tags.read(result)
    assert written["tags"]["title"] == "Gasolina (Instrumental)"
    assert written["tempo"] == {"bpm": "128.04", "key": "Cm"}
    assert (
        client.get("/api/tags", params={"ref": f"job:{original['id']}:vocals"}).status_code == 404
    )


def test_a_track_without_an_upload_has_no_original_to_read(client, song):
    job = client.post(
        "/api/jobs?filename=Gasolina.mp3&mode=instrumental", content=song.read_bytes()
    ).json()
    jobs.source_path(jobs.get(job["id"])).unlink()
    response = client.get("/api/tags", params={"ref": f"job:{job['id']}:original"})
    assert response.status_code == 404


@pytest.mark.parametrize(
    "ref", ["nope", "file:not-a-uuid", "job:1", "file:" + "0" * 32, "job:" + "0" * 32 + ":original"]
)
def test_unknown_references_are_refused(client, ref):
    assert client.get("/api/tags", params={"ref": ref}).status_code in {404, 422}


def test_old_uploads_are_swept_away(client, song, monkeypatch):
    ref = stage(client, song)
    old = client_path(client, ref).parent
    import os
    import time

    long_ago = time.time() - 7200
    os.utime(old, (long_ago, long_ago))
    stage(client, song)
    assert not old.exists()
