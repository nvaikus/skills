"""join: join a group by invite link. Only on the user's explicit request; never in a loop."""
from ...api import groups

FIELDS = groups.GROUP_FIELDS
WRITE = True
EPILOG = """examples:
  wa-cli group-info https://chat.whatsapp.com/AbCdEf123456GhIjKl   # look first
  wa-cli join https://chat.whatsapp.com/AbCdEf123456GhIjKl

JOINS IMMEDIATELY - group members see you arrive. Only when the user asked to join this group;
joining many groups in a row gets accounts banned. Groups needing admin approval: the request
is sent and the row shows the group; you are in once an admin approves.
"""


def add_args(p):
    p.add_argument("link", help="https://chat.whatsapp.com/<code> or the code")


def run(ctx, args):
    ctx.write([groups.join(ctx.session(), ctx.store(), args.link)], FIELDS, receipt=True)
