"""status: every mount and sync folder of this user, with liveness and cache fill."""
import os

from ...api import mounts, persist
from ...core import proc, profile

PROFILE = "none"  # works on mount records of every profile
FIELDS = ["id", "profile", "mode", "what", "where", "state", "cache_used", "cache_limit", "pending_uploads", "persist", "last_sync"]
EPILOG = """examples:
  gdrive status
  gdrive status --fields where,state,pending_uploads
  gdrive status -j          # + pid, log, cache_dir, cache_bytes, stuck_uploads
  gdrive --profile nj status   # one profile's mounts only

state: mounted · starting · dead (rclone gone: gdrive mount again) · stale (rclone gone but the
mount point is still attached: gdrive umount --force) · sync folders: ok · syncing · failed · never.
pending_uploads: writes still in the local cache, not on Drive yet. Empty = rc not answering.
stuck_uploads (-j; also a stderr note): files rclone can never upload (root of a what=/ mount),
not counted in pending_uploads.
"""


def add_args(p):
    pass


def _state(r):
    live = proc.alive(r["pid"])
    if r["mode"] == "sync":
        if mounts.settle_sync(r):
            return "syncing"
        return {None: "never", 0: "ok"}.get(r.get("last_rc"), "failed")
    mounted = mounts.is_mounted(r)
    if live:
        return "mounted" if mounted else "starting"
    return "stale" if mounted else "dead"


def run(ctx, args):
    rows = []
    for r in mounts.records():
        if profile.explicit() and r.get("profile") != profile.active():
            continue
        persist.refresh(r)
        st = _state(r)
        stats = mounts.cache_stats(r) if st in ("mounted", "starting") else None
        used = (stats or {}).get("bytes_used")
        if used is None:
            used = mounts.du(r["cache_dir"]) if os.path.isdir(r["cache_dir"]) else 0
        if stats:
            pending, stuck = stats["pending_uploads"], stats["stuck"]
        elif r["mode"] != "sync":
            dirty = mounts.dirty_files(r)
            stuck = [f for f in dirty if mounts.unuploadable(r, f)]
            pending = len(dirty) - len(stuck)
        else:
            pending, stuck = None, []
        if stuck:
            ctx.note(f"{r['where']}: {', '.join(stuck)} {mounts.STUCK_HINT}")
        rows.append({"id": r["id"], "profile": r.get("profile"), "mode": r["mode"], "what": r["what"], "where": r["where"], "state": st,
                     "cache_used": mounts.human(used), "cache_bytes": used, "cache_limit": r["cache_limit"],
                     "pending_uploads": pending, "stuck_uploads": stuck, "persist": r.get("persist"), "last_sync": r.get("last_sync"),
                     "pid": r["pid"], "log": r["log"], "cache_dir": r["cache_dir"]})
    if not rows:
        ctx.note("no mounts or sync folders (gdrive mount / ~/gdrive)")
    ctx.write(rows, FIELDS)
