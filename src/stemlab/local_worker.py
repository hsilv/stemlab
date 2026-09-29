import signal
import time

from stemlab import jobs
from stemlab.config import settings
from stemlab.worker import separate_job


def stop(signum, frame):
    raise SystemExit(0)


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    jobs.recover_stale()
    while True:
        with jobs.database() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1"
            ).fetchone()
        (settings.data_dir / "worker.heartbeat").touch()
        if row:
            separate_job.apply(args=[row["id"]], task_id=row["task_id"])
        else:
            time.sleep(1)


if __name__ == "__main__":
    main()
