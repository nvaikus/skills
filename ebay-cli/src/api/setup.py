"""Guided setup: one step per run. advance() -> {status: waiting|done, id, say, next}."""
import getpass
import sys

from ..core import config, secrets
from ..core.errors import CliError, UsageError
from . import auth, browse, query, setup_say

STEPS = ("account", "keyset", "deletion")


def apply(cfg, done, market, ship_to, zip_code):
    changes = {}
    if done:
        changes["done_steps"] = sorted(set(cfg.get("done_steps") or []) | set(done))
    for k, v in (("market", market), ("ship_to", ship_to), ("zip", zip_code)):
        if v is not None:
            changes[k] = v
    return config.update(**changes) if changes else cfg


def read_keys():
    """--keys-stdin: App ID then Cert ID from the terminal (hidden) or two piped lines."""
    if sys.stdin.isatty():
        cid = input("App ID (Client ID): ").strip()
        sec = getpass.getpass("Cert ID (Client Secret, hidden): ").strip()
    else:
        lines = [x.strip() for x in sys.stdin.read().splitlines() if x.strip()]
        if len(lines) != 2:
            raise UsageError("--keys-stdin expects two lines: App ID, then Cert ID")
        cid, sec = lines
    if not cid or not sec:
        raise UsageError("both App ID and Cert ID are needed")
    if cid == sec:
        raise UsageError("App ID and Cert ID are the same value: copy each from its own field")
    secrets.store_file(cid, sec)
    return cid, sec


def verify(cfg):
    """Live: mint a token and run a one-row search. -> None or the error text."""
    try:
        auth.drop()
        auth.access_token(force=True)
        loc = query.location({}, cfg)
        browse.search({"q": "phone", "limit": 1}, loc)
    except CliError as e:
        return str(e)
    return None


def advance(cfg, live=verify):
    done = set(cfg.get("done_steps") or [])
    for step, text in (("account", setup_say.ACCOUNT), ("keyset", setup_say.KEYSET), ("deletion", setup_say.DELETION)):
        if step not in done:
            return {"status": "waiting", "id": step, "say": text, "next": f"ebay setup --done {step}"}
    cid, sec, _ = secrets.client()
    if not cid or not sec:
        return {"status": "waiting", "id": "keys", "say": setup_say.keys(), "next": "ebay setup"}
    if not cfg.get("market") or not cfg.get("ship_to"):
        return {"status": "waiting", "id": "defaults", "say": setup_say.DEFAULTS,
                "next": "ebay setup --market EBAY_DE --ship-to PT [--zip CODE]   (the user's answers)"}
    err = live(cfg)
    if err:
        return {"status": "waiting", "id": "keys-rejected", "say": setup_say.rejected(err), "next": "ebay setup"}
    return {"status": "done", "id": "done",
            "say": setup_say.DONE.format(market=cfg["market"], ship=cfg["ship_to"]), "next": None}
