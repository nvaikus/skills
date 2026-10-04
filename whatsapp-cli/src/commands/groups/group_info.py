"""group-info: what an invite link points to. Read-only: does not join."""
from ...api import groups

FIELDS = groups.GROUP_FIELDS
EPILOG = """examples:
  wa-cli group-info https://chat.whatsapp.com/AbCdEf123456GhIjKl
  wa-cli group-info AbCdEf123456GhIjKl -j          # + topic, announce, community, parent

participants = real member count, only when this account is in the group (member=yes); the
link preview lists just a few members (-j: participants_preview), never the total.
Revoked or invalid link -> exit 2.
"""


def add_args(p):
    p.add_argument("link", help="https://chat.whatsapp.com/<code> or the code")


def run(ctx, args):
    ctx.write([groups.info(ctx.session(), ctx.store(), args.link)], FIELDS, receipt=True)
