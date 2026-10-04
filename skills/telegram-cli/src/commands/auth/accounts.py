"""accounts: session files on this machine. No network."""
from ...core import config

FIELDS = ["account", "default", "session"]
EPILOG = """examples:
  tg-cli accounts
  tg-cli whoami --account work    # check a session is still alive (network)
"""


def add_args(p):
    pass


def run(ctx, args):
    rows = [{"account": a, "default": a == ctx.cfg["default_account"], "session": str(config.session_path(a))}
            for a in config.accounts()]
    ctx.write(rows, FIELDS)
    if not rows:
        ctx.note("no accounts on this machine - run: tg-cli login")
