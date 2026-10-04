"""Which Provider indexes a profile. v1: Google Drive only; the scope is the profile's mount."""
from ..core import profile
from ..core.errors import UsageError

DEFAULT_SECTIONS = ["my-drive"]


def scope(cfg):
    what = (cfg.get("mount") or {}).get("what")
    if not what:
        raise UsageError("this profile has not chosen what to mount yet (the index mirrors it): run `gdrive onboard`")
    return what


def sections(cfg):
    """Index sections of a what=/ profile: my-drive always, the others only when included."""
    got = cfg.get("index_sections") or DEFAULT_SECTIONS
    return ["my-drive"] + [s for s in got if s != "my-drive"]


def new_layout(name=None):
    """The index mirrors the mount: a what=/ mount made before the three-folder layout keeps the
    old index layout until it is remounted (`gdrive mount` upgrades it)."""
    from . import mounts
    name = name or profile.active()
    return not any(r.get("profile") == name and mounts.old_layout(r) for r in mounts.records())


def for_profile(cfg):
    from .gprovider import GoogleDrive
    return GoogleDrive(cfg["remote"], scope(cfg), sections(cfg), new_layout())
