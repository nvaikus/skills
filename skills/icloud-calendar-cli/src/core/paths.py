"""Where icloud-calendar keeps things. ICAL_ROOT overrides (tests, relocation); read at call time.

~/.claude/icloud-calendar/            user-local, never touched by skill updates
  config.json                    {default_profile}
  memory.md                      skill memory
  <profile>/config.json          apple id, env var names, discovered urls, default calendar (no secrets)"""
import os
from pathlib import Path


def root():
    p = root_peek()
    p.mkdir(parents=True, exist_ok=True)
    return p


def root_peek():
    return Path(os.environ.get("ICAL_ROOT") or "~/.claude/icloud-calendar").expanduser()


def sub(base, *parts):
    p = base.joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_private(path, text):
    """Atomic write, chmod 600."""
    path = Path(path)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
