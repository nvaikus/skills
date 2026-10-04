"""send: one text message or file(s), sent at once. One-off only: never loop it over recipients."""
import os
import sys

from ...api import messages, peers
from ...core.errors import UsageError

FIELDS = messages.RECEIPT_FIELDS
WRITE = True
EPILOG = """examples:
  wa-cli send "Мама" "Буду в 7"
  wa-cli send +351912345678 - < note.txt            # text from stdin
  wa-cli send me "test"                              # message to yourself
  wa-cli send "Команда QA" "logs" --file logs.zip    # text = caption of the first file
  ID=$(wa-cli send me "test" --fields id --no-header)

SENDS IMMEDIATELY - no preview, no confirmation. One message to one chat per call, only on the
user's request: WhatsApp bans accounts for bulk or automated sending - never loop sends.
TO: me | +phone | jid | exact or unique chat/contact name. Several matches -> exit 2 with
candidates, nothing sent. A phone not in the store is checked on WhatsApp first (not registered ->
exit 2, nothing sent). Text goes verbatim (WhatsApp renders *bold* _italic_ itself).
--file goes as a document (no recompression), one message per file; a missing file -> exit 2.
"""


def add_args(p):
    p.add_argument("to")
    p.add_argument("text", nargs="?", help="message text (caption with --file), or - to read it from stdin")
    p.add_argument("--file", action="append", metavar="PATH", help="attach a file as a document; repeatable")


def run(ctx, args):
    text = sys.stdin.read() if args.text == "-" else (args.text or "")
    files = args.file or []
    for path in files:
        if not os.path.isfile(path):
            raise UsageError(f"no such file: {path} - nothing sent")
    if not files and not text.strip():
        raise UsageError("empty message - nothing sent")
    store = ctx.store()
    if store.get_meta("synced"):
        peers.resolve(store, args.to)  # a bad/ambiguous name fails before connecting
    session = ctx.session()
    jid, _, _ = peers.resolve(store, args.to)  # again: the sync may have taught us its alt jid / name
    jid = messages.check_target(session, store, jid)
    if files:
        rows = messages.send_files(session, store, jid, files, text)
    else:
        rows = [messages.send(session, store, jid, text)]
    ctx.write(rows, FIELDS, receipt=len(rows) == 1)
