"""~/.claude/ebay/config.json: user defaults + setup progress. EBAY_MARKET / EBAY_SHIP_TO override."""
import copy
import json
import os

from . import paths
from .errors import UsageError

# Keys are contract: never rename.
DEFAULTS = {
    "market": None,       # X-EBAY-C-MARKETPLACE-ID, e.g. EBAY_DE
    "ship_to": None,      # ISO 3166 alpha-2 the user ships to, e.g. PT
    "zip": None,          # optional postal code: sharper calculated shipping
    "done_steps": [],     # setup steps the user confirmed: account, keyset, deletion
}
ENV = {"market": "EBAY_MARKET", "ship_to": "EBAY_SHIP_TO", "zip": "EBAY_ZIP"}


def path():
    return paths.root_peek() / "config.json"


def stored():
    p = path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise UsageError(f"{p}: invalid JSON: {e}") from None


def load():
    cfg = copy.deepcopy(DEFAULTS)
    cfg.update(stored())
    for key, var in ENV.items():
        if os.environ.get(var):
            cfg[key] = os.environ[var]
    return cfg


def update(**changes):
    """Merge changes into the file (env overrides never persist). -> config."""
    on_disk = stored()
    on_disk.update(changes)
    paths.write_private(path(), json.dumps(on_disk, indent=1, ensure_ascii=False) + "\n")
    return load()
