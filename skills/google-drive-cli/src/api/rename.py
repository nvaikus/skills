"""Profile rename: everything keyed by the profile name follows - the profile dir, the root
default, mount records (profile, conf, cache_dir), the VFS cache root (queued uploads resume
after a remount), installed mount units, the index service and the index log.
Refused while the profile has a live mount, a sync pass, an onboarding job or an index run."""
import os
from pathlib import Path

from ..core import paths, proc, profile
from ..core.errors import CliError, Refused, UsageError
from . import autoconsole, indexer, mounts, persist, service


def _busy(rec):
    """Why a mount record blocks the rename, or None. Reads the kernel table only (never stats
    inside the mount: a dead macOS NFS mount hangs the process)."""
    if rec.get("mode") == "sync":
        return "a sync pass is running" if mounts.settle_sync(rec) else None
    rec = persist.refresh(rec)
    if mounts.is_mounted(rec):
        return "mounted"
    if proc.alive(rec.get("pid")):
        return "its rclone process is still running"
    return None


def _moved(value, old_base, new_base):
    if value and (value == old_base or value.startswith(old_base + os.sep)):
        return new_base + value[len(old_base):]
    return value


def check(old, new):
    """Every refusal before anything changes. -> the old profile's mount records."""
    have = profile.names()
    if old not in have:
        raise UsageError(f"no profile {old!r}; profiles: {', '.join(have) or 'none'}")
    profile.check_name(new)
    if new == old:
        raise UsageError(f"{old!r} is already the name")
    if new in have or (paths.root_peek() / new).exists():
        raise Refused(f"{paths.root_peek() / new} already exists - pick another name; nothing changed")
    cache_new = paths.cache_root() / new
    if cache_new.exists() and any(cache_new.iterdir()):
        raise Refused(f"{cache_new} exists (VFS cache of an earlier {new!r}?) - pick another name or remove it "
                      "after checking it holds no unuploaded files; nothing changed")
    recs = [r for r in mounts.records() if r.get("profile") == old]
    busy = [f"{r['where']} ({why})" for r in recs for why in [_busy(r)] if why]
    if busy:
        raise Refused(f"profile {old!r} is in use: {'; '.join(busy)} - `gdrive umount <dir>` first "
                      "(it refuses while uploads are pending), mount again after the rename; nothing changed")
    if autoconsole.status(old).get("alive"):
        raise Refused(f"an onboarding job of {old!r} is running - finish or stop it first; nothing changed")
    pid = indexer.Lock(old).holder()
    if pid:
        raise Refused(f"an index update of {old!r} is running (pid {pid}) - retry when it ends; nothing changed")
    return recs


def rename(old, new):
    """-> {'records': n, 'service': state, 'default': bool}."""
    recs = check(old, new)
    svc = service.state(old)
    if svc in ("on", "broken"):
        service.remove(old)
        pid = indexer.Lock(old).holder()  # a tick may have started meanwhile
        if pid:
            service.install(old)
            raise Refused(f"an index update of {old!r} just started (pid {pid}) - retry when it ends; nothing changed")

    root = paths.root()
    try:
        os.rename(root / old, root / new)
    except OSError as e:
        if svc in ("on", "broken"):
            service.install(old)
        raise CliError(f"cannot rename {root / old}: {e} (a program has files open in it?) - nothing changed") from None

    cache_old, cache_new = paths.cache_root() / old, paths.cache_root() / new
    if cache_old.exists():
        if cache_new.exists():
            cache_new.rmdir()  # empty (check() refuses a non-empty one)
        os.rename(cache_old, cache_new)

    log_old = indexer.log_path(old)
    if log_old.exists():
        os.replace(log_old, indexer.log_path(new))

    conf = str(root / new / "rclone.conf")
    for r in recs:
        r.update(profile=new, conf=conf,
                 cache_dir=_moved(r.get("cache_dir"), str(cache_old), str(cache_new)),
                 path_meta=_moved(r.get("path_meta"), str(cache_old), str(cache_new)))
        if r.get("persist") and r.get("unit") and Path(r["unit"]).exists():
            persist.rewrite(r)
        mounts.save(r)

    was_default = profile.root_config().get("default_profile") == old
    if was_default:
        profile.set_default(new)
    if svc in ("on", "broken"):
        service.install(new)
    return {"records": len(recs), "service": service.state(new), "default": was_default}
