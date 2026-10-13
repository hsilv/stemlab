import os
import socket
import subprocess
import sys
import time


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_the_launcher_stops_when_its_parent_closes_stdin(tmp_path):
    env = {
        **os.environ,
        "STEMLAB_EXIT_WITH_PARENT": "1",
        "STEMLAB_DATA_DIR": str(tmp_path / "data"),
        "STEMLAB_PORT": str(free_port()),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "stemlab.local"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        time.sleep(1.5)
        assert process.poll() is None
        process.stdin.close()
        assert process.wait(timeout=30) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
