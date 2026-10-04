"""filter create: a Gmail filter - criteria from/to/subject/query, label and inbox actions."""
from ...api import filters
from ...core.errors import UsageError

WRITE = True
FIELDS = ["profile", "id", "criteria", "actions", "applied"]
EPILOG = """examples:
  gmail filter create --profile work --from news@shop.com --archive --mark-read --add-label Shops
  gmail filter create --from 'a@x.com OR b@y.com' --add-label Receipts --apply
  gmail filter create --query 'list:digest.example.com' --trash

Acts on mail that arrives from now on; --apply also runs the same changes on mail it matches
already (like Gmail's "also apply to matching conversations"; --limit caps that). A missing
--add-label is created (Parent/Child too). archive = remove from Inbox; never-spam = never send to
Spam; trash = straight to Trash (Gmail deletes after 30 days).
Needs the Gmail settings permission: a profile logged in before filters existed gets exit 2 with
the re-login command (`gmail --profile NAME onboard --relogin`); `gmail profiles` column filters
says which profiles have it.
"""


def add_args(p):
    c = p.add_argument_group("criteria (at least one)")
    for k in filters.CRITERIA:
        c.add_argument(f"--{k}", metavar="TEXT", help=f"{k} matches (Gmail query syntax)" if k != "query" else
                       "has the words: any Gmail query")
    a = p.add_argument_group("actions (at least one)")
    a.add_argument("--add-label", action="append", default=[], metavar="NAME", help="apply a label (repeatable)")
    a.add_argument("--remove-label", action="append", default=[], metavar="NAME", help="remove a label (repeatable)")
    a.add_argument("--archive", action="store_true", help="skip the Inbox")
    a.add_argument("--mark-read", action="store_true", help="mark as read")
    a.add_argument("--never-spam", action="store_true", help="never send to Spam")
    a.add_argument("--trash", action="store_true", help="move to Trash")
    a.add_argument("--star", action="store_true", help="star it")
    p.add_argument("--apply", action="store_true", help="also change the mail it matches already")
    p.add_argument("--limit", type=int, metavar="N", help="with --apply: at most N newest matches")


def run(ctx, args):
    prof = ctx.profile
    criteria = {k: getattr(args, k) for k in filters.CRITERIA if getattr(args, k)}
    if not criteria:
        raise UsageError("give at least one criterion: --from, --to, --subject or --query")
    filters.need_settings(prof)
    add, remove = filters.label_ids(prof, args.add_label, args.remove_label, ctx.note)
    for flag, side, lid in (("archive", remove, "INBOX"), ("mark_read", remove, "UNREAD"),
                            ("never_spam", remove, "SPAM"), ("trash", add, "TRASH"), ("star", add, "STARRED")):
        if getattr(args, flag):
            side.append(lid)
    if not add and not remove:
        raise UsageError("give at least one action: --add-label, --remove-label, --archive, --mark-read, "
                         "--never-spam, --trash, --star")
    f = filters.create(prof, criteria, add, remove)
    r = filters.row(prof, f, filters.mail.label_names(prof))
    r["applied"] = filters.apply(prof, criteria, add, remove, args.limit) if args.apply else 0
    ctx.write([r], FIELDS)
