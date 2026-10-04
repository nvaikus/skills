"""Per-task run slots + FIFO queue, across processes and platforms.

Runners are separate processes (launchd/systemd/schtasks, the UI, the CLI), so
the limit lives in OS file locks under runs/<task>/.queue/:

  mutex            held for a few ms around every decision
  seq              ticket counter (FIFO order)
  slot-<i>.lock    a running run holds one for its whole life
  <ticket>-<pid>.wait  a queued run holds its own while it waits

A lock dies with its process (crash, kill -9, reboot), so a dead holder frees
its slot / queue place by itself — no cleanup daemon. Liveness = "can I take
the lock?". Stale .wait files are deleted under the mutex only (a file is
created and locked under the mutex, so a probe never sees it unlocked-but-new).
POSIX: fcntl.flock (per open file, so two fds of one process conflict too).
Windows: msvcrt.locking on byte 0.
"""
import os
import time

import procs

if procs.IS_WIN:
    import msvcrt
else:
    import fcntl

POLL_MIN, POLL_MAX = 0.05, 1.0
POLL_HEAD = 0.2  # first in line polls faster: a freed slot is taken within 0.2 s


class Lock:
    """One exclusive lock on one file, held through an open fd."""

    def __init__(self, path):
        self.path = path
        self.fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
        self.held = False

    def try_lock(self):
        try:
            if procs.IS_WIN:
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self.held = True
        return True

    def lock(self):
        if not procs.IS_WIN:
            fcntl.flock(self.fd, fcntl.LOCK_EX)
            self.held = True
            return
        while not self.try_lock():
            time.sleep(0.01)

    def close(self):
        if self.fd is None:
            return
        try:
            if self.held and procs.IS_WIN:
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        os.close(self.fd)  # POSIX: closing drops the flock
        self.fd, self.held = None, False


def _free(path):
    """True when nobody holds `path` (probe: take and drop the lock)."""
    try:
        probe = Lock(path)
    except OSError:
        return False
    try:
        return probe.try_lock()
    finally:
        probe.close()


def _unlink(path):
    try:
        path.unlink()
    except OSError:
        pass  # Windows: someone has it open — a later sweep removes it


class Gate:
    """The queue directory of one task."""

    def __init__(self, qdir):
        self.dir = qdir
        self.slot = None   # Lock while this process runs
        self.wait = None   # Lock while this process waits
        self.ticket = None
        self.head = False

    # ----- helpers (call with the mutex held unless noted) -----

    def _mutex(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        m = Lock(self.dir / "mutex")
        m.lock()
        return m

    def _waiters(self):
        """Live .wait files, oldest ticket first; stale ones are deleted."""
        live = []
        for p in sorted(self.dir.glob("*.wait")):
            if self.wait is not None and p == self.wait.path:
                live.append(p)
            elif _free(p):
                _unlink(p)
            else:
                live.append(p)
        return live

    def _active(self):
        return sum(1 for p in self.dir.glob("slot-*.lock") if not _free(p))

    def _take_slot(self):
        i = 0
        while True:
            lk = Lock(self.dir / f"slot-{i}.lock")
            if lk.try_lock():
                self.slot = lk
                return
            lk.close()
            i += 1

    def _next_ticket(self):
        p = self.dir / "seq"
        try:
            n = int(p.read_text(encoding="ascii").strip() or 0) + 1
        except (OSError, ValueError):
            n = 1
        p.write_text(str(n), encoding="ascii")
        return n

    # ----- the protocol -----

    def enter(self, parallel, queue):
        """-> "run" (a slot is held), "queued" (a place in line is held) or
        ("full", waiting) (nothing held: the run must be skipped)."""
        m = self._mutex()
        try:
            waiting = self._waiters()
            if not waiting and self._active() < parallel:
                self._take_slot()
                return "run"
            if len(waiting) >= queue:
                return ("full", len(waiting))
            self.ticket = self._next_ticket()
            lk = Lock(self.dir / f"{self.ticket:012d}-{os.getpid()}.wait")
            while not lk.try_lock():  # only a queued_count() probe can hold it, for microseconds
                time.sleep(0.001)
            self.wait = lk
            return "queued"
        finally:
            m.close()

    def advance(self, parallel):
        """Queued: True once this run is first in line and a slot is free (the
        slot is then held and the place in line given up). Sets self.head."""
        m = self._mutex()
        try:
            waiting = self._waiters()
            self.head = bool(waiting) and waiting[0] == self.wait.path
            if not self.head or self._active() >= parallel:
                return False
            self._take_slot()
            path = self.wait.path
            self.wait.close()
            self.wait = None
            _unlink(path)
            return True
        finally:
            m.close()

    def position(self):
        """1-based place in line (no mutex; informational)."""
        if self.wait is None:
            return 0
        mine = self.wait.path.name
        return 1 + sum(1 for p in self.dir.glob("*.wait") if p.name < mine and not _free(p))

    def wait_turn(self, parallel_now, stop_after=None):
        """Block until advance() succeeds. `parallel_now()` is re-read every poll
        (an edit to `parallel` takes effect for waiting runs). Polls with
        backoff, never above POLL_MAX."""
        delay, t0 = POLL_MIN, time.monotonic()
        while not self.advance(parallel_now()):
            if stop_after is not None and time.monotonic() - t0 > stop_after:
                return False
            time.sleep(min(delay, POLL_HEAD) if self.head else delay)
            delay = min(delay * 2, POLL_MAX)
        return True

    def release(self):
        for attr in ("slot", "wait"):
            lk = getattr(self, attr)
            if lk is not None:
                path = lk.path
                lk.close()
                setattr(self, attr, None)
                if attr == "wait":
                    _unlink(path)


def queued_count(qdir):
    """Runs waiting in line right now (read-only probe, no mutex)."""
    if not qdir.is_dir():
        return 0
    return sum(1 for p in qdir.glob("*.wait") if not _free(p))
