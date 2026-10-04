"""Where ebay keeps things. Env overrides exist for tests and relocation; read at call time.

~/.claude/ebay/            user-local, never touched by skill updates
  config.json              market, ship_to, zip, setup progress
  token.json               cached application token (chmod 600)
  credentials.json         App ID + Cert ID where no env / Keychain (chmod 600)
  watch/searches.json      saved searches
  watch/seen/<name>.json   items a saved search has already reported
  memory.md                skill memory"""
import os
from pathlib import Path


def root_peek():
    return Path(os.environ.get("EBAY_ROOT") or "~/.claude/ebay").expanduser()


def root():
    p = root_peek()
    p.mkdir(parents=True, exist_ok=True)
    return p


def sub(*parts):
    p = root().joinpath(*parts)
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
