"""Single-machine launcher with a SQLite-backed polling worker; no Docker needed."""

import os
import signal
import subprocess
import sys
import time

from stemlab.config import settings


def main():
    env = {**os.environ, "STEMLAB_QUEUE_MODE": "local"}
    processes = []

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        processes.append(subprocess.Popen([sys.executable, "-m", "stemlab.local_worker"], env=env))
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
            )
        )
        print("StemLab is starting. Press Ctrl+C to stop both services.", flush=True)
        while all(process.poll() is None for process in processes):
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
