"""~/.claude/vinted/config.json: user defaults. VINTED_SITE overrides site."""
import copy
import json
import os

from . import paths
from .errors import UsageError

# Keys are contract: never rename.
DEFAULTS = {
    "site": "pt",              # Vinted domain: pt fr es de it pl ... co.uk (www.vinted.<site>)
    "notify_topic": "vinted",  # claude-tg notify_topics key for `watch run --notify`
}
ENV = {"site": "VINTED_SITE"}


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
