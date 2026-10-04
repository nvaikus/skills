"""draft create: a new draft (or a reply draft) - review with `draft show`, then `draft send`."""
from ...api import compose, drafting

PROFILE = "locate"
WRITE = True
FIELDS = drafting.FIELDS
EPILOG = """examples:
  gmail draft create --to 'Anna <anna@x.com>' --subject 'Q3 report' --body 'Hi Anna, ...'
  printf '%s' "$TEXT" | gmail draft create --to anna@x.com --subject Report --body - --md --attach q3.pdf
  gmail draft create --reply-to 18f2a9c0d1e2f3a4 --body - --reply-all <<'EOF'
  ...
  EOF

--reply-to: same thread, 'Re: <subject>', In-Reply-To/References set, To = the sender (Reply-To
header honored; your own message -> its recipients); --to/--cc/--subject override. The quoted
original is not appended. The Gmail web signature is not added (the API never adds it): put it in
the body. Account: --profile, else the --reply-to message's account, else the default profile.
Next: gmail draft show DRAFT_ID, then gmail draft send DRAFT_ID.
"""


def add_args(p):
    drafting.add_args(p)


def run(ctx, args):
    prof = drafting.profile_for(ctx, args.reply_to)
    msg, thread = drafting.new_message(prof, args)
    d = compose.create_draft(prof, msg, thread)
    ctx.write([drafting.receipt(prof, draft=d, msg=msg)], FIELDS, receipt=True)
