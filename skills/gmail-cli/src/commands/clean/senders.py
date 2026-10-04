"""senders: who sends the most mail - a query's messages grouped by sender address, every profile."""
from ...api import senders
from ...core import profile
from ...core.errors import CliError, UsageError

PROFILE = "all"
DEFAULT_Q = "newer_than:1y -from:me"
FIELDS = ["profile", "sender", "name", "count", "unread", "last", "category", "subject", "unsubscribe"]
EPILOG = f"""examples:
  gmail senders                                       # every profile, query '{DEFAULT_Q}'
  gmail senders --profile work 'in:inbox newer_than:6m' --min 5
  gmail senders 'category:promotions' --limit 5000 --fields profile,sender,count,unsubscribe
  gmail unsubscribe --profile work news@shop.com      # then: the sender from a row

Rows sorted by count, descending. unread = messages still unread; last = newest message (local
time); category = Gmail tab most of them sit in (primary/promotions/social/updates/forums, '-' none);
subject = of the newest message; unsubscribe = one-click (RFC 8058 POST), mailto, url (a page to
open by hand) or '-' (no List-Unsubscribe header). More: latest_id, unsub_id (message carrying the
header), ts.
Speed: Gmail's per-user quota allows ~400-1000 message reads a minute (depends on the OAuth
project); the scan is paced to it (a thread with several hits = one call), so 3000 messages can
take ~5 min: run it once, keep the output, filter with awk/--min. --limit caps messages scanned
per profile (newest first). A failure partway prints what was aggregated, then exits 1.
"""


def add_args(p):
    p.add_argument("query", nargs="*", metavar="QUERY", help=f"Gmail search query (default: {DEFAULT_Q})")
    p.add_argument("--limit", type=int, default=2000, metavar="N", help="messages scanned per profile (default 2000)")
    p.add_argument("--min", type=int, default=1, metavar="N", help="only senders with at least N messages")


def run(ctx, args):
    if args.limit < 1 or args.min < 1:
        raise UsageError("--limit and --min must be >= 1")
    q = " ".join(args.query).strip() or DEFAULT_Q
    rows, problems = senders.report(ctx.profiles, q, args.limit, args.min, ctx.note)
    if not rows and not problems:
        ctx.note(f"no senders for {q!r} (--min {args.min}) in {', '.join(ctx.profiles)}")
    elif not profile.explicit() and len(ctx.profiles) > 1:
        ctx.note(f"profiles: {', '.join(ctx.profiles)}; --profile NAME for one")
    ctx.write(rows, FIELDS)
    if problems:
        raise CliError("rows above are incomplete:\n" + "\n".join(problems), status=0)
