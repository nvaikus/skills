"""--persist: the mount comes back after reboot/login. Linux: systemd user unit. macOS: LaunchAgent.
The service owns the rclone process; gdrive only installs/removes it."""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from ..core.errors import CliError, UsageError
from . import mounts


def kind():
    if sys.platform.startswith("linux"):
        return "systemd"
    if sys.platform == "darwin":
        return "launchd"
    raise UsageError("--persist is not supported on this OS in v1 (Linux systemd / macOS launchd only)")


def run_cmd(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise CliError(f"{' '.join(cmd[:3])} failed: {(p.stderr or p.stdout).strip()}")
    return p.stdout


# ---- systemd -------------------------------------------------------------------------------

def _unit_name(state):
    return f"gdrive-{state['id']}.service"


def _unit_path(state):
    return Path("~/.config/systemd/user").expanduser() / _unit_name(state)


def sd_quote(arg):
    return '"' + arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


def systemd_unit(state):
    env = "".join(f"Environment={sd_quote(f'{k}={v}')}\n" for k, v in mounts.rc_env(state).items())
    return (f"[Unit]\nDescription=gdrive mount {state['what']} -> {state['where']}\n"
            "Wants=network-online.target\nAfter=network-online.target\n\n"
            f"[Service]\nType=simple\n{env}"
            f"ExecStartPre=-{sd_quote(mounts.fuse_helper() or 'fusermount3')} -uz {sd_quote(state['where'])}\n"
            f"ExecStart={' '.join(sd_quote(a) for a in mounts.mount_argv(state))}\n"
            f"ExecStop={sd_quote(mounts.fuse_helper() or 'fusermount3')} -u {sd_quote(state['where'])}\n"
            f"StandardOutput=append:{state['log']}\nStandardError=append:{state['log']}\n"
            "Restart=on-failure\nRestartSec=10\n\n[Install]\nWantedBy=default.target\n")


# ---- launchd -------------------------------------------------------------------------------

def _label(state):
    return f"gdrive.mount.{state['id']}"


def _plist_path(state):
    return Path("~/Library/LaunchAgents").expanduser() / f"{_label(state)}.plist"


def launchd_plist(state):
    return plistlib.dumps({
        # live: after rclone crashed the dead NFS mount point stayed attached and every restart
        # failed "already mounted" -> force-unmount the stale point before each start
        "Label": _label(state),
        "ProgramArguments": ["/bin/sh", "-c", '/sbin/umount -f "$0" 2>/dev/null; exec "$@"', state["where"],
                             *mounts.mount_argv(state)],
        # No KeepAlive on purpose (live): a restart after a crash does not recover the wedged NFS
        # mount point, and processes touching it hang uninterruptibly. Start at login only;
        # `gdrive status` shows "stale", `gdrive mount` again force-unmounts and restarts.
        "EnvironmentVariables": mounts.rc_env(state), "RunAtLoad": True,
        "StandardOutPath": state["log"], "StandardErrorPath": state["log"]})


def domain():
    return f"gui/{os.getuid()}"


def bootstrap(label, path):
    """(Re)load a LaunchAgent and start it now. Live (macOS 26+): a bootstrapped RunAtLoad job can sit
    in "pended nondemand spawn = speculative" for hours, never run; kickstart forces the first run."""
    subprocess.run(["launchctl", "bootout", f"{domain()}/{label}"], capture_output=True)
    run_cmd(["launchctl", "bootstrap", domain(), str(path)])
    run_cmd(["launchctl", "kickstart", f"{domain()}/{label}"])


# ---- install / remove ----------------------------------------------------------------------

def write_unit(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # holds the rc password
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def install(state):
    """Write + start the service; state gets persist/unit/pid."""
    k = kind()
    if k == "systemd":
        path = _unit_path(state)
        write_unit(path, systemd_unit(state).encode())
        run_cmd(["systemctl", "--user", "daemon-reload"])
        run_cmd(["systemctl", "--user", "enable", "--now", _unit_name(state)])
    else:
        path = _plist_path(state)
        write_unit(path, launchd_plist(state))
        bootstrap(_label(state), path)
    state.update(persist=k, unit=str(path))
    state["pid"] = service_pid(state)


def service_pid(state, tries=20):
    import time
    for _ in range(tries):
        if state["persist"] == "systemd":
            out = subprocess.run(["systemctl", "--user", "show", "-p", "MainPID", "--value", _unit_name(state)],
                                 capture_output=True, text=True).stdout.strip()
            pid = int(out) if out.isdigit() else 0
        else:
            out = subprocess.run(["launchctl", "print", f"{domain()}/{_label(state)}"],
                                 capture_output=True, text=True).stdout
            pid = next((int(ln.split("=")[1]) for ln in out.splitlines()
                        if ln.strip().startswith("pid =") and ln.split("=")[1].strip().isdigit()), 0)
        if pid or tries == 1:
            return pid or None
        time.sleep(0.25)
    return None


def remove(state, before_stop):
    """Stop the service without it restarting the mount, then delete the unit.
    before_stop(): unmount step for launchd (rclone exits 0 on umount, so KeepAlive leaves it)."""
    if state.get("persist") == "systemd":
        subprocess.run(["systemctl", "--user", "disable", "--now", _unit_name(state)], capture_output=True)
        Path(state["unit"]).unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    elif state.get("persist") == "launchd":
        before_stop()
        subprocess.run(["launchctl", "bootout", f"{domain()}/{_label(state)}"], capture_output=True)
        Path(state["unit"]).unlink(missing_ok=True)


def rewrite(state):
    """Point an installed unit at changed paths (profile rename) without starting it: systemd
    reloads the file; launchd reads the plist at the next login or `gdrive mount`."""
    if state.get("persist") == "systemd":
        write_unit(Path(state["unit"]), systemd_unit(state).encode())
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    elif state.get("persist") == "launchd":
        write_unit(Path(state["unit"]), launchd_plist(state))


def refresh(state):
    """A persisted mount's pid changes on every service restart: read it from the service."""
    if state.get("persist"):
        pid = service_pid(state, tries=1)
        if pid != state.get("pid"):
            state["pid"] = pid
            mounts.save(state)
    return state
