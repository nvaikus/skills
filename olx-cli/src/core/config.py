"""~/.claude/olx/config.json: user defaults. OLX_SITE overrides site."""
import copy
import json
import os

from . import paths
from .errors import UsageError

# Keys are contract: never rename.
DEFAULTS = {
    "site": "pt",            # OLX country: pt pl ro bg ua kz uz (www.olx.<site>)
    "notify_topic": "olx",   # claude-tg notify_topics key for `watch run --notify`
    # account actions (login, msg) in the user's own Chrome: see references/account.md
    "browser_session": None,        # playwright-cli session = Chrome profile dir name (default "olx")
    "browser_port": None,           # Chrome remote-debugging port (default 9335)
    "browser_display": None,        # Linux X display when the env has none, e.g. ":99" (always-on Xvfb)
    "browser_view_url": None,       # the user's remote view of that display (noVNC link), quoted in exit-5 texts
    "browser_launch_prefix": None,  # argv before the Chrome command, e.g. systemd-run --user ... ({ts} {display} {path} {cwd})
    "browser_chrome": None,         # Chrome executable when not on the usual path
}
ENV = {"site": "OLX_SITE", "browser_session": "OLX_BROWSER_SESSION", "browser_port": "OLX_BROWSER_PORT",
       "browser_view_url": "OLX_VIEW_URL"}


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
