"""Per-profile config: ~/.claude/icloud-calendar/<profile>/config.json. Never holds the password:
only the NAME of the env var (or a command) that yields it."""
import copy
import json

from . import paths, profile
from .errors import UsageError

# Keys are contract: users' configs depend on them. Never rename.
DEFAULTS = {
    "apple_id": None,                       # Apple ID email; env[apple_id_env] wins when set
    "apple_id_env": "ICLOUD_APPLE_ID",
    "password_env": "ICLOUD_APP_PASSWORD",  # env var holding the app-specific password
    "password_cmd": None,                   # optional command printing the password (keychain, pass, secret-tool)
    "principal": None,                      # discovered: principal URL
    "home": None,                           # discovered: calendar-home-set URL (pNN-caldav host)
    "notifications": None,                  # discovered: notification collection URL (share invitations)
    "user_addresses": [],                   # discovered: calendar-user-address-set (mailto:...)
    "default_calendar": None,               # calendar id used by `add` without --cal
    "tz": None,
    "default_alarms": [],                   # `add` without --alarm, timed events: e.g. ["1d", "1h"]
    "default_alarms_today": None,           # same, for events starting today; None = default_alarms                             # IANA zone for input/output; None = this machine's zone
}


def path(name=None):
    return profile.dir(name) / "config.json"


def load(name=None):
    cfg = copy.deepcopy(DEFAULTS)
    name = name or profile.active()
    if name:
        p = profile.dir_peek(name) / "config.json"
        if p.exists():
            try:
                cfg.update(json.loads(p.read_text(encoding="utf-8-sig")))
            except ValueError as e:
                raise UsageError(f"{p}: invalid JSON: {e}") from None
    return cfg


def update(name=None, **changes):
    p = path(name)
    on_disk = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    on_disk.update(changes)
    paths.write_private(p, json.dumps(on_disk, indent=1, ensure_ascii=False) + "\n")
    return load(name)
