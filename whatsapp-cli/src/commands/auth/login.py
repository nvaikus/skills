"""login: link this machine as a WhatsApp device (QR or pairing code), then pull the history sync."""
from ...api import auth, sync
from ...core import config
from ...core.errors import UsageError

FIELDS = auth.ACCOUNT_FIELDS
WRITE = True
EPILOG = """examples:
  wa-cli login                              # QR: phone > Settings > Linked devices > Link a device
  wa-cli --account work login --phone +351912345678   # 8-char code to type on that phone instead

traps:
  interactive only: a person runs it in a terminal (not an agent, not `!` in Claude Code).
  after linking, it waits up to 3 min while the phone sends recent chat history - keep the phone
  online. Older messages than that sync are never readable by wa-cli.
  the session file (~/.wa-cli/accounts/<name>/session.db) is full account access (chmod 600). One
  session per machine: copying it elsewhere makes the two kick each other off.
  already logged in -> prints the account and changes nothing. Unlinked on the phone -> logout, login.
"""


def add_args(p):
    p.add_argument("--phone", help="pair with a code typed on the phone instead of scanning a QR (international format)")


def run(ctx, args):
    auth.require_tty()
    path = config.session_path(ctx.account)
    if path.exists():
        try:
            s = ctx.session()
        except UsageError as e:
            raise UsageError(f"{e} - to start over: wa-cli --account {ctx.account} logout, then login") from None
        ctx.note(f"account {ctx.account!r} is already logged in; wa-cli logout first to switch")
        ctx.write([auth.me_row(s.me(), ctx.account)], FIELDS, receipt=True)
        return
    linked = False
    try:
        s = ctx.session(need_auth=False)
        auth.link(s, args.phone.replace(" ", "") if args.phone else None)
        linked = True
        ctx.note(f"pulling chat history from the phone (up to {auth.HISTORY_WAIT} s; keep it online)")
        stats = sync.drain(s, ctx.store(), maximum=auth.HISTORY_WAIT, quiet=auth.HISTORY_QUIET, force_refresh=True)
        ctx.note(f"stored {stats.get('messages', 0)} messages from {stats.get('history_chats', 0)} chats")
        ctx.write([auth.me_row(s.me(), ctx.account)], FIELDS, receipt=True)
    except BaseException:
        ctx.close()
        if not linked and path.exists():
            path.unlink()  # never paired: leave no half-made account behind
        raise
