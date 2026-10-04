"""send: build and send in one step (no draft to review)."""
from ...api import compose, drafting

PROFILE = "locate"
WRITE = True
FIELDS = drafting.FIELDS
EPILOG = """examples:
  gmail send --to me@x.com --subject 'build done' --body 'all green'
  gmail send --reply-to 18f2a9c0d1e2f3a4 --body - < reply.txt

Same flags as `draft create`. Prefer `draft create` + `draft show` + `draft send` for anything a
person will read: sending cannot be undone. Receipt: message_id, thread_id.
"""


def add_args(p):
    drafting.add_args(p)


def run(ctx, args):
    prof = drafting.profile_for(ctx, args.reply_to)
    msg, thread = drafting.new_message(prof, args)
    sent = compose.send(prof, msg, thread)
    ctx.write([drafting.receipt(prof, sent=sent, msg=msg)], FIELDS, receipt=True)
