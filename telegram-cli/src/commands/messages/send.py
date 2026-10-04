"""send: one text message or file(s), sent at once. Deliberate no-rail (user decision, 2026-09-30)."""
import os
import sys

from ...api import messages, peers
from ...core.errors import UsageError

FIELDS = ["id", "chat_id", "chat", "date"]
WRITE = True
EPILOG = """examples:
  tg-cli send @ivan "Привет! Посмотри PR"
  tg-cli send -1001234567890 - < note.txt          # text from stdin
  tg-cli send @ivan "logs attached" --file logs.zip   # text = caption, optional with --file
  tg-cli send @ivan --file a.pdf --file b.pdf      # several = one album, one row per message
  ID=$(tg-cli send me "test" --fields id --no-header)

SENDS IMMEDIATELY - no preview, no confirmation; a sent message can only be deleted in the app.
Check the target first when unsure: tg-cli chats <name> / tg-cli user-find <name>.
TO: me | id | @username | t.me link | exact or unique dialog/contact name. Several matches ->
exit 2 listing candidates, nothing sent. Text is sent verbatim; --markdown parses **bold**, `code`, [x](url).
--file always goes as a document (no photo/video recompression); a missing file is exit 2, nothing sent.
"""


def add_args(p):
    p.add_argument("to")
    p.add_argument("text", nargs="?", help="message text (caption with --file), or - to read it from stdin")
    p.add_argument("--file", action="append", metavar="PATH", help="attach a file as a document; repeatable")
    p.add_argument("--markdown", action="store_true", help="parse Telegram markdown")
    p.add_argument("--reply-to", type=int, metavar="MSG_ID")


def run(ctx, args):
    text = sys.stdin.read() if args.text == "-" else (args.text or "")
    files = args.file or []
    for path in files:
        if not os.path.isfile(path):
            raise UsageError(f"no such file: {path} - nothing sent")
    if not files and not text.strip():
        raise UsageError("empty message - nothing sent")
    client = ctx.client()
    chat = peers.resolve(client, args.to)
    if files:
        rows = messages.send_files(client, chat, files, text, args.markdown, args.reply_to)
    else:
        rows = [messages.send(client, chat, text, args.markdown, args.reply_to)]
    ctx.write(rows, FIELDS, receipt=len(rows) == 1)  # album: a list, like any listing
