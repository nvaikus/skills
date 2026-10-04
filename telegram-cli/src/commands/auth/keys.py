"""keys: store the Telegram API keys, typed at a prompt."""
import getpass
import sys

from ...core import config
from ...core.errors import UsageError

FIELDS = ["config", "api_id"]
WRITE = True
EPILOG = """examples:
  tg-cli keys          # asks api_id, then api_hash (hidden); writes ~/.tg-cli.json, chmod 600

Keys come from my.telegram.org -> API development tools (one app per Telegram account; form:
title tg-cli, short name tgcli, platform Desktop; "ERROR" on submit = VPN/adblock, retry without).
Interactive: run it in a terminal, never paste the keys into a chat. TG_CLI_API_ID/HASH env override the file.
"""


def add_args(p):
    pass


def run(ctx, args):
    if not sys.stdin.isatty():
        raise UsageError("keys is interactive - run it in a terminal, not through an agent")
    api_id = input("api_id: ").strip()
    if not api_id.isdigit():
        raise UsageError(f"api_id is a number, got {api_id!r} - nothing saved")
    api_hash = getpass.getpass("api_hash (hidden): ").strip()
    if len(api_hash) != 32:
        raise UsageError(f"api_hash is 32 characters, got {len(api_hash)} - nothing saved")
    config.save({"api_id": int(api_id), "api_hash": api_hash})
    ctx.write([{"config": str(config.CONFIG_PATH), "api_id": int(api_id)}], FIELDS, receipt=True)
    ctx.note("next: tg-cli login")
