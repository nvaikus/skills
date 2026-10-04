"""setup: guided, resumable onboarding. Prints ONLY the next step."""
from ...api import markets, setup
from ...core.errors import Waiting

EPILOG = """examples:
  ebay setup                                   # start, or show where it stands
  ebay setup --done account                    # the user finished a portal step: account | keyset | deletion
  ebay setup --market EBAY_DE --ship-to PT     # defaults (the user's answers); --zip 1000-001 optional
  ebay setup --keys-stdin                      # the USER runs this in their own terminal (non-macOS)

Driving it (agent): run, relay the text under "say to the user" WORD FOR WORD (a "(agent ...)" text is
for you: ask the user, then run "then run" with the answers), repeat until DONE. Exit 5 = waiting on
the user; 0 = done. Keys never pass through the chat or argv: macOS Keychain items EBAY_CLIENT_ID /
EBAY_CLIENT_SECRET, else env vars of those names, else --keys-stdin (~/.claude/ebay/credentials.json, 600).
The last step proves the keys live (token + one search); `ebay doctor` repeats that check any time.
"""


def add_args(p):
    p.add_argument("--done", action="append", choices=setup.STEPS, metavar="STEP",
                   help="the user finished a portal step: account | keyset | deletion")
    p.add_argument("--market", metavar="M", help="default eBay site, e.g. EBAY_DE")
    p.add_argument("--ship-to", metavar="CC", help="default delivery country, e.g. PT")
    p.add_argument("--zip", metavar="CODE", help="default postal code (sharper calculated shipping)")
    p.add_argument("--keys-stdin", action="store_true", help="read App ID + Cert ID from the terminal / stdin")


def run(ctx, args):
    if args.keys_stdin:
        setup.read_keys()
        ctx.note("keys stored in ~/.claude/ebay/credentials.json (chmod 600)")
    cfg = setup.apply(ctx.cfg, args.done, markets.norm(args.market), markets.country(args.ship_to), args.zip)
    r = setup.advance(cfg)
    head = "DONE" if r["status"] == "done" else f"WAITING {r['id']}"
    out = [head, "--- say to the user ---", r["say"]]
    if r.get("next"):
        out += ["--- then run ---", r["next"]]
    ctx.text("\n".join(out), {k: r[k] for k in ("status", "id", "say", "next")})
    if r["status"] == "waiting":
        raise Waiting(f"setup waits on the user ({r['id']}): relay the text, then run the command under 'then run'")
