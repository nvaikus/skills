"""Background processes that outlive this CLI run (cross-platform). No domain nouns."""
import os
import signal
import subprocess
import sys

# Runs a command and records its exit code in a file, so a later CLI run can learn how a
# detached job ended (the spawning run is long gone by then).
_RUNNER = ("import subprocess,sys,os\n"
           "rc=subprocess.call(sys.argv[2:])\n"
           "t=sys.argv[1]+'.tmp'\n"
           "open(t,'w').write(str(rc))\n"
           "os.replace(t,sys.argv[1])\n")


def spawn(argv, log_path, env=None, status_path=None):
    """Start argv detached from this process group; stdout+stderr -> log_path. -> pid.
    status_path: the exit code is written there when the command ends."""
    if status_path:
        argv = [sys.executable, "-c", _RUNNER, str(status_path), *argv]
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                               | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        kw["start_new_session"] = True  # survives the terminal / agent shell going away
    log = open(log_path, "ab")
    try:
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             env={**os.environ, **(env or {})}, close_fds=True, **kw)
    finally:
        log.close()
    return p.pid


def alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # a zombie child of this very process still answers kill 0
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True


def terminate(pid):
    if not alive(pid):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def tail(path, lines=8):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 8192))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    return [line for line in text.splitlines() if line.strip()][-lines:]
