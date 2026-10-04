"""channel-fetch: recent posts of a channel, saved into the store. Does not follow it."""
from ...api import channels

FIELDS = channels.POST_FIELDS
EPILOG = """examples:
  wa-cli channel-fetch https://whatsapp.com/channel/0029VaABCDEFghijklmnop12 -n 10
  wa-cli channel-fetch "Some Channel" --full
  wa-cli search "keyword" --chat "Some Channel" --offline    # later: posts are in the store

Works without following the channel (verified live 2026-10-04); `chats` hides such channels
unless --all. Newest first by server id. Posts carry no date (the server reply neonize hands over
has none). reactions = total count (-j: top_reactions per emoji); view counts are shown to
channel admins only. Fetched posts stay in the store, so search can find them afterwards.
"""


def add_args(p):
    p.add_argument("channel", help="link, invite code, <id>@newsletter, or a stored channel name")
    p.add_argument("-n", "--limit", type=int, default=20)
    p.add_argument("--full", action="store_true", help="do not cut post text")


def run(ctx, args):
    ch, rows = channels.fetch(ctx.session(), ctx.store(), args.channel, args.limit,
                              None if args.full else ctx.cfg["text_limit"])
    ctx.note(f"{ch['name']} ({ch['jid']}): {len(rows)} posts")
    ctx.write(rows, FIELDS)
    if any(r["truncated"] for r in rows):
        ctx.note(f"text cut to {ctx.cfg['text_limit']} chars - --full for whole posts")
