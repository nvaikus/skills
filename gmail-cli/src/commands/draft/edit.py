"""draft edit: change recipients, subject, body or attachments of a draft; the rest stays."""
from ...api import compose, drafting
from ...core.errors import UsageError

PROFILE = "locate"
WRITE = True
FIELDS = drafting.FIELDS
EPILOG = """examples:
  gmail draft edit r-1234567890123456789 --subject 'Q3 report (final)'
  gmail draft edit r-1234567890123456789 --body - --md < new.md
  gmail draft edit r-1234567890123456789 --attach v2.pdf --drop-attach v1.pdf

Only the given flags change (an HTML body is rebuilt from the plain/markdown text); --to/--cc/--bcc replace the whole list ('' clears it). --attach adds,
--drop-attach removes. The draft id stays; reply headers and thread are kept.
"""


def add_args(p):
    p.add_argument("id", metavar="DRAFT_ID")
    drafting.add_args(p, edit=True)


def run(ctx, args):
    prof, d = drafting.locate_draft(ctx, args.id)
    raw = drafting.get_draft(prof, args.id, "raw")["message"]
    old = compose.parse_raw(raw["raw"])
    plain, htm, atts = compose.parts_of(old)
    for w in args.drop_attach:
        hit = [a for i, a in enumerate(atts, 1) if a[0] == w or (w.isdigit() and int(w) == i)]
        if not hit:
            raise UsageError(f"no attachment {w!r} in this draft (has: {', '.join(a[0] for a in atts) or 'none'})")
        atts = [a for a in atts if a is not hit[0]]
    body = drafting.body_of(args)
    md = args.md or (body is None and bool(htm))  # a --md draft keeps its markdown in the plain part
    pick = lambda new, key: new if new is not None else (old.get(key) or "")  # noqa: E731
    reply = {"in_reply_to": old.get("In-Reply-To"), "references": old.get("References")}
    msg = compose.build(pick(args.to, "To"), pick(args.cc, "Cc"), pick(args.bcc, "Bcc"),
                        pick(args.subject, "Subject"), body if body is not None else plain, md,
                        args.attach, args.sender or old.get("From"), reply, atts)
    upd = compose.update_draft(prof, args.id, msg, raw.get("threadId"))
    ctx.write([drafting.receipt(prof, draft=upd, msg=msg)], FIELDS, receipt=True)
