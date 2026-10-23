"""Where olx keeps things. OLX_ROOT overrides (tests, relocation); read at call time.

~/.claude/olx/               user-local, never touched by skill updates
  config.json                site, notify_topic
  health.tsv                 one line per OLX request outcome (ok / blocked / schema / http / network)
  cache/categories-<site>.json   category tree, refreshed weekly
  watch/searches.json        saved searches
  watch/seen/<name>.json     listings a saved search has already reported
  watch/alerted.json         last failure alert per watch (notify rate limit)
  memory.md                  skill memory"""
import os
from pathlib import Path


def root_peek():
    return Path(os.environ.get("OLX_ROOT") or "~/.claude/olx").expanduser()


def root():
    p = root_peek()
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_private(path, text):
    """Atomic write, chmod 600: a half-written file is impossible."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
