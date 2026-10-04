"""Finished-run notifications. Pluggable: every module in CHANNELS exposes
`send(msg) -> None` and decides for itself whether it is configured. The task's
gate (`notify: off | on | failure`) is applied ONCE, here, for all channels.

Best effort by contract: the run is already recorded; nothing here may change
its outcome. Failures that leave no other trace go to <data>/notify.log.

Adding a channel: write notify/<name>.py with send(msg), add
the name to CHANNELS. Config lives in <data>/notify.yaml (flat `key: value`).
"""
import importlib
import sys
from datetime import datetime

import identity
import store
import taskdef

LABELS = {"success": "✅ success", "failed": "❌ failed", "timeout": "⏱️ timeout",
          "killed": "💀 killed", "stopped": "⏹️ stopped"}
LOG_MAX = 256_000
CHANNELS = ("desktop", "teams", "telegram")
EXTRA_KEYS = ("telegram", "telegram_topic", "claude_tg")  # notify.yaml keys teams.py must not flag


class Message:
    """What every channel gets."""

    def __init__(self, task, meta, log_path):
        self.task, self.meta, self.log_path = task, meta, log_path
        self.status = meta.get("status", "?")
        self.duration = meta.get("durationSec") or 0
        self.run_id = meta.get("runId")
        self.title = task.name
        self.body = f"{LABELS.get(self.status, self.status)} in {store.fmt_dur(self.duration)}"
        self.sound = task.sound  # "off" or a validated sound name


def wanted(mode, status):
    return mode == "on" or (mode == "failure" and status != "success")


def log_path():
    return identity.data_dir() / "notify.log"


def config_path():
    return identity.data_dir() / "notify.yaml"


def note(line):
    """One stamped line in notify.log; truncated in place past LOG_MAX."""
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_MAX:
            path.write_bytes(b"")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {line}\n")
    except OSError:
        pass


def config():
    """notify.yaml as a dict ({} when absent or broken — logged, never raised)."""
    path = config_path()
    if not path.exists():
        return {}
    try:
        return taskdef.parse_flat(path.read_text(encoding="utf-8"), path.name)
    except Exception as e:  # a typo here may not cost a banner
        note(f"{path.name}: unreadable ({e}); channels that need it are skipped")
        return {}


def desktop_module():
    name = {"darwin": "desktop_mac", "win32": "desktop_win"}.get(sys.platform, "desktop_linux")
    return importlib.import_module(f"notify.{name}")


def channel(name):
    return desktop_module() if name == "desktop" else importlib.import_module(f"notify.{name}")


def dispatch(task, meta, log_file=None):
    if not wanted(task.notify, meta.get("status")):
        return
    msg = Message(task, meta, log_file)
    for name in CHANNELS:  # desktop first: a slow network channel may not delay it
        try:
            channel(name).send(msg)
        except Exception as e:
            note(f"{task.name} {msg.run_id}: {name} channel crashed ({type(e).__name__}: {e})")


def channels():
    """Plain names of the channels a finished run reaches right now (shown in the UI)."""
    cfg = config()
    out = []
    try:
        mod = desktop_module()
        if sys.platform in ("darwin", "win32") or mod.display_env():
            out.append("Desktop")
    except Exception:
        pass
    for name, label in (("teams", "Teams"), ("telegram", "Telegram")):
        try:
            if importlib.import_module(f"notify.{name}").settings(cfg):
                out.append(label)
        except Exception:
            pass
    return out
