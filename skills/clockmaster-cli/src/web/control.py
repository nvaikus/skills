"""`ui` command: start the server detached, stop it, the autostart service
(launchd agent on macOS, clockmaster-ui.service on Linux), and tailnet sharing
(web/tailnet.py).

While autostart is on, start/stop go through the service manager: a plain kill
would be undone by KeepAlive/Restart=always, and a second detached instance
would fight it over the port forever.
"""
import os
import signal
import subprocess
import sys
import time

import backends
import identity
import procs
from errors import Conflict, ValidationError
from web import server

LOG_MAX = 1_000_000


def log_path():
    """ui.log, truncated in place past LOG_MAX (never unlinked: a service manager
    may hold the fd, and an unlink would send later lines into a dead inode)."""
    p = identity.data_dir() / "ui.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        if p.exists() and p.stat().st_size > LOG_MAX:
            p.write_bytes(b"")
    except OSError:
        pass
    return p


def ours(port):
    out = []
    for pid, cmd in procs.listeners(port):
        if not server.is_ours(cmd):
            raise Conflict(f"port {port} is held by pid {pid} ({cmd or '?'}) — not a {identity.APP} UI")
        out.append(pid)
    return out


def kill(pids):
    for pid in pids:
        if procs.IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


def wait_gone(port, secs=5):
    deadline = time.time() + secs
    while time.time() < deadline and procs.listeners(port):
        time.sleep(0.2)
    return not procs.listeners(port)


def wait_pid(port, want_pid=None, secs=15, proc=None):
    deadline = time.time() + secs
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            raise Conflict(f"UI failed to start (exit {proc.returncode}) — log: {log_path()}")
        pids = [p for p, _ in procs.listeners(port)]
        if want_pid is None and pids:
            return pids[0]
        if callable(want_pid):
            w = want_pid()
            if w and w in pids:
                return w
        elif want_pid in pids:
            return want_pid
        time.sleep(0.3)
    return None


def started(port, pid, extra):
    return [f"{identity.TITLE} UI -> http://127.0.0.1:{port}   (pid {pid}, log: {log_path()})", extra]


def start_detached(port):
    log = log_path()
    with open(log, "ab") as fh:
        proc = subprocess.Popen(server.argv_for(port), stdout=fh, stderr=fh, stdin=subprocess.DEVNULL,
                                **procs.DETACH_SERVER)
    pid = wait_pid(port, proc.pid, proc=proc)  # evicting a previous instance takes up to ~5 s
    if not pid:
        raise Conflict(f"UI did not come up in 15s — log: {log}")
    return started(port, pid, f"stop: {identity.APP} ui --stop")


def _agent_pid(be):
    def get():
        st = be.ui_autostart_state()
        return st and st.get("pid")
    return get


def restart_service(be, st, port):
    if port != st["port"]:
        raise ValidationError(f"autostart serves port {st['port']} — move it with "
                              f"`{identity.APP} ui --autostart on --port {port}`")
    log_path()
    be.ui_autostart_restart(port)
    pid = wait_pid(port, _agent_pid(be))
    if not pid:
        raise Conflict(f"UI service did not come up in 15s — log: {log_path()}")
    return started(port, pid, f"autostart: on   stop: {identity.APP} ui --stop")


def stop(be, port):
    st = be.ui_autostart_state()
    if st:
        be.ui_autostart_stop()
    pids = ours(port)
    kill(pids)
    if st:
        wait_gone(port)
        return ["stopped the UI (service stopped)", f"autostart stays on — `{identity.APP} ui` brings it back"]
    if pids:
        return [f"stopped UI (pid {p})" for p in pids]
    return [f"UI not running on port {port}"]


def autostart(be, value, port):
    if procs.IS_WIN:
        raise ValidationError("ui --autostart is not available on Windows yet")
    st = be.ui_autostart_state()
    if value is None:
        out = [f"autostart: on    ({st['detail']}, port {st['port']})" if st
               else f"autostart: off   (enable: {identity.APP} ui --autostart on)"]
        live = [p for p, c in procs.listeners(port) if server.is_ours(c)]
        out.append(f"UI: http://127.0.0.1:{port} (pid {live[0]})" if live else f"UI: nothing listening on port {port}")
        return out + tailnet_line(port)
    if value == "on":
        kill(ours(port))  # a detached instance would fight the service
        wait_gone(port)
        log_path()
        be.ui_autostart_on(port)
        pid = wait_pid(port, _agent_pid(be))
        if not pid:
            raise Conflict(f"UI service did not come up in 15s — log: {log_path()}")
        return started(port, pid, f"autostart: on    ({be.ui_autostart_hint()})")
    if value == "off":
        if not st:
            return ["autostart: off   (already)"]
        was_up = bool([p for p, c in procs.listeners(port) if server.is_ours(c)])
        be.ui_autostart_off()
        wait_gone(port)
        out = ["autostart: off   (service unloaded and removed)"]
        if was_up:
            out.append("restarting the UI detached — it stays up for this session only")
            out += start_detached(port)
        return out
    raise ValidationError(f"unknown --autostart value '{value}' — use on | off (or nothing for the state)")


def tailnet_line(port):
    from web import tailnet
    return tailnet.state_line(port)


def _opt_value(args, flag):
    tail = args[args.index(flag) + 1:]
    return tail[0] if tail and not tail[0].startswith("-") else None


def _int(value, what):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{what} needs a number, got '{value}'")


def run(args):
    """`ui [--port N] [--fg | --stop | --autostart [on|off] | --share [HTTPS_PORT | --service [NAME]]
    [--allow LOGIN] | --unshare [HTTPS_PORT | --service [NAME]]]` -> lines (or never returns for --fg)."""
    port = identity.UI_PORT
    if "--port" in args:
        try:
            port = int(args[args.index("--port") + 1])
        except (IndexError, ValueError):
            raise ValidationError("--port needs a number")
    be = backends.current()
    if "--fg" in args:
        argv = server.argv_for(port)
        if procs.IS_WIN:  # execv on Windows returns the shell before the server is up
            sys.exit(subprocess.call(argv))
        os.execv(sys.executable, argv)
    if "--share" in args or "--unshare" in args:
        from web import tailnet
        service = (_opt_value(args, "--service") or "") if "--service" in args else None
        if "--unshare" in args:
            v = _opt_value(args, "--unshare")
            return tailnet.unshare(port, v and _int(v, "--unshare"), service)
        if "--allow" in args and not _opt_value(args, "--allow"):
            raise ValidationError("--allow needs a tailscale login")
        v = _opt_value(args, "--share")
        return tailnet.share(port, _int(v, "--share") if v else None,
                             "--allow" in args and _opt_value(args, "--allow") or None, service)
    if "--autostart" in args:
        return autostart(be, _opt_value(args, "--autostart"), port)
    if "--stop" in args:
        return stop(be, port)
    st = None if procs.IS_WIN else be.ui_autostart_state()
    return (restart_service(be, st, port) if st else start_detached(port)) + tailnet_line(port)
