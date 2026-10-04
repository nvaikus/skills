"""The active profile: one Google account (or Shared drive) = one dir under ~/.claude/gdrive.
main resolves it once; api/ modules read it through dir(). A local path inside another
profile's mount may switch it (api/address) - the mount record knows its account."""
import json
import re

from . import paths
from .errors import UsageError

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
ROOT_KEYS = {"default_profile": None}

_active = {"name": None, "explicit": False}


def root_config():
    p = paths.root_peek() / "config.json"
    cfg = dict(ROOT_KEYS)
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8-sig")))
        except ValueError as e:
            raise UsageError(f"{p}: invalid JSON: {e}") from None
    return cfg


def set_default(name):
    cfg = root_config()
    cfg["default_profile"] = name
    paths.write_private(paths.root() / "config.json", json.dumps(cfg, indent=1) + "\n")


def names():
    base = paths.root_peek()
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and (p / "config.json").exists())


def check_name(name):
    if not NAME.match(name or ""):
        raise UsageError(f"bad profile name {name!r}: lowercase letters, digits, - and _ (max 32), e.g. work, njdesign")
    return name


def resolve(requested, need):
    """need: 'required' (an existing profile) | 'create' (onboard: may be new) | 'none'.
    Order: --profile > GDRIVE_PROFILE > root config default_profile > the only profile."""
    import os
    explicit = requested or os.environ.get("GDRIVE_PROFILE")
    have = names()
    if explicit:
        check_name(explicit)
        if need == "required" and explicit not in have:
            raise UsageError(f"no profile {explicit!r}" + (f"; profiles: {', '.join(have)}" if have else "")
                             + f" - set one up with `gdrive onboard --profile {explicit}`")
        return _use(explicit, True)
    if need == "none" and not have:
        return _use(None, False)
    default = root_config().get("default_profile")
    if default in have:
        return _use(default, False)
    if len(have) == 1:
        return _use(have[0], False)
    if not have:
        if need == "none":
            return _use(None, False)
        raise UsageError("no gdrive profile yet: run `gdrive onboard --profile NAME` "
                         "(NAME = a short label for this Google account, e.g. work, njdesign)")
    if need == "none":
        return _use(None, False)
    raise UsageError(f"{len(have)} profiles and no default: pass --profile NAME "
                     f"(one of {', '.join(have)}) or `gdrive profiles --default NAME`")


def _use(name, explicit):
    _active.update(name=name, explicit=explicit)
    return name


def active():
    return _active["name"]


def explicit():
    return _active["explicit"]


def switch(name):
    """Follow a local path into another profile's mount (not when --profile was given)."""
    if name == _active["name"]:
        return False
    if _active["explicit"]:
        raise UsageError(f"that path is in a mount of profile {name!r}, but --profile {_active['name']} was given")
    _active.update(name=name)
    return True


def dir(name=None):  # noqa: A001 - reads as profile.dir()
    name = name or _active["name"]
    if not name:
        raise UsageError("no gdrive profile selected: run `gdrive onboard --profile NAME` first")
    p = paths.sub(paths.root(), name)
    try:
        import os
        os.chmod(p, 0o700)
    except OSError:
        pass
    return p
