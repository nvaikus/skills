"""Login flows (QR / phone code, then the 2FA cloud password) and the account row."""
import getpass
import sys
import time

from ..core import tg
from ..core.errors import CliError, UsageError

QR_DEADLINE = 180  # seconds; each QR token lives ~30 s and is recreated until then


def me_row(me, account):
    from .peers import name
    return {"account": account, "id": me.id, "username": me.username, "name": name(me),
            "phone": me.phone, "premium": bool(getattr(me, "premium", False))}


def _ask(prompt, secret=False):
    """Codes and passwords come from the terminal, never argv (shell history, process list, transcripts)."""
    if not sys.stdin.isatty():
        raise UsageError("login is interactive - run it in a terminal (a separate window, or a new tmux window), not through an agent")
    return (getpass.getpass(prompt) if secret else input(prompt)).strip()


def _password(client):
    for _ in range(3):
        pw = _ask("2FA cloud password: ", secret=True)
        try:
            return client.sign_in(password=pw)
        except tg.telethon().errors.PasswordHashInvalidError:
            sys.stderr.write("# wrong password\n")
    raise CliError("3 wrong 2FA passwords - stopped (Telegram rate-limits password attempts)")


def login_phone(client, phone):
    errors = tg.telethon().errors
    client.send_code_request(phone)
    sys.stderr.write(f"# code sent to the Telegram app of {phone} (or SMS)\n")
    code = _ask("code: ")
    try:
        return client.sign_in(phone=phone, code=code)
    except errors.SessionPasswordNeededError:
        return _password(client)


def _show_qr(url, out):
    try:
        import qrcode
    except ImportError:
        out.write(f"# qrcode package missing (tg-cli deps installs it); open this on the phone: {url}\n")
        return
    q = qrcode.QRCode(border=1)
    q.add_data(url)
    q.print_ascii(out=out, invert=True)
    out.flush()


def login_qr(client, out=sys.stderr):
    if not sys.stdin.isatty():
        raise UsageError("login is interactive - run it in a terminal (a separate window, or a new tmux window), not through an agent")
    errors = tg.telethon().errors
    qr = client.qr_login()
    deadline = time.monotonic() + QR_DEADLINE
    out.write("# Phone: Telegram > Settings > Devices > Link Desktop Device, then scan:\n")
    while True:
        _show_qr(qr.url, out)
        left = deadline - time.monotonic()
        if left <= 0:
            raise CliError(f"QR not scanned within {QR_DEADLINE} s - nothing changed; run tg-cli login again")
        try:
            return tg.run(client, qr.wait(timeout=min(left, 30)))
        except errors.SessionPasswordNeededError:
            return _password(client)
        except TimeoutError:
            tg.run(client, qr.recreate())
            out.write("# QR refreshed:\n")
