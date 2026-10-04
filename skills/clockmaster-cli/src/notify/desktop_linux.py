"""Linux desktop banner via notify-send — only where a graphical session exists.

A timer-started run has no DISPLAY of its own; the user manager may still know
one (`systemctl --user show-environment`, filled by the desktop session). No
display anywhere = a headless host: no-op plus one notify.log line, so a
missing banner is explainable.
"""
import os
import shutil
import subprocess

import identity
import notify

KEYS = ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR")
TIMEOUT = 10


def display_env():
    """{var: value} needed to reach the desktop, {} when there is none."""
    env = {k: os.environ[k] for k in KEYS if os.environ.get(k)}
    if not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        try:
            out = subprocess.run(["systemctl", "--user", "show-environment"],
                                 capture_output=True, text=True, timeout=TIMEOUT).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        for line in out.splitlines():
            k, _, v = line.partition("=")
            if k in KEYS and v and k not in env:
                env[k] = v
    return env if (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")) else {}


def argv(msg):
    out = ["notify-send", "--app-name", identity.TITLE]
    if msg.status != "success":
        out += ["--urgency", "critical"]
    return out + ["--", msg.title, msg.body]


def send(msg):
    env = display_env()
    if not env:
        notify.note(f"{msg.title} {msg.run_id}: no desktop session (no DISPLAY/WAYLAND_DISPLAY) — banner skipped")
        return
    if not shutil.which("notify-send"):
        notify.note(f"{msg.title} {msg.run_id}: notify-send not installed — banner skipped")
        return
    p = subprocess.run(argv(msg), env={**os.environ, **env}, capture_output=True, text=True, timeout=TIMEOUT)
    if p.returncode:
        notify.note(f"{msg.title} {msg.run_id}: notify-send exit {p.returncode}: {p.stderr.strip()[:200]}")
