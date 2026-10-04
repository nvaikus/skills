"""unsubscribe: leave mailing lists via their List-Unsubscribe header (one-click POST, else a mailto
sent from the account, else the URL to open by hand)."""
from ...api import mail, unsubscribe
from ...core import profile
from ...core.errors import CliError, UsageError

PROFILE = "locate"
WRITE = True
FIELDS = ["profile", "target", "method", "result"]
EPILOG = """examples:
  gmail unsubscribe --profile work news@shop.com deals@x.com --dry-run   # method it would use
  gmail unsubscribe --profile work news@shop.com
  gmail unsubscribe 18f2a9c0d1e2f3a4                                     # a message id finds its profile

SENDER = an address from `gmail senders`: its newest message carrying List-Unsubscribe is used
(the newest 10 are checked), in --profile or the default profile. ID = that exact message.
Order: one-click = RFC 8058 POST to the sender's https URL (no page opened, no cookies); else
mailto = an unsubscribe mail sent from the account (shows in Sent); else manual = a URL the user
must open (never fetched: a GET may confirm, track, or do nothing); '-' = no header: filter it
(`gmail filter create --from ADDR --archive`). Takes effect on the sender's side, often days later.
More columns: message_id, sender, one_click, mailto, url. Exit 1 when any target failed.
"""


def add_args(p):
    p.add_argument("targets", nargs="+", metavar="SENDER_OR_ID", help="sender address or message id")
    p.add_argument("--dry-run", action="store_true", help="print the method it would use, act on nothing")


def _profile_of(ctx, target, noted):
    if profile.explicit():
        return ctx.profile
    if "@" not in target:
        return mail.locate(target, ctx.profiles)
    if not ctx.profile:
        raise UsageError("a sender address needs one profile: pass --profile NAME (the `profile` column of "
                         "`gmail senders`)")
    if len(ctx.profiles) > 1 and not noted:
        ctx.note(f"profile {ctx.profile} (default); --profile NAME for another account")
    return ctx.profile


def run(ctx, args):
    rows, noted = [], False
    for t in dict.fromkeys(args.targets):
        prof = _profile_of(ctx, t, noted)
        noted = noted or "@" in t
        try:
            rows.append(unsubscribe.execute(unsubscribe.plan(prof, t), args.dry_run))
        except Exception as e:  # noqa: BLE001 - one bad target must not drop the receipts of the ones already done
            msg = str(e) if isinstance(e, (UsageError, CliError)) else f"{type(e).__name__}: {e}"
            rows.append({"profile": prof, "target": t, "method": "-", "result": f"failed: {msg}", "ok": False})
    if args.dry_run:
        ctx.note("dry run: nothing posted or sent")
    ctx.write(rows, FIELDS)
    bad = [r["target"] for r in rows if not r["ok"]]
    if bad:
        raise CliError(f"unsubscribe failed for: {', '.join(bad)}")
