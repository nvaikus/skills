"""Per-profile config: ~/.claude/gdrive/<profile>/config.json + GDRIVE_* env overrides for the
top-level string keys. Written atomically, chmod 600 (it holds the OAuth client secret)."""
import copy
import json
import os

from . import paths, profile
from .errors import UsageError

# Keys are contract: recipes and other agents' configs depend on them. Never rename.
DEFAULTS = {
    "client_id": None, "client_secret": None, "project_id": None,
    "remote": "gdrive", "cache_limit": "10G",
    "account": None,            # {"email", "domain" (Workspace hd or null), "refresh_expires_in"}
    "apis_confirmed": False,    # the user said the APIs are enabled (re-verified live after login)
    "mode": None,               # onboarding: auto (browser job) | manual (step texts)
    "done_steps": [],           # onboarding steps confirmed before login: consent, branding, publish
    "audience": None,           # consent screen audience: internal (Workspace) | external
    "mount": None,              # {"what", "where", "persist"}
    "index_max_mb": 50,         # larger files get a metadata line only
    "ocr": "auto",              # auto: Google conversion for scanned PDFs/images · off
    "ocr_max_mb": 20,
    "index_sections": None,     # what=/ only: my-drive (always) + shared-with-me | shared-drives | shared:<Drive>
}
ENV_KEYS = ("client_id", "client_secret", "remote", "cache_limit")


def path(name=None):
    return profile.dir(name) / "config.json"


def load(name=None):
    """Active (or named) profile's config; DEFAULTS when no profile is selected."""
    cfg = copy.deepcopy(DEFAULTS)
    name = name or profile.active()
    if name:
        p = path(name)
        if p.exists():
            try:
                cfg.update(json.loads(p.read_text(encoding="utf-8-sig")))
            except ValueError as e:
                raise UsageError(f"{p}: invalid JSON: {e}") from None
    for key in ENV_KEYS:
        val = os.environ.get(f"GDRIVE_{key.upper()}")
        if val:
            cfg[key] = val
    return cfg


def update(name=None, **changes):
    """Merge changes into the profile's file (only what is passed: env overrides never persist). -> config."""
    p = path(name)
    on_disk = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    on_disk.update(changes)
    paths.write_private(p, json.dumps(on_disk, indent=1, ensure_ascii=False) + "\n")
    return load(name)


def require_client(cfg):
    """(client_id, client_secret) of the user's own OAuth client, or exit 2 pointing at onboarding."""
    cid, secret = cfg.get("client_id"), cfg.get("client_secret")
    if not cid or not secret or "..." in str(secret):
        raise UsageError(f"profile {profile.active()!r} has no OAuth client yet: run `gdrive onboard` "
                         "(it walks through creating one and importing its JSON with --client-file)")
    return cid, secret
