"""Mounts and sync mappings: state records, per-OS mechanism, liveness, cache, unmount.

One record per local dir (id = hash of its real path) in <data>/mounts/<id>.json (chmod 600:
it holds the rc password). The VFS cache dir is per record and survives an unmount that left
unuploaded writes: remounting the same dir resumes those uploads (live-proven with nfsmount)."""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ..core import paths, proc, profile
from ..core.errors import CliError, UsageError
from . import drive, rclone

MODES = ("auto", "mount", "sync")
WINFSP = [r"C:\Program Files (x86)\WinFsp\bin", r"C:\Program Files\WinFsp\bin"]


# ---- records -------------------------------------------------------------------------------

def _dir():
    return paths.sub(paths.data(), "mounts")


def real(where):
    return os.path.realpath(os.path.expanduser(where))


def mount_id(where):
    return hashlib.sha1(real(where).encode()).hexdigest()[:8]


def load(mid):
    p = _dir() / f"{mid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save(state):
    paths.write_private(_dir() / f"{state['id']}.json", json.dumps(state, indent=1))


def forget(state):
    (_dir() / f"{state['id']}.json").unlink(missing_ok=True)


def records():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(_dir().glob("*.json"))]


def old_layout(state):
    """A what=/ mount made before the three-folder layout (My Drive's content at its top)."""
    return state.get("what") == "/" and state.get("layout") != "all"


def _match(path, resolve):
    """(record, path relative to its dir) for a local path at/inside a mount, else (None, None).
    String match on the unresolved path first: stat-ing inside a dead NFS mount hangs the
    process uninterruptibly (live, macOS), so realpath runs only when nothing matched."""
    rs = records()

    def hit(target):
        for r in rs:
            for base in {r["where"], r.get("where_abs") or r["where"]}:
                if target == base or target.startswith(base + os.sep):
                    return r, os.path.relpath(target, base)
        return None

    found = hit(os.path.abspath(os.path.expanduser(path)))
    if not found and resolve and rs:
        found = hit(real(path))
    return found or (None, None)


def find(where_or_id):
    """A record by its id or by any path at/inside its local dir."""
    rec = load(where_or_id) if len(where_or_id) == 8 else None
    rec = rec or _match(where_or_id, resolve=True)[0]
    if not rec:
        raise UsageError(f"no gdrive mount or sync folder at {where_or_id!r}; see `gdrive status`")
    return rec


def to_drive(local):
    """A local path inside a mount/sync folder -> the Drive address it mirrors, else None."""
    if not os.path.isabs(os.path.expanduser(local)):
        return None
    r, rel = _match(local, resolve=True)
    if not r:
        return None
    rel = rel.replace(os.sep, "/")
    if r.get("layout") == "all":
        return drive.layout_address("" if rel == "." else rel)
    base = r["what"].rstrip("/")
    return base if rel == "." else f"{base}/{rel}"


# ---- mechanism -----------------------------------------------------------------------------

def _combine(upstreams):
    """[(dir, remote spec)] -> an on-the-fly rclone combine remote (connection string: values in
    '...' with ' doubled; each upstream in "..." with " doubled). Nests: a spec may be a combine."""
    ups = " ".join('"' + f"{d}={spec}".replace('"', '""') + '"' for d, spec in upstreams)
    return ":combine,upstreams='" + ups.replace("'", "''") + "':"


def everything(cfg):
    """what=/ -> combine of My Drive, Shared with me and (when the account has any) every Shared
    drive under 'Shared drives/' (combine dir names cannot hold '/': a nested combine)."""
    remote = cfg["remote"]
    ups = [(drive.MY_DIR, f"{remote}:"), (drive.SWM_DIR, f"{remote},shared_with_me:")]
    drives = drive.shared_drives(remote)
    if drives:
        segs = drive.drive_segments(drives)
        ups.append((drive.DRIVES_DIR, _combine([(segs[d["id"]], f"{remote},team_drive={d['id']}:") for d in drives])))
    return _combine(ups)


