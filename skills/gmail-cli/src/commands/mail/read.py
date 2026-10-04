"""read: a thread (or one message) as compact markdown."""
from ...api import mail, render
from ...core import profile

PROFILE = "locate"
EPILOG = """examples:
  gmail read 18f2a9c0d1e2f3a4                 # message id or thread id: the whole conversation
  gmail read 18f2a9c0d1e2f3a4 --message       # only that message
  gmail read 18f2a9c0d1e2f3a4 --full          # keep quoted replies and signatures
  gmail read 18f2a9c0d1e2f3a4 -j              # {id, profile, subject, messages[...], text}

Compact by default: text/plain preferred, HTML converted to text (links as [text](url), long
tracking URLs dropped), quoted replies ("On ... wrote:", "> ", Outlook "From:/Sent:" blocks) and
signatures cut - the earlier messages of the thread are shown in full above anyway. A forward
(Fwd: subject) keeps its forwarded part. Each message is capped at --max chars (default 6000).
Attachments are listed by number: gmail attachment get MESSAGE_ID N. Reading does not mark as read.
The id's profile is found automatically (default profile first); --profile skips the lookup.
"""


def add_args(p):
    p.add_argument("id", metavar="ID", help="message id or thread id (search: id / thread_id)")
    p.add_argument("--message", action="store_true", help="only this message, not the whole thread")
    p.add_argument("--full", action="store_true", help="keep quoted replies and signatures")
    p.add_argument("--max", type=int, default=6000, metavar="CHARS", help="per-message text cap, 0 = none (default 6000)")


def run(ctx, args):
    prof = ctx.profile if profile.explicit() else mail.locate(args.id, ctx.profiles)
    t = mail.thread_of(prof, args.id)
    only = None
    if args.message:
        only = args.id if any(m["id"] == args.id for m in t.get("messages", [])) else t["messages"][-1]["id"]
    names = mail.label_names(prof)
    text = render.thread_md(t, names, prof, args.full, args.max, only)
    msgs = [m for m in t.get("messages", []) if not only or m["id"] == only]
    meta = {"id": t.get("id"), "profile": prof,
            "subject": mail.headers(t["messages"][0].get("payload")).get("subject") if t.get("messages") else None,
            "messages": [{"id": m["id"], "from": mail.headers(m.get("payload")).get("from"),
                          "date": mail.when(m.get("internalDate")),
                          "attachments": [{k: a[k] for k in ("n", "name", "size", "type", "inline")}
                                          for a in render.attachments(m.get("payload"))]} for m in msgs]}
    ctx.text(text, meta)
