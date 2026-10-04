"""macOS: one LaunchAgent per task in ~/Library/LaunchAgents.

The agent runs `zsh -lic "exec '<entry>' _exec '<task>'"` (shebang python3): login +
interactive, so .zprofile AND .zshrc load (PATH, keychain-fed credentials).
TERM=dumb keeps shell integrations from writing escape codes into the io log.
StartCalendarInterval is the cartesian product of the cron fields (capped at
512); launchd ANDs day and weekday, which is this tool's cron meaning, and runs
a start missed during sleep once on wake.

Drift = plist bytes differ, or the label is not loaded. Labels outside
`com.claude.clockmaster.` are never touched (the UI agent sits outside it).
"""
import os
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path

import cron
import identity
from errors import Conflict

name = "launchd"
label = "LAUNCHD"
CAP = 512
# Privacy-protected folders (TCC): the first access from a launchd-started
# process raises a consent prompt nobody sees, and the run blocks on it.
TCC_DIRS = ("Documents", "Desktop", "Downloads")


def agents_dir():
    return identity.home() / "Library" / "LaunchAgents"


def plist_path(task_name):
    return agents_dir() / f"{identity.LAUNCHD_PREFIX}{task_name}.plist"


def io_log(task_name):
    return identity.data_dir() / "launchd-io" / f"{task_name}.log"


def _sq(s):
    return "'" + str(s).replace("'", "'\\''") + "'"


def plist_bytes(task):
    env = {"TERM": "dumb"}
    if os.environ.get(identity.ENV_HOME):  # only an explicit override travels
        env[identity.ENV_HOME] = os.environ[identity.ENV_HOME]
    return plistlib.dumps({
        "Label": identity.LAUNCHD_PREFIX + task.name,
        "ProgramArguments": ["/bin/zsh", "-lic", f"exec {_sq(identity.ENTRY)} _exec {_sq(task.name)}"],
        "EnvironmentVariables": env,
        "StartCalendarInterval": cron.calendar_intervals(task.cron, CAP),
        "StandardOutPath": str(io_log(task.name)),
        "StandardErrorPath": str(io_log(task.name)),
    }, sort_keys=False)


def launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def domain():
    return f"gui/{os.getuid()}"


def loaded(lbl):
    return launchctl("print", f"{domain()}/{lbl}").returncode == 0


def agent_pid(lbl):
    r = launchctl("print", f"{domain()}/{lbl}")
    m = re.search(r"^\s*pid = (\d+)$", r.stdout, re.M) if r.returncode == 0 else None
    return int(m.group(1)) if m else None


def bootout(lbl):
    launchctl("bootout", f"{domain()}/{lbl}")  # rc ignored: may not be loaded


def bootstrap(path, lbl):
    r = launchctl("bootstrap", domain(), str(path))
    if r.returncode:
        raise Conflict(f"launchctl bootstrap failed for {lbl}: {(r.stderr or r.stdout).strip()}")


def registered(task_name):
    return plist_path(task_name).exists()


def registered_names():
    d, pre = agents_dir(), identity.LAUNCHD_PREFIX
    if not d.is_dir():
        return []
    return sorted(p.name[len(pre):-len(".plist")] for p in d.glob(f"{pre}*.plist"))


def state(task):
    p = plist_path(task.name)
    if not task.enabled:
        return "stale" if p.exists() else "off"
    if not p.exists():
        return "missing"
    if p.read_bytes() != plist_bytes(task):
        return "stale"
    return "ok" if loaded(identity.LAUNCHD_PREFIX + task.name) else "unloaded"


def states(tasks):
    return {t.name: state(t) for t in tasks}


# ---------- TCC ----------

def tcc_root(path):
    """The protected folder `path` is in (both sides resolved: iCloud Drive turns
    ~/Documents into a symlink), else None."""
    if not path:
        return None
    try:
        target = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    for folder in TCC_DIRS:
        root = identity.home() / folder
        try:
            real = root.resolve()
        except OSError:
            real = root
        if target == real or real in target.parents:
            return root
    return None


def command_path(command):
    head = command.split()[0] if command.strip() else ""
    return head if head[:1] in ("/", "~") or head[:2] == "./" else ""


def tcc_warnings(tasks):
    out = []
    for t in tasks:
        for what, path in (("workdir", t.workdir), ("command path", command_path(t.command))):
            root = tcc_root(path)
            if root:
                out.append(f"! {t.name}: {what} is under ~/{root.name} — macOS privacy (TCC) can block a "
                           f"scheduled run there; see references/launchd.md")
                break
    return out


# ---------- sync ----------