def source(cfg, what):
    """gdrive address -> rclone remote spec. Shared drives go through a connection-string override;
    / ("everything") is a combine of My Drive, Shared with me and Shared drives."""
    remote = cfg["remote"]
    if what == "/":
        return everything(cfg)
    if what.startswith("shared:"):
        name, _, sub = what[len("shared:"):].strip("/").partition("/")
        if not name:
            raise UsageError("shared: needs a Shared drive name, e.g. shared:Team")
        d = {"id": name[1:]} if name.startswith("@") else drive.shared_drive(remote, name)
        return f"{remote},team_drive={d['id']}:{sub}"
    if not what.startswith("/"):
        raise UsageError(f"WHAT must be /, /Folder/Sub or shared:<Drive>[/Sub], got {what!r}")
    return f"{remote}:{what.strip('/')}"


def fuse_helper():
    return shutil.which("fusermount3") or shutil.which("fusermount")


def winfsp():
    return any(Path(d, n).exists() for d in WINFSP for n in ("winfsp-x64.dll", "winfsp-a64.dll", "winfsp-x86.dll"))


def gdocs_note(mode):
    """Google Docs/Sheets/Slides have no size on Drive (rclone: -1). FUSE/WinFsp `mount` reads such
    files to EOF (needs --vfs-cache-mode writes, see cache_mode); NFS has no such switch: nfsmount shows them as 0-byte
    files that read back EMPTY (live-proven, no rclone flag helps). Sync folders skip them."""
    if mode == "mount":
        return None
    return ("Google Docs/Sheets/Slides " + ("read back EMPTY here (0-byte .docx/.xlsx/.pptx)" if mode == "nfsmount"
            else "are not in a sync folder") + ": read them with `gdrive doc cat` / `gdrive sheet get` (or the index)")


def pick_mode(requested):
    """-> ('mount'|'nfsmount'|'sync', why)."""
    if requested == "sync":
        return "sync", "requested"
    if sys.platform == "darwin":
        return "nfsmount", "macOS: rclone nfsmount (no kernel extension, no admin)"
    if sys.platform.startswith("linux"):
        ok = os.path.exists("/dev/fuse") and fuse_helper()
        why = "FUSE" if ok else "no /dev/fuse or fusermount3 (container? install fuse3)"
    elif os.name == "nt":
        ok = winfsp()
        why = "WinFsp" if ok else "WinFsp is not installed (winget install WinFsp.WinFsp)"
    else:
        ok, why = False, f"mounting is not supported on {sys.platform}"
    if ok:
        return "mount", why
    if requested == "mount":
        raise UsageError(f"cannot mount here: {why}; use --mode sync for a synced local folder")
    return "sync", why


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def new_state(cfg, what, where, mode, src, cache_limit):
    mid = mount_id(where)
    prof = profile.active()
    return {"id": mid, "profile": prof, "conf": str(rclone.conf()), "what": what, "source": src,
            "layout": "all" if what == "/" else None,  # all = My Drive / Shared with me / Shared drives
            "where": real(where), "mode": mode, "pid": None,
            "where_abs": os.path.abspath(os.path.expanduser(where)),
            "rc_addr": None if mode == "sync" else f"127.0.0.1:{free_port()}",
            "rc_user": "gdrive", "rc_pass": os.urandom(16).hex(),
            "cache_dir": str(paths.sub(paths.cache_root(), prof or "_", mid)), "cache_limit": cache_limit,
            "log": str(paths.sub(paths.data(), "logs") / f"{mid}.log"), "persist": None,
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "last_sync": None, "last_rc": None}


def conf_of(state):
    """The rclone.conf of the profile that owns the mount (records outlive profile switches)."""
    return state.get("conf") or str(rclone.conf())


def to_drive_profile(local):
    """A local path inside a mount -> (Drive address, owning profile) or (None, None)."""
    if not os.path.isabs(os.path.expanduser(local)):
        return None, None
    r, _ = _match(local, resolve=True)
    return (to_drive(local), r.get("profile")) if r else (None, None)


def rc_env(state):
    """The rc password travels by env, never argv (argv is world-readable in ps)."""
    return {"RCLONE_RC_USER": state["rc_user"], "RCLONE_RC_PASS": state["rc_pass"]}


