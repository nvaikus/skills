"""Bring a mount / sync folder up (shared by `mount` and `onboard`). Sits above mounts + persist."""
from ..core import proc, wait
from ..core.errors import CliError, UsageError
from . import auth, mounts, persist, rclone


def existing(what, where, note):
    """Same dir already registered: -> (state, 'mounted'|'ok') when live with the same WHAT;
    a dead record is cleaned up (-> None) so a fresh start follows."""
    state = mounts.load(mounts.mount_id(where))
    if not state:
        return None
    live = proc.alive(persist.refresh(state)["pid"])
    if live and state["what"] != what:
        raise UsageError(f"{state['where']} already holds {state['what']}; `gdrive umount {state['where']}` first")
    if live and mounts.old_layout(state):
        if upgrade(state, note):
            return None
    if live:
        return state, ("mounted" if state["mode"] != "sync" else "ok")
    if state["mode"] != "sync" and mounts.is_mounted(state):
        mounts.unmount(state)  # stale mount point of a dead rclone
    if state.get("persist"):
        persist.remove(state, lambda: None)
    mounts.forget(state)  # the cache dir stays: queued uploads resume on this mount
    note("previous rclone for this dir was dead; starting it again")
    return None


def upgrade(state, note):
    """A live what=/ mount of the old layout -> stopped so the caller starts the new one (My Drive /
    Shared with me / Shared drives). Kept as it is while writes wait to upload. -> True when stopped."""
    if state["mode"] == "sync":
        note(f"{state['where']} is a sync folder of the old layout (My Drive at its top); to get My Drive / "
             f"Shared with me there: `gdrive umount {state['where']}`, empty the folder, mount again")
        return False
    if mounts.dirty_files(state):
        note(f"{state['where']} keeps the old layout until its pending uploads finish (`gdrive sync`); "
             "then run `gdrive mount` again")
        return False
    note(f"{state['where']}: switching to the new layout - My Drive/, Shared with me/ (+ Shared drives/)")
    if state.get("persist"):
        persist.remove(state, lambda: mounts.unmount(state))
    mounts.unmount(state)
    mounts.purge_cache(state)
    mounts.forget(state)
    return True


def bring_up(cfg, what, where, mode_req, keep, cache_limit, seconds, note):
    """-> (state, status). status: mounted | ok (sync folder synced) | starting | syncing (deadline:
    nothing undone, it continues). keep = install autostart (--persist)."""
    rclone.require()
    auth.require_remote(cfg["remote"])
    prev = mounts.load(mounts.mount_id(where))
    keep = keep or bool(prev and mounts.old_layout(prev) and prev.get("persist"))  # an upgrade keeps autostart
    old = existing(what, where, note)
    if old:
        note(f"already {'syncing' if old[0]['mode'] == 'sync' else 'mounted'} - nothing changed")
        return old
    mode, why = mounts.pick_mode(mode_req)
    if mode == "sync" and mode_req == "auto":
        note(f"no mount possible ({why}): using a sync folder instead")
    if mode == "sync" and keep:
        raise UsageError("--persist applies to mounts; a sync folder syncs on `gdrive sync`")
    mounts.check_target(where, mode)
    src = mounts.source(cfg, what)
    sub = what.partition(":")[2].strip("/").partition("/")[2] if what.startswith("shared:") else what.strip("/")
    if sub:  # a typo'd folder must fail here, not show up as an empty mount
        try:
            rclone.run(["lsjson", "--stat", src], timeout=60)
        except CliError as e:
            raise UsageError(f"{what} is not a folder on Drive", payload=e.payload) from None
    state = mounts.new_state(cfg, what, where, mode, src, cache_limit or cfg["cache_limit"])
    if mode == "sync":
        state["pid"] = mounts.launch_sync(state)
    elif keep:
        persist.install(state)
    else:
        state["pid"] = mounts.launch(state)
    mounts.save(state)
    try:
        probe = (lambda: mounts.sync_finished(state)) if mode == "sync" else (lambda: mounts.ready(state))
        rc = wait.until(probe, seconds)
    except CliError:
        if state.get("persist"):
            persist.remove(state, lambda: None)
        mounts.forget(state)
        raise
    if rc is None:
        return state, ("starting" if mode != "sync" else "syncing")
    if mode == "sync":
        mounts.record_sync(state, rc[0])
        if rc[0] != 0:
            raise CliError(f"first sync failed (exit {rc[0]}); log {state['log']}",
                           payload=[{"log": ln} for ln in proc.tail(state["log"])])
        return state, "ok"
    return state, "mounted"
