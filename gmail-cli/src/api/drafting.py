"""Shared plumbing of draft create / draft edit / send: flags -> EmailMessage, profile choice,
draft lookup across profiles."""
from ..core import profile
from ..core.errors import UsageError
from ..core.stdin import text_arg
from . import compose, google, mail

FIELDS = ["profile", "draft_id", "message_id", "thread_id", "to", "subject"]


def add_args(p, edit=False):
    p.add_argument("--to", metavar="ADDRS", help="recipients, comma-separated ('Name <a@x>, b@y')")
    p.add_argument("--cc", metavar="ADDRS")
    p.add_argument("--bcc", metavar="ADDRS")
    p.add_argument("--subject", metavar="TEXT")
    p.add_argument("--body", metavar="TEXT|-", help="body text; - reads stdin")
    p.add_argument("--md", action="store_true", help="body is markdown: send an HTML part too (lists, bold, links)")
    p.add_argument("--attach", action="append", default=[], metavar="FILE", help="attach a file (repeatable)")
    p.add_argument("--from", dest="sender", metavar="ADDR", help="a send-as alias of this account (Gmail settings)")
    if edit:
        p.add_argument("--drop-attach", action="append", default=[], metavar="NAME|N",
                       help="remove an attachment by file name or number (repeatable)")
    else:
        p.add_argument("--reply-to", metavar="MESSAGE_ID", help="answer this message: same thread, Re: subject, "
                       "reply headers, To = its sender (unless --to)")
        p.add_argument("--reply-all", action="store_true", help="with --reply-to: Cc everyone else on it")


def body_of(args):
    return text_arg(args.body, "--body") if args.body is not None else None


def profile_for(ctx, reply_id=None):
    """--profile wins; else the profile that holds the message replied to; else the default."""
    if profile.explicit():
        return ctx.profile
    if reply_id:
        return mail.locate(reply_id, ctx.profiles)
    if not ctx.profile:
        raise UsageError(f"which account? pass --profile NAME (one of {', '.join(ctx.profiles)}) "
                         "or set `gmail profiles --default NAME`")
    if len(ctx.profiles) > 1:
        ctx.note(f"from profile {ctx.profile} (default); --profile NAME for another account")
    return ctx.profile


def new_message(prof, args):
    """create / send: -> (EmailMessage, thread_id)."""
    if args.reply_all and not args.reply_to:
        raise UsageError("--reply-all needs --reply-to MESSAGE_ID")
    reply = compose.reply_context(prof, args.reply_to, args.reply_all) if args.reply_to else None
    to = args.to if args.to is not None else (reply or {}).get("to")
    cc = args.cc if args.cc is not None else (reply or {}).get("cc")
    subject = args.subject if args.subject is not None else (reply or {}).get("subject", "")
    body = body_of(args) or ""
    if not to and not args.cc and not args.bcc:
        raise UsageError("no recipient: --to ADDRS (or --reply-to MESSAGE_ID)")
    msg = compose.build(to, cc, args.bcc, subject, body, args.md, args.attach, args.sender, reply)
    return msg, (reply or {}).get("thread_id")


def receipt(prof, draft=None, sent=None, msg=None):
    m = (draft or {}).get("message") or sent or {}
    return {"profile": prof, "draft_id": (draft or {}).get("id", ""), "message_id": m.get("id"),
            "thread_id": m.get("threadId"), "to": (msg or {}).get("To", "") if msg is not None else "",
            "subject": (msg or {}).get("Subject", "") if msg is not None else ""}


def get_draft(prof, did, fmt="full"):
    return google.get(prof, f"/drafts/{did}", {"format": fmt})


def locate_draft(ctx, did):
    """-> (profile, draft) for a draft id; --profile pins the profile."""
    profs = [ctx.profile] if profile.explicit() else ctx.profiles
    for p in profs:
        try:
            return p, get_draft(p, did)
        except UsageError as e:
            if profile.explicit() or e.status not in (400, 404, 401, None):
                raise
    raise UsageError(f"no draft {did} in {', '.join(profs)}: ids come from `gmail draft list` / `draft create`")


def list_drafts(prof, limit):
    got = google.get(prof, "/drafts", {"maxResults": min(limit, 500)}) or {}
    names = mail.label_names(prof)

    def row(d):
        full = google.get(prof, f"/drafts/{d['id']}", {"format": "metadata"})
        r = mail.row(prof, full["message"], names)
        return {"profile": prof, "draft_id": d["id"], "date": r["date"], "to": r["to"],
                "subject": r["subject"], "snippet": r["snippet"], "ts": r["ts"]}
    return google.pmap(row, got.get("drafts", [])[:limit])