def cache_mode(mode):
    """FUSE/WinFsp `mount` reads size-less Google exports to EOF only WITHOUT the full read cache:
    `full` serves them as 0 bytes (live 2026-10-01, Linux: off/minimal/writes read 6706 B, full 0).
    nfsmount reads them empty in every mode, so it keeps the full read cache."""
    return "writes" if mode == "mount" else "full"


def mount_argv(state):
    return [str(rclone.binary()), state["mode"], state["source"], state["where"],
            "--config", conf_of(state), "--vfs-cache-mode", cache_mode(state["mode"]),
            "--cache-dir", state["cache_dir"], "--vfs-cache-max-size", state["cache_limit"],
            "--rc", "--rc-addr", state["rc_addr"], "--log-level", "NOTICE"]


def bisync_argv(state, resync):
    argv = [str(rclone.binary()), "bisync", state["source"], state["where"], "--config", conf_of(state),
            "--workdir", str(Path(state["cache_dir"]) / "bisync"), "--resilient", "--recover",
            "--create-empty-src-dirs", "--drive-skip-gdocs", "--max-lock", "2m", "--log-level", "NOTICE"]
    return argv + (["--resync"] if resync else [])


def check_target(where, mode):
    p = Path(where).expanduser()
    if os.name == "nt" and mode == "mount":
        if p.exists():
            raise UsageError(f"{where} exists: on Windows the mount point must NOT exist yet (its parent must)")
        if not p.parent.exists():
            raise UsageError(f"parent folder {p.parent} does not exist")
        return
    if p.exists() and not p.is_dir():
        raise UsageError(f"{where} is a file, not a folder")
    if p.exists() and any(p.iterdir()):
        raise UsageError(f"{where} is not empty: mount/sync into an empty or new folder")
    p.mkdir(parents=True, exist_ok=True)


def launch(state):
    """Start the background mount (not persisted). -> pid."""
    return proc.spawn(mount_argv(state), state["log"], env=rc_env(state))


def launch_sync(state):
    status = Path(state["cache_dir"]) / "bisync.rc"
    status.unlink(missing_ok=True)
    state["sync_running"] = True
    return proc.spawn(bisync_argv(state, resync=state["last_sync"] is None), state["log"], status_path=status)


# ---- liveness ------------------------------------------------------------------------------

def _unescape(s):
    return s.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")


def mounted_paths():
    """Mount points from the kernel table - never stats the dir (a dead NFS server would hang it)."""
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/self/mounts", encoding="utf-8") as f:
                return {_unescape(line.split()[1]) for line in f if len(line.split()) > 1}
        except OSError:
            return set()
    if sys.platform == "darwin":
        out = subprocess.run(["/sbin/mount"], capture_output=True, text=True).stdout
        return {line.split(" on ", 1)[1].rsplit(" (", 1)[0] for line in out.splitlines() if " on " in line}
    return set()


def is_mounted(state):
    if os.name == "nt":
        return os.path.isdir(state["where"]) and rclone.rc(state, "core/pid") is not None
    return state["where"] in mounted_paths()


def ready(state):
    """Mount usable? -> True | False (still starting). Process died -> CliError with the log tail."""
    if not proc.alive(state["pid"]):
        raise CliError(f"rclone exited before the mount came up; log {state['log']}",
                       payload=[{"log": ln} for ln in proc.tail(state["log"])])
    if not is_mounted(state):
        return False
    try:
        os.listdir(state["where"])
        cache_stats(state)  # records path_meta while rclone is surely alive
        return True
    except OSError:
        return False


def sync_done(state):
    """Sync job finished? -> exit code, or None while running."""
    status = Path(state["cache_dir"]) / "bisync.rc"
    if status.exists():
        return int(status.read_text().strip() or 1)
    if not proc.alive(state["pid"]):
        return 1  # died without writing a status (killed)
    return None