def sync(tasks):
    for d in (identity.tasks_dir(), identity.runs_dir(), identity.data_dir() / "launchd-io", agents_dir()):
        d.mkdir(parents=True, exist_ok=True)
    desired = {t.name: t for t in tasks if t.enabled}
    lines, unchanged = [], 0
    for n, t in sorted(desired.items()):
        body, p, lbl = plist_bytes(t), plist_path(n), identity.LAUNCHD_PREFIX + n
        if not p.exists() or p.read_bytes() != body:
            bootout(lbl)
            p.write_bytes(body)
            bootstrap(p, lbl)
            k = len(cron.calendar_intervals(t.cron, CAP))
            lines.append(f"~ {n}: scheduled '{t.schedule}' ({cron.describe(t.cron)}; {k} interval{'s' if k != 1 else ''})")
        elif not loaded(lbl):
            bootstrap(p, lbl)
            lines.append(f"+ {n}: loaded")
        else:
            unchanged += 1
    for n in registered_names():
        if n not in desired:
            unregister(n)
            lines.append(f"- {n}: removed from launchd")
    lines.append(f"sync done: {len(desired)} scheduled, {len(lines)} changed, {unchanged} unchanged")
    return lines + tcc_warnings(tasks)


def unregister(task_name):
    bootout(identity.LAUNCHD_PREFIX + task_name)
    try:
        plist_path(task_name).unlink()
    except FileNotFoundError:
        pass


def notes():
    return []


def exec_guard(task, now):
    return True


# ---------- UI autostart: com.claude.clockmaster-ui ----------

def ui_plist_path():
    return agents_dir() / f"{identity.LAUNCHD_UI}.plist"


def ui_plist_bytes(port):
    plist = {
        "Label": identity.LAUNCHD_UI,
        # `ui --fg` execs the server in this pid, so launchd's pid IS the listener
        "ProgramArguments": [sys.executable, str(identity.ENTRY), "ui", "--fg",
                             *(["--port", str(port)] if port != identity.UI_PORT else [])],
        "RunAtLoad": True, "KeepAlive": True,
        "WorkingDirectory": str(identity.home()),
        "StandardOutPath": str(identity.data_dir() / "ui.log"),
        "StandardErrorPath": str(identity.data_dir() / "ui.log"),
    }
    if os.environ.get(identity.ENV_HOME):
        plist["EnvironmentVariables"] = {identity.ENV_HOME: os.environ[identity.ENV_HOME]}
    return plistlib.dumps(plist, sort_keys=False)


def ui_plist_port():
    try:
        args = plistlib.loads(ui_plist_path().read_bytes()).get("ProgramArguments", [])
        return int(args[args.index("--port") + 1]) if "--port" in args else identity.UI_PORT
    except (OSError, ValueError, IndexError):
        return identity.UI_PORT


def ui_autostart_state():
    if not ui_plist_path().exists():
        return None
    pid = agent_pid(identity.LAUNCHD_UI)
    detail = (f"loaded, pid {pid}" if pid else "loaded, not running" if loaded(identity.LAUNCHD_UI)
              else f"booted out — start it with: {identity.APP} ui")
    return {"port": ui_plist_port(), "pid": pid, "detail": f"{identity.LAUNCHD_UI}: {detail}"}


def ui_autostart_on(port):
    agents_dir().mkdir(parents=True, exist_ok=True)
    identity.data_dir().mkdir(parents=True, exist_ok=True)
    ui_plist_path().write_bytes(ui_plist_bytes(port))
    bootout(identity.LAUNCHD_UI)  # bootstrap over a loaded label fails with an I/O error
    bootstrap(ui_plist_path(), identity.LAUNCHD_UI)


def ui_autostart_off():
    bootout(identity.LAUNCHD_UI)
    try:
        ui_plist_path().unlink()
    except FileNotFoundError:
        pass


def ui_autostart_restart(port):
    if loaded(identity.LAUNCHD_UI):
        r = launchctl("kickstart", "-k", f"{domain()}/{identity.LAUNCHD_UI}")
        if r.returncode:
            raise Conflict(f"launchctl kickstart failed: {(r.stderr or r.stdout).strip()}")
    else:  # plist kept but booted out — what `ui --stop` leaves behind
        bootstrap(ui_plist_path(), identity.LAUNCHD_UI)


def ui_autostart_stop():
    bootout(identity.LAUNCHD_UI)  # a plain kill would be undone by KeepAlive
    time.sleep(0.2)


def ui_autostart_hint():
    return f"{identity.LAUNCHD_UI}: starts at login, restarts if it dies"
