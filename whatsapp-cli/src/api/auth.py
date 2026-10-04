"""Login (QR or pairing code, both interactive) and the account row."""
import sys
import time

from ..core.errors import CliError, UsageError
from ..core.wa import FATAL

PAIR_DEADLINE = 180   # s for a person to scan / type the code
HISTORY_WAIT = 180    # s max for the phone's initial history sync after linking
HISTORY_QUIET = 15    # s of silence that ends it (the phone sends history in bursts)
PAIR_ERROR = 1        # PairStatus.Status ERROR
ACCOUNT_FIELDS = ["account", "jid", "phone", "name", "platform"]


def me_row(me, account):
    return {"account": account, "jid": me["jid"], "phone": f"+{me['phone']}" if me.get("phone") else None,
            "name": me["name"], "platform": me["platform"], "lid": me["lid"]}


def require_tty():
    if not sys.stdin.isatty():
        raise UsageError("login is interactive - a person runs it in a terminal (a separate window, or a new "
                         "tmux window), not through an agent")


def _show_qr(data, out):
    code = data.decode() if isinstance(data, bytes) else str(data)
    try:
        import segno
        segno.make_qr(code).terminal(out=out, compact=True)
    except ImportError:
        out.write(f"# segno missing (wa-cli deps installs it); QR payload: {code}\n")
    out.flush()


def link(session, phone=None, out=None):
    """Wait for the person to link this device. Returns when WhatsApp reports the connection."""
    out = out or sys.stderr  # at call time: wa.Quiet swaps sys.stderr while connected
    deadline = time.monotonic() + PAIR_DEADLINE
    shown = False
    if phone is None:
        out.write("# Phone: WhatsApp > Settings > Linked devices > Link a device, then scan:\n")
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise CliError(f"device not linked within {PAIR_DEADLINE} s - nothing changed; run wa-cli login again")
        got = session.next_event(min(left, 1))
        if got is None:
            continue
        kind, ev = got
        if kind == "connected":
            return
        if kind == "qr":
            if phone is None:
                if shown:
                    out.write("# QR refreshed:\n")
                _show_qr(ev, out)
                shown = True
            elif not shown:
                code = session.pair_phone(phone)
                out.write(f"# Phone {phone}: WhatsApp > Settings > Linked devices > Link a device > "
                          f"'Link with phone number instead', enter: {code}\n")
                out.flush()
                shown = True
        elif kind == "pair":
            if getattr(ev, "Status", 0) == PAIR_ERROR or getattr(ev, "Error", ""):
                raise CliError(f"pairing failed: {getattr(ev, 'Error', '') or 'error'} - run wa-cli login again")
            out.write("# linked; connecting\n")
        elif kind in FATAL:
            raise session.fatal(kind, ev)
        elif kind in ("message", "history"):
            session.pending.append((kind, ev))
