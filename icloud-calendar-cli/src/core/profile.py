"""Profiles: one Apple ID = one dir under ~/.claude/icloud-calendar. main resolves once per run.

need (a command's PROFILE):
  required  one profile: --profile > ICAL_PROFILE > default_profile > the only one
  create    onboard: --profile may name a new one (none given and none exist -> `main`)
  none      may run without any profile"""
import json
import os
import re

from . import paths
from .errors import UsageError

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
FIRST = "main"

_active = {"name": None, "explicit": False}


def root_config():
    p = paths.root_peek() / "config.json"
    cfg = {"default_profile": None}
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
        raise UsageError(f"bad profile name {name!r}: lowercase letters, digits, - and _ (max 32), e.g. main, work")
    return name


def default():
    have = names()
    d = root_config().get("default_profile")
    if d in have:
        return d
    return have[0] if len(have) == 1 else None


def resolve(requested, need):
    explicit = requested or os.environ.get("ICAL_PROFILE")
    have = names()
    if explicit:
        check_name(explicit)
        if need != "create" and explicit not in have:
            raise UsageError(f"no profile {explicit!r}" + (f"; profiles: {', '.join(have)}" if have else "")
                             + f" - set one up with `icloud-calendar onboard --profile {explicit}`")
        return _use(explicit, True)
    if need == "create":
        if not have:
            return _use(FIRST, False)
        d = default()
        if d:
            return _use(d, False)
        raise UsageError(f"onboard needs --profile NAME (existing: {', '.join(have)}, or a new one)")
    if not have:
        if need == "none":
            return _use(None, False)
        raise UsageError("no icloud-calendar profile yet: run `icloud-calendar onboard`")
    d = default()
    if d or need == "none":
        return _use(d, False)
    raise UsageError(f"{len(have)} profiles and no default: pass --profile NAME "
                     f"(one of {', '.join(have)}) or `icloud-calendar profiles --default NAME`")


def _use(name, explicit):
    _active.update(name=name, explicit=explicit)
    return name


def active():
    return _active["name"]


def dir_peek(name):
    return paths.root_peek() / name


def dir(name=None):  # noqa: A001 - reads as profile.dir()
    name = name or _active["name"]
    if not name:
        raise UsageError("no icloud-calendar profile selected: run `icloud-calendar onboard` first")
    p = paths.sub(paths.root(), name)
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass
    return p
