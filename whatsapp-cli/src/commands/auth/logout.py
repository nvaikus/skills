"""logout: unlink the device on WhatsApp, delete the local session (and with --purge the store)."""
import shutil

from ...core import config
from ...core.errors import UsageError

FIELDS = ["account", "status"]
WRITE = True
EPILOG = """examples:
  wa-cli --account work logout
  wa-cli logout --purge          # also delete the local message store

The device disappears from the phone's Linked devices; logging in again needs a new QR/code.
Already unlinked on the phone -> only the local files are removed.
"""


def add_args(p):
    p.add_argument("--purge", action="store_true", help="also delete the local message store (store.db)")


def run(ctx, args):
    session = config.session_path(ctx.account)
    if not session.exists():
        raise UsageError(f"account {ctx.account!r} is not logged in on this machine")
    status = "logged-out"
    try:
        ctx.session(drain=False).logout()
    except UsageError:
        status = "local-only"  # already unlinked or never paired
    ctx.close()
    if args.purge:  # the whole dir (lock, any db the Go side reopened): `accounts` must not list it
        shutil.rmtree(config.account_dir(ctx.account), ignore_errors=True)
    for f in (session, session.with_name(session.name + "-wal"), session.with_name(session.name + "-shm")):
        if f.exists():
            f.unlink()
    ctx.write([{"account": ctx.account, "status": status + ("+purged" if args.purge else "")}], FIELDS, receipt=True)
