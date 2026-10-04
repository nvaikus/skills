"""Where gmail keeps things. Env overrides exist for tests and relocation; read at call time.

~/.claude/gmail/                 user-local, never touched by skill updates
  config.json                    {default_profile}
  memory.md                      skill memory
  <profile>/config.json          OAuth client, project, account (chmod 600: holds the client secret)
  <profile>/token.json           the OAuth token (chmod 600)
~/.claude/gdrive/<profile>/config.json   read only: a gdrive profile's OAuth client is reused"""
import os
import tempfile
from pathlib import Path


def _dir(env, default):
    p = Path(os.environ.get(env) or default).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def root():
    """~/.claude/gmail: profiles, root config, memory."""
    return _dir("GMAIL_ROOT", "~/.claude/gmail")


def root_peek():
    """root() without creating it (read-only callers: listing profiles)."""
    return Path(os.environ.get("GMAIL_ROOT") or "~/.claude/gmail").expanduser()


def gdrive_root():
    """The google-drive-cli skill's profiles (their OAuth clients are reused, never written)."""
    return Path(os.environ.get("GDRIVE_ROOT") or "~/.claude/gdrive").expanduser()


def downloads():
    """Default target of `attachment get`: a temp dir, never the skill or the cwd."""
    return _dir("GMAIL_DOWNLOADS", Path(tempfile.gettempdir()) / "gmail")


def sub(base, *parts):
    p = base.joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_private(path, text):
    """Atomic write, chmod 600 (tokens, secrets): a half-written file is impossible."""
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
