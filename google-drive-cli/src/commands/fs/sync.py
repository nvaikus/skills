"""sync: a sync folder runs one two-way pass; a mount waits until its queued uploads are on Drive."""
import time

from ...api import mounts, persist
from ...core import proc, wait
from ...core.errors import CliError, Deadline

PROFILE = "none"  # works on mount records of every profile
FIELDS = ["id", "mode", "where", "status", "pending_uploads"]
WRITE = True
WAIT = True
EPILOG = """examples:
  gdrive sync ~/gdrive              # after writing into a sync folder, or to see remote changes
  gdrive sync                       # every mount and sync folder
  gdrive sync ~/gdrive --wait 60

Mount: nothing is transferred by this command - it waits until the VFS cache has uploaded
everything written so far (run it before telling anyone a file is on Drive).
Sync folder: `rclone bisync` both ways; conflicting edits keep both copies (*.conflict1/2);
more than half the files deleted on one side aborts the pass (exit 1, nothing deleted).
Exit 6: still uploading/syncing in the background - nothing undone; rerun to keep waiting
(stderr names the files it waits on). A file at the root of a what=/ mount can never upload:
it is named on stderr and not waited for.
"""


def add_args(p):
    p.add_argument("where", nargs="?", help="mount/sync dir or id (default: all)")


def _mount(state, deadline, note):
    if not proc.alive(state["pid"]):
        raise CliError(f"rclone for {state['where']} is not running (gdrive status); pending writes upload on remount")
    last = {}

    def probe():
        st = mounts.cache_stats(state)
        last.update(st or {})
        return st is not None and st["pending_uploads"] == 0

    ok = wait.until(probe, max(0, deadline - time.monotonic()))
    if last.get("errored"):
        hint = ("; a file inside an item shared view-only can never upload: move it under My Drive/"
                if state.get("layout") == "all" else "")
        raise CliError(f"{last['errored']} upload(s) failed for {state['where']}{hint}; see {state['log']}",
                       payload=[{"log": ln} for ln in proc.tail(state["log"])])
    if last.get("stuck"):
        note(f"{state['where']}: {', '.join(last['stuck'])} {mounts.STUCK_HINT}")
    if not ok and last.get("queued"):
        note(f"{state['where']}: waiting on {', '.join(last['queued'][:10])}"
             + (f" (+{len(last['queued']) - 10} more)" if len(last["queued"]) > 10 else "") + f"; log {state['log']}")
    return ("uploaded" if ok else None), last.get("pending_uploads")


def _sync(state, deadline, note):
    if not mounts.settle_sync(state):
        state["pid"] = mounts.launch_sync(state)
        mounts.save(state)
    rc = wait.until(lambda: mounts.sync_finished(state), max(0, deadline - time.monotonic()))
    if rc is None:
        return None, None
    mounts.record_sync(state, rc[0])
    if rc[0] != 0:
        raise CliError(f"sync of {state['where']} failed (exit {rc[0]}); log {state['log']}",
                       payload=[{"log": ln} for ln in proc.tail(state["log"])])
    return "synced", None


def run(ctx, args):
    targets = [persist.refresh(t) for t in ([mounts.find(args.where)] if args.where else mounts.records())]
    if not targets:
        ctx.note("no mounts or sync folders")
    deadline = time.monotonic() + args.wait
    rows, late = [], []
    for st in targets:
        status, pending = (_sync if st["mode"] == "sync" else _mount)(st, deadline, ctx.note)
        if status is None:
            late.append(st["where"])
        rows.append({"id": st["id"], "mode": st["mode"], "where": st["where"],
                     "status": status or "running", "pending_uploads": pending})
    ctx.write(rows, FIELDS)
    if late:
        raise Deadline(f"still running after {args.wait:g} s: {', '.join(late)} - NOTHING WAS UNDONE; "
                       "rerun `gdrive sync` to keep waiting")
