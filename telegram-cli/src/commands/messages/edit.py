"""edit: replace the text of this account's own already-sent message. Same no-rail stance as send."""
import sys

from ...api import messages, peers

FIELDS = ["id", "chat_id", "chat", "date"]
WRITE = True
EPILOG = """examples:
  tg-cli edit me 4512 "updated memo"
  tg-cli edit @ivan 5123 - < note.txt               # new text from stdin
  tg-cli edit -1001234567890 77 "**done**" --markdown

EDITS IMMEDIATELY - the old text is gone. Get the id first: tg-cli history <chat> --fields msg_id,out,text.
Only your own messages (out=1): another sender's message is exit 3, a missing id is exit 2, nothing edited.
The new text replaces the whole text (for media: the caption); sent verbatim, --markdown parses it.
"""


def add_args(p):
    p.add_argument("chat")
    p.add_argument("msg_id", type=int)
    p.add_argument("text", nargs="?", help="new message text, or - to read it from stdin")
    p.add_argument("--markdown", action="store_true", help="parse Telegram markdown")


def run(ctx, args):
    text = sys.stdin.read() if args.text == "-" else (args.text or "")
    client = ctx.client()
    chat = peers.resolve(client, args.chat)
    ctx.write([messages.edit(client, chat, args.msg_id, text, args.markdown)], FIELDS, receipt=True)