def cache_stats(state):
    """-> {bytes_used, pending_uploads, errored} from the live rc, or None when it does not answer."""
    st = rclone.rc(state, "vfs/stats")
    dc = (st or {}).get("diskCache")
    if not dc:
        return None
    if dc.get("pathMeta") and state.get("path_meta") != dc["pathMeta"]:
        state["path_meta"] = dc["pathMeta"]  # lets dirty_files name paths relative to the mount
        save(state)
    out = {"bytes_used": dc.get("bytesUsed"), "pending_uploads": dc.get("uploadsInProgress", 0) + dc.get("uploadsQueued", 0),
           "errored": dc.get("erroredFiles", 0), "queued": None, "stuck": []}
    q = rclone.rc(state, "vfs/queue")
    if q is not None and isinstance(q.get("queue"), list):
        names = [e.get("name", "") for e in q["queue"]]
        out["stuck"] = [n for n in names if unuploadable(state, n)]
        out["queued"] = [n for n in names if not unuploadable(state, n)]
        out["pending_uploads"] = len(out["queued"])
    return out


def unuploadable(state, rel):
    """A file at the root of a `what=/` mount (a :combine of My Drive / Shared with me / Shared
    drives) has no backing remote: rclone retries it every 5 min forever ("combine for remote
    X: directory not found"). Typically Finder's .DS_Store. Never counted as a pending upload."""
    return state.get("source", "").startswith(":combine") and "/" not in rel.strip("/")


STUCK_HINT = ("can never upload: a file at the virtual root of a what=/ mount (only My Drive/, Shared with me/, "
              "Shared drives/ exist there) - move it into one of them or delete it; Finder's .DS_Store: "
              "`defaults write com.apple.desktopservices DSDontWriteNetworkStores -bool true`")


def dirty_files(state):
    """Files the VFS cache still has to upload (vfsMeta 'Dirty'), read from disk: works even
    when rclone is dead. -> list of paths relative to the cache's remote root."""
    meta = Path(state["cache_dir"]) / "vfsMeta"
    root = Path(state["path_meta"]) if state.get("path_meta") else None
    out = []
    if not meta.exists():
        return out
    for p in meta.rglob("*"):
        if p.is_file():
            try:
                if json.loads(p.read_text(encoding="utf-8")).get("Dirty"):
                    rel = p.relative_to(root) if root and root in p.parents else p.relative_to(meta)
                    out.append(str(rel).replace(os.sep, "/"))
            except (ValueError, OSError):
                continue
    return out


def du(path):
    total = 0
    for p in Path(path).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


# ---- stop ----------------------------------------------------------------------------------

def unmount(state):
    """Detach the mount point; rclone exits on its own (macOS nfsmount: `umount` is instant,
    SIGTERM takes ~15 s). NOTE: rclone does NOT flush queued uploads on unmount - callers check
    dirty state first."""
    where = state["where"]
    if os.name == "nt":
        proc.terminate(state["pid"])
        return
    if is_mounted(state):
        dead = not proc.alive(state["pid"])  # a dead server's mount point: plain umount would hang/fail
        if sys.platform.startswith("linux"):
            cmd = [fuse_helper() or "fusermount3", "-uz" if dead else "-u", where]
        else:
            cmd = ["/sbin/umount", *(["-f"] if dead else []), where]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0 and is_mounted(state):
            raise CliError(f"unmount failed: {p.stderr.strip() or p.stdout.strip()} (a shell or program has "
                           f"files open or its cwd inside {where}?) - still mounted")
    deadline = time.monotonic() + 20
    while proc.alive(state["pid"]) and time.monotonic() < deadline:
        time.sleep(0.3)
    proc.terminate(state["pid"])


def purge_cache(state):
    shutil.rmtree(state["cache_dir"], ignore_errors=True)


def sync_finished(state):
    """wait.until probe for a sync job: (exit_code,) once finished, else None."""
    rc = sync_done(state)
    return None if rc is None else (rc,)


def record_sync(state, rc):
    state.update(last_rc=rc, last_sync=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    state.pop("sync_running", None)
    save(state)


def settle_sync(state):
    """Bookkeeping for a background sync job: -> True while it runs; records its result once done."""
    if not state.get("sync_running"):
        return False
    rc = sync_done(state)
    if rc is None:
        return True
    record_sync(state, rc)
    return False


def human(n):
    if n is None:
        return None
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
