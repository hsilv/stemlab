"""Single-machine launcher with a SQLite-backed polling worker; no Docker needed."""

import os
import signal
import subprocess
import sys
import threading
import time

from stemlab.config import settings


def watch_parent(stopped):
    """Set `stopped` when the program that started us goes away.

    A parent that started us with a pipe on stdin (the desktop app) closes it when it exits or
    crashes, so reading to the end of stdin is a signal that works on every platform.
    """

    def wait():
        try:
            # The raw descriptor, not sys.stdin: a buffered reader blocked in a daemon thread
            # aborts the interpreter when it shuts down.
            while os.read(0, 4096):
                pass
        except OSError:
            pass
        stopped.set()

    threading.Thread(target=wait, daemon=True).start()


def main():
    env = {**os.environ, "STEMLAB_QUEUE_MODE": "local"}
    processes = []
    stopped = threading.Event()
    if os.environ.get("STEMLAB_EXIT_WITH_PARENT") == "1":
        watch_parent(stopped)

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        processes.append(
            subprocess.Popen(
                [sys.executable, "-m", "stemlab.local_worker"], env=env, stdin=subprocess.DEVNULL
            )
        )
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "stemlab.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(settings.port),
                ],
                env=env,
                stdin=subprocess.DEVNULL,
            )
        )
        print("StemLab is starting. Press Ctrl+C to stop both services.", flush=True)
        while not stopped.is_set() and all(process.poll() is None for process in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
