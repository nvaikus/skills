"""Where gdrive keeps things. Env overrides exist for tests and relocation; read at call time.

~/.claude/gdrive/                user-local, never touched by skill updates
  config.json                    {default_profile}
  memory.md                      skill memory
  <profile>/config.json          client, project, mount choice (chmod 600: holds the client secret)
  <profile>/rclone.conf          the OAuth token (chmod 600)
  <profile>/index/, index.sqlite text mirror + manifest
~/.cache/gdrive/<profile>/<id>   rclone VFS cache per mount (disposable once uploaded)
~/.local/share/gdrive/           bin/ (rclone), mounts/ (records), logs/ - shared by all profiles"""
import os
from pathlib import Path


def _dir(env, default, mode=None):
    p = Path(os.environ.get(env) or default).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    if mode is not None:
        try:
            os.chmod(p, mode)
        except OSError:
            pass
    return p


def root():
    """~/.claude/gdrive: profiles, root config, memory."""
    return _dir("GDRIVE_ROOT", "~/.claude/gdrive")


def root_peek():
    """root() without creating it (read-only callers: listing profiles)."""
    return Path(os.environ.get("GDRIVE_ROOT") or "~/.claude/gdrive").expanduser()


def data():
    """bin/ (rclone), mounts/ (state records), logs/."""
    return _dir("GDRIVE_HOME", "~/.local/share/gdrive")


def cache_root():
    """VFS caches: <profile>/<mount id> (a remount resumes queued uploads from it)."""
    return _dir("GDRIVE_CACHE_DIR", "~/.cache/gdrive")


def legacy_config():
    """v0.1 single-account files, imported once by `onboard` (never written)."""
    return Path("~/.gdrive.json").expanduser()


def legacy_rclone_conf():
    return Path(os.environ.get("GDRIVE_CONF_DIR") or "~/.config/gdrive").expanduser() / "rclone.conf"


def sub(base, *parts):
    p = base.joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_private(path, text):
    """Atomic write, chmod 600 (tokens, secrets, rc passwords): a half-written file is impossible."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
