"""Bounded waits: 200 s default, 230 s hard cap (the agent's own ~240 s command timeout would
otherwise kill the poll mid-way and the caller loses the exit code)."""
import time

DEFAULT, CAP = 200, 230


def clamp(seconds, note):
    if seconds is None:
        return DEFAULT
    if seconds > CAP:
        note(f"--wait {seconds:g} clamped to {CAP} s")
        return CAP
    return max(0, seconds)


def until(probe, seconds, interval=0.5, max_interval=5.0):
    """Call probe() until it returns a truthy value or the deadline passes (-> None).
    The first probe runs before any sleep, so an already-settled state returns at once."""
    deadline = time.monotonic() + seconds
    while True:
        got = probe()
        if got:
            return got
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        time.sleep(min(interval, left))
        interval = min(interval * 1.5, max_interval)
