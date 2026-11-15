"""msg send: message the seller of a listing through OLX chat."""
import sys

from ...api import account, query

FIELDS = ["id", "seller", "conversation", "time", "text"]
EPILOG = """examples:
  olx msg send 674669746 "Olá! Ainda está disponível? Aceita 80€?"
  echo "Is the frame size M?" | olx msg send "https://www.olx.pt/d/anuncio/...-IDJEQcI.html"

Sends exactly once (no retry: a rerun sends a second copy - check `olx msg list --id ID` first).
Verified: exit 0 only when the message shows in the conversation with its time (= delivered).
Opens the listing page and clicks its own "send message" button: an existing conversation is reused.
"""


def add_args(p):
    p.add_argument("ref", metavar="ID|URL", help="listing id or OLX listing URL")
    p.add_argument("text", nargs="?", help="message; omitted or '-' = read stdin")
    query.add_site_arg(p)


def run(ctx, args):
    text = account.message_text(args.text, sys.stdin)
    s = query.site({"site": args.site}, ctx.cfg)
    ctx.write([account.msg_send(ctx.cfg, args.ref, text, s)], FIELDS, receipt=True)
