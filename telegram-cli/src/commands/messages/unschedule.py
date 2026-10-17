"""unschedule: cancel scheduled (not yet delivered) messages of one chat by id."""
from ...api import messages, peers

FIELDS = ["id", "chat_id", "chat", "date"]
WRITE = True
EPILOG = """examples:
  tg-cli history @ivan --scheduled --fields msg_id,date,text   # find the ids first
  tg-cli unschedule @ivan 4513
  tg-cli unschedule me 4513 4514                               # several = one request

DELETES IMMEDIATELY - a cancelled message is gone, not sent. Ids are scheduled ids (history --scheduled,
send --schedule receipt), not ordinary message ids. Any id not in the chat's scheduled list -> exit 2,
nothing deleted. Receipt: one row per cancelled message, date = the time it was scheduled for (-j adds text).
"""


def add_args(p):
    p.add_argument("chat")
    p.add_argument("ids", type=int, nargs="+", metavar="id", help="scheduled message id(s)")


def run(ctx, args):
    client = ctx.client()
    chat = peers.resolve(client, args.chat)
    rows = messages.unschedule(client, chat, args.ids)
    ctx.write(rows, FIELDS, receipt=len(rows) == 1)
