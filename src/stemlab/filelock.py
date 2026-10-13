"""One exclusive, non-blocking lock on an open file, the same on Linux and Windows.

The locks say "a process is working on this": the job folder's `.lock` and the shared
`inference.lock`. They work on an open file descriptor, so a lock held by one handle blocks every
other handle on the same file, in this process or another.
"""

import os
import sys

if sys.platform == "win32":
    import msvcrt

    def try_lock(fd):
        """True when this descriptor now holds the lock, False when someone else does."""
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def unlock(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

    def inherit(fd):
        """Popen arguments that keep the lock alive in a child. Windows cannot pass a descriptor
        to a child, so the parent keeps holding it."""
        return {}

else:
    import fcntl

    def try_lock(fd):
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def unlock(fd):
        fcntl.flock(fd, fcntl.LOCK_UN)

    def inherit(fd):
        """Popen arguments that hand the locked descriptor to a child, so the lock outlives a
        parent that dies and recovery does not release a job whose child is still running."""
        return {"pass_fds": (fd,)}
