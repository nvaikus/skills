"""Process helpers per OS: command lines, liveness, boot time, killing a
detached group, the shell a task runs in, and who listens on a port.

Every platform-specific import stays inside its branch — the module must
import on macOS, Linux and Windows alike.
"""
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# Detach a task's shell into its own POSIX session / Windows process group, so a
# timeout or `stop` can end the whole tree. CREATE_NO_WINDOW: no console flash
# under pythonw.
if IS_WIN:
    DETACH = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    DETACH_SERVER = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
else:
    DETACH = DETACH_SERVER = {"start_new_session": True}


def _run(argv, timeout=30):
    return subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout)


def ps_win(script):
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])


# ---------- identity of a pid ----------

def cmdline(pid):
    """Full command line of a pid as one space-joined string, None when gone."""
    try:
        if IS_WIN:
            out = ps_win(f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine").stdout
        elif Path("/proc").is_dir():
            out = Path(f"/proc/{int(pid)}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        else:
            out = _run(["ps", "-p", str(int(pid)), "-o", "command="]).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return " ".join(out.split()) or None


def alive(pid):
    if IS_WIN:
        return cmdline(pid) is not None
    try:  # our own exited child (the UI starts runners) stays a zombie until reaped
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    except (ChildProcessError, OSError):
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # exists, just not ours to signal
    return not _zombie(pid)


def _zombie(pid):
    """Exited, waiting for a parent to reap it: signal 0 still succeeds. Without
    this check a stop waits out the whole TERM/KILL grace on a corpse."""
    try:
        if Path("/proc").is_dir():
            stat = Path(f"/proc/{int(pid)}/stat").read_text()
            return stat[stat.rindex(")") + 2:][:1] == "Z"
        return _run(["ps", "-p", str(int(pid)), "-o", "stat="]).stdout.strip().startswith("Z")
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


_BOOT = []


def boot_time():
    """Last boot as an aware datetime, None when unknown. Cached per process.
    Windows uses CIM LastBootUpTime, NOT GetTickCount64 (which excludes sleep and
    would put "boot" after live runs)."""
    if _BOOT:
        return _BOOT[0]
    stamp = None
    try:
        if IS_WIN:
            text = ps_win("(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime()"
                          ".ToString('yyyyMMddHHmmss',[cultureinfo]::InvariantCulture)").stdout.strip()
            if text:
                stamp = datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).astimezone()
        elif IS_MAC:
            m = re.search(r"sec\s*=\s*(\d+)", _run(["sysctl", "-n", "kern.boottime"]).stdout)
            if m:
                stamp = datetime.fromtimestamp(int(m.group(1))).astimezone()
        else:
            m = re.search(r"^btime (\d+)$", Path("/proc/stat").read_text(), re.M)
            if m:
                stamp = datetime.fromtimestamp(int(m.group(1))).astimezone()
    except (OSError, ValueError, subprocess.SubprocessError):
        stamp = None
    _BOOT.append(stamp)
    return stamp


# ---------- killing ----------

def waiter(pid):
    """Popen.wait-shaped poll for a pid that is not our child."""
    def wait(timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not alive(pid):
                return
            time.sleep(0.1)
        if alive(pid):
            raise subprocess.TimeoutExpired(str(pid), timeout)
    return wait


def kill_group(pgid, wait=None, grace=(10, 5)):
    """TERM, then KILL, a detached run's whole group (POSIX) / tree (Windows)."""
    wait = wait or waiter(pgid)
    if IS_WIN:
        # taskkill /T walks the tree from a LIVE parent: never kill the shell alone.
        for force, secs in ((False, grace[0]), (True, grace[1])):
            argv = ["taskkill", "/PID", str(pgid), "/T"] + (["/F"] if force else [])
            if subprocess.run(argv, capture_output=True).returncode and not force:
                continue  # graceful pass reaches windowed processes only
            try:
                wait(secs)
                return
            except subprocess.TimeoutExpired:
                continue
        return
    for sig, secs in ((signal.SIGTERM, grace[0]), (signal.SIGKILL, grace[1])):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            wait(secs)
            return
        except subprocess.TimeoutExpired:
            continue


def kill_one(pid, wait=None):
    """TERM, then KILL, one process (a runner) — never its group."""
    if IS_WIN:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        return
    wait = wait or waiter(pid)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            wait(5)
            return
        except subprocess.TimeoutExpired:
            continue


# ---------- the task shell ----------

def login_shell():
    """The user's login shell from the password database (POSIX)."""
    if IS_MAC:
        return "/bin/zsh"
    try:
        import pwd
        shell = pwd.getpwuid(os.getuid()).pw_shell
    except (ImportError, KeyError, OSError):
        shell = ""
    return shell if shell and os.access(shell, os.X_OK) else "/bin/sh"


def shell_spawn(command, log_fd):
    """(argv_or_string, extra Popen kwargs, stderr_to_devnull) for a task command.
    `log_fd` is the open output.log descriptor in this process.

    macOS: `zsh -lic` — login + interactive, so .zprofile AND .zshrc load.
    Linux: the passwd shell. bash and zsh run `-lic` too, because Debian-style
    .bashrc returns early unless interactive (API keys exported there would be
    missing). Interactive without a tty makes bash print two "no job control"
    lines at startup, so the shell starts with stderr on /dev/null and the
    command's first act is `exec 2>&<log_fd>` — the log. The command runs in a
    subshell so its own `exit` does not trigger bash's "logout" line. Only shell
    start-up chatter is lost. Other shells get plain `-lc`.
    Windows: `cmd /d /s /c "<cmd>"` as a STRING — a list goes through
    list2cmdline, whose \\" escaping cmd.exe does not understand.
    """
    if IS_WIN:
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return f'"{comspec}" /d /s /c "{command}"', {}, False
    if IS_MAC:
        return ["/bin/zsh", "-lic", command], {}, False
    shell = login_shell()
    if Path(shell).name == "zsh":
        return [shell, "-lic", command], {}, False
    if Path(shell).name == "bash":
        # subshell: an `exit` inside the command would make the interactive
        # login shell print "logout" into the log; the outer exit is muted.
        script = (f"exec 2>&{log_fd} {log_fd}>&-; (\n{command}\n); "
                  f"__cm_rc=$?; exec 2>/dev/null; exit $__cm_rc")
        return [shell, "-lic", script], {"pass_fds": (log_fd,)}, True
    return [shell, "-lc", command], {}, False


# ---------- port listeners ----------

def _linux_listeners(port):
    inodes = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            rows = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            f = row.split()
            if len(f) > 9 and f[3] == "0A" and int(f[1].rsplit(":", 1)[1], 16) == port:
                inodes.add(f[9])
    if not inodes:
        return []
    found = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            for fd in (proc / "fd").iterdir():
                link = os.readlink(fd)
                if link.startswith("socket:[") and link[8:-1] in inodes:
                    found.append(int(proc.name))
                    break
        except OSError:
            continue
    return found


def listeners(port):
    """[(pid, cmdline)] of processes listening on a TCP port."""
    if IS_WIN:
        pids = set()
        for line in _run(["netstat", "-ano", "-p", "tcp"]).stdout.splitlines():
            f = line.split()
            # match addresses, never the localized state word
            if len(f) >= 5 and f[0].upper() == "TCP" and f[-1].isdigit() \
                    and f[1].endswith(f":{port}") and f[2].endswith(":0"):
                pids.add(int(f[-1]))
    elif IS_MAC:
        pids = {int(p) for p in _run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"]).stdout.split()}
    else:
        pids = set(_linux_listeners(port))
    return [(pid, cmdline(pid) or "") for pid in sorted(pids)]
