"""Profiles: one Gmail account = one dir under ~/.claude/gmail. main resolves once per run.

need (a command's PROFILE):
  required  one profile: --profile > GMAIL_PROFILE > default_profile > the only one
  create    onboard: --profile may name a new one
  none      may run without any profile
  all       search: --profile/GMAIL_PROFILE narrows to one, else every profile
  locate    id-based: --profile/GMAIL_PROFILE pins one, else the command finds the id's owner
            (default first); active() is the default or None"""
import json
import os
import re

from . import paths
from .errors import UsageError

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
ROOT_KEYS = {"default_profile": None}

_active = {"name": None, "explicit": False, "all": []}


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
        raise UsageError(f"bad profile name {name!r}: lowercase letters, digits, - and _ (max 32), e.g. work, personal")
    return name


def default():
    """The default profile (root config, else the only one), or None."""
    have = names()
    d = root_config().get("default_profile")
    if d in have:
        return d
    return have[0] if len(have) == 1 else None


def ordered():
    """Every profile, the default first (locate tries them in this order)."""
    have, d = names(), default()
    return ([d] if d else []) + [n for n in have if n != d]


def resolve(requested, need):
    explicit = requested or os.environ.get("GMAIL_PROFILE")
    have = names()
    if explicit:
        check_name(explicit)
        if need != "create" and explicit not in have:
            raise UsageError(f"no profile {explicit!r}" + (f"; profiles: {', '.join(have)}" if have else "")
                             + f" - set one up with `gmail onboard --profile {explicit}`")
        return _use(explicit, True, [explicit])
    if need in ("none", "create") and not have:
        if need == "create":
            raise UsageError("onboard needs --profile NAME (a short label for this Gmail account, e.g. work, personal)")
        return _use(None, False, [])
    if not have:
        raise UsageError("no gmail profile yet: run `gmail onboard --profile NAME` "
                         "(NAME = a short label for this Gmail account, e.g. work, personal)")
    d = default()
    if need == "all":
        return _use(d, False, ordered())
    if d or need in ("none", "locate"):
        return _use(d, False, ordered())  # locate without a default: the command searches every profile
    if need == "create":
        raise UsageError(f"onboard needs --profile NAME (existing: {', '.join(have)}, or a new one)")
    raise UsageError(f"{len(have)} profiles and no default: pass --profile NAME "
                     f"(one of {', '.join(have)}) or `gmail profiles --default NAME`")


def _use(name, explicit, every):
    _active.update(name=name, explicit=explicit, all=list(every))
    return name


def active():
    return _active["name"]


def explicit():
    return _active["explicit"]


def selected():
    """need=all: the profiles to query (one when --profile was given)."""
    return list(_active["all"])


def dir_peek(name):
    return paths.root_peek() / name


def dir(name=None):  # noqa: A001 - reads as profile.dir()
    name = name or _active["name"]
    if not name:
        raise UsageError("no gmail profile selected: run `gmail onboard --profile NAME` first")
    p = paths.sub(paths.root(), name)
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass
    return p
