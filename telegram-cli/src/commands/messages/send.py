"""send: one text message or file(s), sent at once or scheduled. Deliberate no-rail (user decision, 2026-09-30)."""
import os
import sys

from ...api import messages, peers
from ...core.errors import UsageError
from ...core.timeparse import iso, parse_future

FIELDS = ["id", "chat_id", "chat", "date"]
WRITE = True
EPILOG = """examples:
  tg-cli send @ivan "Привет! Посмотри PR"
  tg-cli send -1001234567890 - < note.txt          # text from stdin
  tg-cli send @ivan "logs attached" --file logs.zip   # text = caption, optional with --file
  tg-cli send @ivan --file a.pdf --file b.pdf      # several = one album, one row per message
  ID=$(tg-cli send me "test" --fields id --no-header)
  tg-cli send @ivan "Доброе утро" --schedule "2026-10-17 08:00"   # local time; also +2h, ISO with offset

SENDS IMMEDIATELY - no preview, no confirmation; a sent message can only be deleted in the app.
Check the target first when unsure: tg-cli chats <name> / tg-cli user-find <name>.
TO: me | id | @username | t.me link | exact or unique dialog/contact name. Several matches ->
exit 2 listing candidates, nothing sent. Text is sent verbatim; --markdown parses **bold**, `code`, [x](url).
--schedule: Telegram delivers it later. Receipt id = scheduled id, date = scheduled time, link empty;
list: tg-cli history <to> --scheduled, cancel: tg-cli unschedule <to> <id>. Past or >365 days ahead is exit 2, nothing sent.
--file always goes as a document (no photo/video recompression); a missing file is exit 2, nothing sent.
"""


def add_args(p):
    p.add_argument("to")
    p.add_argument("text", nargs="?", help="message text (caption with --file), or - to read it from stdin")
    p.add_argument("--file", action="append", metavar="PATH", help="attach a file as a document; repeatable")
    p.add_argument("--markdown", action="store_true", help="parse Telegram markdown")
    p.add_argument("--reply-to", type=int, metavar="MSG_ID")
    p.add_argument("--schedule", metavar="WHEN",
                   help="send later: +30m / +2h / +1d, 'YYYY-MM-DD HH:MM' (local) or ISO with offset")


def run(ctx, args):
    text = sys.stdin.read() if args.text == "-" else (args.text or "")
    files = args.file or []
    for path in files:
        if not os.path.isfile(path):
            raise UsageError(f"no such file: {path} - nothing sent")
    if not files and not text.strip():
        raise UsageError("empty message - nothing sent")
    schedule = parse_future(args.schedule) if args.schedule else None
    client = ctx.client()
    chat = peers.resolve(client, args.to)
    if files:
        rows = messages.send_files(client, chat, files, text, args.markdown, args.reply_to, schedule)
    else:
        rows = [messages.send(client, chat, text, args.markdown, args.reply_to, schedule)]
    if schedule:
        ctx.note(f"scheduled for {iso(schedule)}")
    ctx.write(rows, FIELDS, receipt=len(rows) == 1)  # album: a list, like any listing
