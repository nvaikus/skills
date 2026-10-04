"""modify: add/remove labels on message ids or on every match of a query."""
from ...api import targets
from ...core.errors import UsageError

PROFILE = "locate"
FIELDS = targets.FIELDS
WRITE = True
EPILOG = """examples:
  gmail modify 18f2a9c0d1e2f3a4 18f2a9c0d1e2f3b7 --add Clients/Acme --remove INBOX
  gmail modify -q 'from:billing@acme.com' --add Finance
  gmail modify -q 'label:Old' --add New --remove Old --dry-run

Labels: user labels by name (Parent/Child), or system ones: INBOX UNREAD STARRED IMPORTANT SPAM
TRASH PROMOTIONS SOCIAL UPDATES FORUMS PERSONAL. A missing user label is an error: create it
first (`gmail label create`). -q covers all matches (paged, 1000 per call); no confirmation.
Shortcuts: archive, mark-read, star, ... (see gmail --help).
"""


def add_args(p):
    targets.add_args(p)
    p.add_argument("--add", action="append", default=[], metavar="LABEL", help="label to add (repeatable)")
    p.add_argument("--remove", action="append", default=[], metavar="LABEL", help="label to remove (repeatable)")


def run(ctx, args):
    if not args.add and not args.remove:
        raise UsageError("nothing to do: --add LABEL and/or --remove LABEL")
    action = " ".join([f"+{x}" for x in args.add] + [f"-{x}" for x in args.remove])
    targets.change(ctx, args, action, args.add, args.remove)
