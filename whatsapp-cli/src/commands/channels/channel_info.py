"""channel-info: a channel by link, invite code, jid or stored name. Does not follow it."""
from ...api import channels

FIELDS = channels.CHANNEL_FIELDS
EPILOG = """examples:
  wa-cli channel-info https://whatsapp.com/channel/0029VaABCDEFghijklmnop12
  wa-cli channel-info 120363123456789012@newsletter -j     # + description, created, state

following = this account follows the channel (yes/no). Reading posts (channel-fetch) needs no follow.
There is no channel directory search: WhatsApp's "Find channels" is not in whatsmeow/neonize.
Find a channel's link on the web or ask the user for it.
"""


def add_args(p):
    p.add_argument("channel", help="whatsapp.com/channel/<code> link, the code, <id>@newsletter, or a stored name")


def run(ctx, args):
    ctx.write([channels.info(ctx.session(), ctx.store(), args.channel)], FIELDS, receipt=True)
