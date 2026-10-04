"""umount: detach a mount (or stop a sync folder). Refuses while writes are not uploaded yet."""
from ...api import mounts, persist
from ...core import proc, rails, wait
from ...core.errors import CliError, Deadline, Refused

PROFILE = "none"  # works on mount records of every profile
FIELDS = ["id", "mode", "what", "where", "status"]
WRITE = True
WAIT = True
EPILOG = """examples:
  gdrive umount ~/gdrive
  gdrive sync ~/gdrive && gdrive umount ~/gdrive     # wait for uploads first
  gdrive umount ~/gdrive --force                     # leave pending uploads in the cache

Exit 3 lists the files still waiting to upload (stdout) - rclone does NOT flush them on
unmount. `gdrive sync <dir>` waits for them. With --force they stay in ~/.cache/gdrive/<id> and
upload the next time the same WHAT is mounted at the same dir. --persist mounts lose autostart.
Sync folder: runs a final sync pass first (--force skips it); the local files stay where they are.
Exit 1 "busy" = a shell or program has its cwd or open files inside the mount.
"""


def add_args(p):
    p.add_argument("where", help="the mount dir (or any path inside it), or the id from gdrive status")
    p.add_argument("--force", action="store_true", help="unmount even with pending uploads / skip the final sync")


def _row(state, status):
    return {**{k: state.get(k) for k in ("id", "mode", "what", "where")}, "status": status}


def _mount(ctx, state, force):
    stats = mounts.cache_stats(state) if proc.alive(state["pid"]) else None
    dirty = mounts.dirty_files(state)
    stuck = [f for f in dirty if mounts.unuploadable(state, f)]
    dirty = [f for f in dirty if f not in stuck]
    pending = max(len(dirty), (stats or {}).get("pending_uploads", 0))
    if stuck:
        ctx.note(f"dropped with the cache: {', '.join(stuck)} {mounts.STUCK_HINT}")
    errored = (stats or {}).get("errored", 0)
    if pending or errored:
        rows = [{"pending_upload": f} for f in dirty] or [{"pending_upload": f"{pending} file(s) (names unknown)"}]
        rails.confirm(ctx, rows, ["pending_upload"], force,
                      f"{pending} file(s) not uploaded yet" + (f", {errored} failed" if errored else "")
                      + f"; `gdrive sync {state['where']}` waits for them")
    if state.get("persist"):
        persist.remove(state, lambda: mounts.unmount(state))
    mounts.unmount(state)
    if dirty:
        ctx.note(f"{len(dirty)} unuploaded file(s) kept in {state['cache_dir']}: mount {state['what']} at "
                 f"{state['where']} again to upload them")
    else:
        mounts.purge_cache(state)
    mounts.forget(state)
    ctx.write([_row(state, "unmounted")], FIELDS, receipt=True)


def _sync(ctx, state, force, seconds):
    if mounts.settle_sync(state):
        raise Refused(f"a sync pass is running; `gdrive sync {state['where']}` waits for it - nothing changed")
    if not force:
        state["pid"] = mounts.launch_sync(state)
        mounts.save(state)
        rc = wait.until(lambda: mounts.sync_finished(state), seconds)
        if rc is None:
            raise Deadline(f"final sync still running after {seconds:g} s - NOTHING WAS UNDONE, the folder is "
                           f"still registered; rerun `gdrive umount {state['where']}` when `gdrive status` shows it done")
        mounts.record_sync(state, rc[0])
        if rc[0] != 0:
            raise CliError(f"final sync failed (exit {rc[0]}) - still registered; log {state['log']} "
                           "(--force detaches without it)", payload=[{"log": ln} for ln in proc.tail(state["log"])])
    mounts.purge_cache(state)
    mounts.forget(state)
    ctx.note(f"the files stay in {state['where']}; it is no longer synced")
    ctx.write([_row(state, "detached")], FIELDS, receipt=True)


def run(ctx, args):
    state = persist.refresh(mounts.find(args.where))
    if state["mode"] == "sync":
        return _sync(ctx, state, args.force, args.wait)
    return _mount(ctx, state, args.force)
