"""login: QR or phone code, then 2FA password. Writes ~/.tg-cli/sessions/<account>.session."""
from ...api import auth

FIELDS = ["account", "id", "username", "name", "phone", "premium"]
WRITE = True
EPILOG = """examples:
  tg-cli login                           # QR: phone > Settings > Devices > Link Desktop Device
  tg-cli --account work login --phone +351912345678

traps:
  interactive only: a person runs it in a terminal (not an agent, not `!` in Claude Code); code and
  2FA password are typed at the prompt, never passed as flags.
  the session file is full account access (chmod 600). Using one session on two machines at
  once can get it revoked - log in separately on each machine.
  already logged in -> prints the account and changes nothing.
"""


def add_args(p):
    p.add_argument("--phone", help="log in with a code sent to this number instead of the QR")


def run(ctx, args):
    client = ctx.client(need_auth=False)
    if client.is_user_authorized():
        ctx.note(f"account {ctx.account!r} is already logged in; tg-cli logout first to switch")
    elif args.phone:
        auth.login_phone(client, args.phone)
    else:
        auth.login_qr(client)
    ctx.write([auth.me_row(client.get_me(), ctx.account)], FIELDS, receipt=True)
