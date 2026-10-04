"""~/.wa-cli.json + WA_CLI_* env overrides; state (venv, per-account session + store) under ~/.wa-cli/."""
import json
import os
import re
from pathlib import Path

from .errors import UsageError

CONFIG_PATH = Path(os.environ.get("WA_CLI_CONFIG", "~/.wa-cli.json")).expanduser()
HOME = Path(os.environ.get("WA_CLI_HOME", "~/.wa-cli")).expanduser()
ACCOUNTS = HOME / "accounts"
LOGS = HOME / "logs"

# Keys are contract: recipes and other agents' configs depend on them. Never rename.
DEFAULTS = {"default_account": "default", "text_limit": 200, "sync_wait": 20}
INTS = ("text_limit", "sync_wait")
ACCOUNT_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def load():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig")))
        except ValueError as e:
            raise UsageError(f"{CONFIG_PATH}: invalid JSON: {e}") from None
    for key in DEFAULTS:
        val = os.environ.get(f"WA_CLI_{key.upper()}")
        if val:
            cfg[key] = val
    for key in INTS:
        try:
            cfg[key] = int(cfg[key])
        except (TypeError, ValueError):
            raise UsageError(f"config {key} must be a number, got {cfg[key]!r}") from None
    return cfg


def account_dir(account):
    if not ACCOUNT_RE.fullmatch(account or ""):
        raise UsageError(f"bad account name {account!r}: letters, digits, _ . - only")
    return ACCOUNTS / account


def session_path(account):
    """whatsmeow's own sqlite (device keys = full account access)."""
    return account_dir(account) / "session.db"


def store_path(account):
    """wa-cli's message store (chats, contacts, messages + FTS5)."""
    return account_dir(account) / "store.db"


def log_path(account):
    return LOGS / f"{account}.log"


def accounts():
    if not ACCOUNTS.exists():
        return []
    return sorted(p.name for p in ACCOUNTS.iterdir() if _nonempty(p / "session.db"))


def _nonempty(path):
    """An empty session.db is sqlite reopened by path after logout, not an account."""
    try:
        return path.stat().st_size > 0
    except OSError:
        return False
