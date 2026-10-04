"""draft send: send a draft as it is."""
from ...api import compose, drafting, mail

PROFILE = "locate"
WRITE = True
FIELDS = ["profile", "message_id", "thread_id", "to", "subject"]
EPILOG = """examples:
  gmail draft send r-1234567890123456789
Sends immediately, no confirmation; the draft disappears and the message lands in Sent.
"""


def add_args(p):
    p.add_argument("id", metavar="DRAFT_ID")


def run(ctx, args):
    prof, d = drafting.locate_draft(ctx, args.id)
    h = mail.headers(d["message"].get("payload"))
    sent = compose.send_draft(prof, args.id)
    ctx.write([{"profile": prof, "message_id": sent.get("id"), "thread_id": sent.get("threadId"),
                "to": h.get("to", ""), "subject": h.get("subject", "")}], FIELDS, receipt=True)
