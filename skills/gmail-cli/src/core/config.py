"""Per-profile config: ~/.claude/gmail/<profile>/config.json + GMAIL_CLIENT_ID/SECRET env overrides.
Written atomically, chmod 600 (it holds the OAuth client secret)."""
import copy
import json
import os

from . import paths, profile
from .errors import UsageError

# Keys are contract: other agents' configs depend on them. Never rename.
DEFAULTS = {
    "client_id": None, "client_secret": None, "project_id": None,
    "client_from": None,        # where the client came from: gmail:<p> | gdrive:<p> | file
    "app_name": None,           # the consent screen's app name (login texts quote it)
    "account": None,            # {"email", "domain" (Workspace hd or null), "refresh_expires_in"}
    "apis_confirmed": False,    # the user said the Gmail API is on (re-verified live after login)
    "apis_confirmed_at": None,  # epoch: a fresh "on" may take minutes to propagate
    "gmail_api": False,         # a live call proved the Gmail API answers for this client's project
    "done_steps": [],           # onboarding steps confirmed before login: consent, branding, publish
    "audience": None,           # consent screen audience: internal (Workspace) | external
    "keep_testing": False,
}
ENV_KEYS = ("client_id", "client_secret")


def path(name=None):
    return profile.dir(name) / "config.json"


def load(name=None):
    """Active (or named) profile's config; DEFAULTS when no profile is selected."""
    cfg = copy.deepcopy(DEFAULTS)
    name = name or profile.active()
    if name:
        p = profile.dir_peek(name) / "config.json"
        if p.exists():
            try:
                cfg.update(json.loads(p.read_text(encoding="utf-8-sig")))
            except ValueError as e:
                raise UsageError(f"{p}: invalid JSON: {e}") from None
    for key in ENV_KEYS:
        val = os.environ.get(f"GMAIL_{key.upper()}")
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


def require_client(cfg, prof=None):
    """(client_id, client_secret) of the user's own OAuth client, or exit 2 pointing at onboarding."""
    cid, secret = cfg.get("client_id"), cfg.get("client_secret")
    if not cid or not secret or "..." in str(secret):
        raise UsageError(f"profile {prof or profile.active()!r} has no OAuth client yet: run "
                         f"`gmail onboard --profile {prof or profile.active()}`")
    return cid, secret
