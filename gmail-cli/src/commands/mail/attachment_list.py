"""attachment list: every attachment of a message, numbered (the numbers `attachment get` takes)."""
from ...api import mail, render
from ...core import profile

PROFILE = "locate"
FIELDS = ["n", "name", "size", "type", "inline"]
EPILOG = """examples:
  gmail attachment list 18f2a9c0d1e2f3a4
Numbers follow the message's MIME order and are stable; inline = embedded image (logos etc.).
"""


def add_args(p):
    p.add_argument("id", metavar="MESSAGE_ID")


def run(ctx, args):
    prof = ctx.profile if profile.explicit() else mail.locate(args.id, ctx.profiles)
    atts = render.attachments(mail.message(prof, args.id).get("payload"))
    if not atts:
        ctx.note("no attachments")
    ctx.write([{k: a[k] for k in FIELDS} for a in atts], FIELDS)
