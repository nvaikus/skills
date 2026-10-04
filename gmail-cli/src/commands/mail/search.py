"""search: Gmail query syntax -> one TSV row per message (or thread), every profile merged by date."""
from ...api import mail
from ...core import profile
from ...core.errors import CliError, UsageError

PROFILE = "all"
FIELDS = ["profile", "id", "thread_id", "date", "from", "subject", "labels", "snippet"]
EPILOG = """examples:
  gmail search 'from:anna invoice newer_than:30d'          # every connected account
  gmail search --profile work 'is:unread in:inbox' --limit 50
  gmail search 'has:attachment filename:pdf subject:contract' --threads
  gmail search 'label:clients/acme' --fields profile,id,subject -j

QUERY = exactly what the Gmail search box takes: from: to: subject: label: is:unread is:starred
has:attachment filename: newer_than:7d older_than:1y after:2026/01/31 before: category:promotions
in:anywhere "exact phrase" -word OR {a b}. Empty QUERY = newest mail. Spam/Trash only with
--spam-trash (or in:spam / in:trash).
Without --profile every profile is queried in parallel; --limit applies to the merged list. A
profile that fails (logged out) is skipped with a '# profile X skipped' note. Large --limit is
paced under Gmail's per-user quota (~400-1000 messages/min per profile); a failure partway still
prints the rows fetched, then exits 1 naming what is missing.
Columns: date = received, local time; labels = names (CATEGORY_ prefix dropped); snippet = first
~140 chars. More: to, ts (epoch ms); --threads adds count (messages in the thread, row = last one).
Next: gmail read ID (it finds the profile itself).
"""


def add_args(p):
    p.add_argument("query", nargs="*", metavar="QUERY", help="Gmail search query (words are joined)")
    p.add_argument("--limit", type=int, default=20, metavar="N", help="max rows (default 20)")
    p.add_argument("--threads", action="store_true", help="one row per conversation instead of per message")
    p.add_argument("--all", action="store_true", help="every profile (the default without --profile)")
    p.add_argument("--spam-trash", action="store_true", help="include Spam and Trash")


def run(ctx, args):
    if args.all and profile.explicit():
        raise UsageError("--all and --profile contradict each other: drop one")
    if args.limit < 1:
        raise UsageError("--limit must be >= 1")
    q = " ".join(args.query).strip()
    rows, problems = mail.search(ctx.profiles, q, args.limit, args.threads, args.spam_trash, ctx.note)
    if not rows and not problems:
        ctx.note(f"no matches for {q!r} in {', '.join(ctx.profiles)}")
    ctx.write(rows, FIELDS + (["count"] if args.threads else []))
    if problems:
        raise CliError("rows above are incomplete:\n" + "\n".join(problems), status=0)
