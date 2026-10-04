"""draft show: a draft exactly as it will be sent: headers, full body, attachments."""
from ...api import drafting, mail, render

PROFILE = "locate"
EPILOG = """examples:
  gmail draft show r-1234567890123456789
Shows the whole body (nothing stripped or cut). Next: gmail draft send DRAFT_ID, or draft edit.
"""


def add_args(p):
    p.add_argument("id", metavar="DRAFT_ID")


def run(ctx, args):
    prof, d = drafting.locate_draft(ctx, args.id)
    msg = d["message"]
    h = mail.headers(msg.get("payload"))
    names = mail.label_names(prof)
    text = "\n".join([f"# {h.get('subject') or '(no subject)'}",
                      f"draft: {d['id']} · profile: {prof} · thread: {msg.get('threadId')}"
                      + (f" · reply to: {h['in-reply-to']}" if h.get("in-reply-to") else ""),
                      "", render.message_md(msg, names, full=True, max_chars=0)])
    meta = {"profile": prof, "draft_id": d["id"], "message_id": msg.get("id"), "thread_id": msg.get("threadId"),
            **{k: h.get(k, "") for k in ("from", "to", "cc", "bcc", "subject")}}
    ctx.text(text, meta)
