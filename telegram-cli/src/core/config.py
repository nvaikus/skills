"""~/.tg-cli.json + TG_CLI_* env overrides; state (sessions, venv) under ~/.tg-cli/."""
import json
import os
import re
from pathlib import Path

from .errors import UsageError

CONFIG_PATH = Path(os.environ.get("TG_CLI_CONFIG", "~/.tg-cli.json")).expanduser()
HOME = Path(os.environ.get("TG_CLI_HOME", "~/.tg-cli")).expanduser()
SESSIONS = HOME / "sessions"
EXAMPLE = Path(__file__).resolve().parents[2] / "config.example.json"

# Keys are contract: recipes and other agents' configs depend on them. Never rename.
DEFAULTS = {"api_id": None, "api_hash": None, "default_account": "default", "text_limit": 200}
ACCOUNT_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def load():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig")))
        except ValueError as e:
            raise UsageError(f"{CONFIG_PATH}: invalid JSON: {e}") from None
    for key in DEFAULTS:
        val = os.environ.get(f"TG_CLI_{key.upper()}")
        if val:
            cfg[key] = val
    return cfg


def api_creds(cfg):
    api_id, api_hash = cfg.get("api_id"), cfg.get("api_hash")
    if not api_id or not api_hash:
        example = EXAMPLE.read_text(encoding="utf-8") if EXAMPLE.exists() else ""
        raise UsageError(
            "Telegram API keys are not set. Get them at my.telegram.org -> API development tools, then run "
            "`tg-cli keys` in a terminal (it asks for both and writes "
            f"{CONFIG_PATH}, chmod 600). Or export TG_CLI_API_ID / TG_CLI_API_HASH, or write the file by hand:\n"
            f"{example.strip()}")
    try:
        return int(api_id), str(api_hash)
    except ValueError:
        raise UsageError(f"api_id must be a number, got {api_id!r}") from None


def save(updates):
    """Merge keys into the config file: atomic (.tmp + os.replace), chmod 600 - it may hold API keys."""
    cur = {}
    if CONFIG_PATH.exists():
        cur = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    cur.update(updates)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(cur, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, CONFIG_PATH)
    os.chmod(CONFIG_PATH, 0o600)


def session_path(account):
    if not ACCOUNT_RE.fullmatch(account or ""):
        raise UsageError(f"bad account name {account!r}: letters, digits, _ . - only")
    return SESSIONS / f"{account}.session"


def accounts():
    return sorted(p.stem for p in SESSIONS.glob("*.session")) if SESSIONS.exists() else []
