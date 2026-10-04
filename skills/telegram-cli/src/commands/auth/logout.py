"""logout: terminate the session on Telegram, delete the local session file."""
FIELDS = ["account", "status"]
WRITE = True
EPILOG = """examples:
  tg-cli --account work logout

The session disappears from Telegram > Settings > Devices; logging in again needs a new QR/code.
"""


def add_args(p):
    pass


def run(ctx, args):
    ctx.client().log_out()  # Telethon also deletes the .session file
    ctx.write([{"account": ctx.account, "status": "logged-out"}], FIELDS, receipt=True)
