import os
import sys

import pytest

from stemlab import filelock
from stemlab.environment import default_mixxx_db, venv_python


def open_fd(path):
    return os.open(path, os.O_RDWR | os.O_CREAT)


def test_a_second_descriptor_cannot_take_a_held_lock_until_it_is_released(tmp_path):
    path = tmp_path / "job.lock"
    first, second = open_fd(path), open_fd(path)
    try:
        assert filelock.try_lock(first)
        assert not filelock.try_lock(second)
        filelock.unlock(first)
        assert filelock.try_lock(second)
        filelock.unlock(second)
    finally:
        os.close(first)
        os.close(second)


def test_a_closed_descriptor_releases_its_lock(tmp_path):
    path = tmp_path / "job.lock"
    first = open_fd(path)
    assert filelock.try_lock(first)
    os.close(first)
    second = open_fd(path)
    try:
        assert filelock.try_lock(second)
    finally:
        os.close(second)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot pass a descriptor to a child")
def test_a_child_inherits_the_locked_descriptor(tmp_path):
    fd = open_fd(tmp_path / "job.lock")
    try:
        assert filelock.inherit(fd) == {"pass_fds": (fd,)}
    finally:
        os.close(fd)


def test_environment_paths_match_the_platform(tmp_path):
    interpreter = venv_python(tmp_path / ".venv")
    assert interpreter.parts[-2:] == (
        ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    )
    assert default_mixxx_db().name == "mixxxdb.sqlite"
