"""doctor: keys, defaults, token, live search - one row per check."""
import time

from ...api import auth, browse, query
from ...core import secrets
from ...core.errors import CliError

FIELDS = ["check", "ok", "detail"]
EPILOG = """examples:
  ebay doctor
  ebay doctor -j

Checks: keys (where they come from, masked), defaults (market, ship-to), token (mints a fresh one),
search (one live result in the default market). Exit 1 when any check fails; the detail says what to do.
"""


def add_args(p):
    pass


def run(ctx, args):
    rows = []
    cid, sec, src = secrets.client()
    keys_ok = bool(cid and sec)
    rows.append({"check": "keys", "ok": keys_ok,
                 "detail": f"{src}: App ID {secrets.mask(cid)}, Cert ID {secrets.mask(sec)}" if keys_ok
                 else "missing: run `ebay setup`"})
    cfg = ctx.cfg
    rows.append({"check": "defaults", "ok": bool(cfg.get("market") and cfg.get("ship_to")),
                 "detail": f"market {cfg.get('market') or '-'}, ship-to {cfg.get('ship_to') or '-'}, zip {cfg.get('zip') or '-'}"
                 + ("" if cfg.get("market") and cfg.get("ship_to") else "; set with `ebay setup --market .. --ship-to ..`")})
    if keys_ok:
        try:
            auth.drop()
            auth.access_token(force=True)
            rows.append({"check": "token", "ok": True, "detail": "application token minted"})
            loc = query.location({}, cfg)
            t0 = time.time()
            res, total = browse.search({"q": "phone", "limit": 1}, loc)
            rows.append({"check": "search", "ok": bool(res),
                         "detail": f"{loc['market']}: {total} results for 'phone' in {time.time() - t0:.1f}s"})
        except CliError as e:
            rows.append({"check": "token" if len(rows) == 2 else "search", "ok": False, "detail": str(e)})
    ctx.write(rows, FIELDS)
    if not all(r["ok"] for r in rows):
        raise CliError("some checks failed (see detail)")
