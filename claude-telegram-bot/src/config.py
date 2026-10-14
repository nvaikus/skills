"""Paths and user config. Config file is optional; every key has a default."""
import json
import os
import shlex
import shutil
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("CLAUDE_TG_CONFIG_DIR", "~/.config/claude-tg")).expanduser()
STATE_DIR = Path(os.environ.get("CLAUDE_TG_STATE_DIR", "~/.local/share/claude-tg")).expanduser()
RUN_TOPIC_ENV = "CLAUDE_TG_RUN_TOPIC"  # set in every bot-spawned claude: `restart` from inside a run defers
RUN_CHAT_ENV = "CLAUDE_TG_RUN_CHAT"    # chat of that topic (thread ids collide across chats)
CONFIG_FILE = CONFIG_DIR / "config.json"
SERVICE = "claude-tg"
SYSTEM_TOKEN = Path("/etc/claude-tg/token")  # root-only copy read by systemd LoadCredential

DEFAULTS = {
    "token_file": str(CONFIG_DIR / "token"),
    "owner_id": None,            # pin the owner; None = first private-chat user wins
    "default_cwd": "~",
    "claude_bin": None,          # None = PATH, then ~/.local/bin/claude
    "claude_args": [],           # extra args for every run, e.g. ["--model", "opus"]
    "title_model": "haiku",
    "env_files": [],             # KEY=VALUE files loaded into the bot + claude env (e.g. STT API keys)
    "stt_models": [""],          # model-cli asr models tried in order; "" = its default (HF whisper)
    "stt_paid": False,           # pass --paid to model-cli (costs money)
    "claudeai_connectors": True,  # False = ENABLE_CLAUDEAI_MCP_SERVERS=false for claude (no claude.ai connectors)
    "ui_lang": "en",             # bot-facing language: "en" | "ru"
    "status_style": "friendly",  # "friendly" = one short status line; "detailed" = tool calls (per topic: /verbose)
    "reactions": False,          # True = status reactions on the owner's messages (👀 ✍ 👍 💔 👌)
    "permission_mode": "bypass",  # bypass = --dangerously-skip-permissions; auto | default | acceptEdits
    "protected_paths": [],       # leak filter (guard.py): files whose verbatim text never goes out; [] = off
    "protect_min_words": 12,     # consecutive matching words that count as a leak
    "protect_exempt_marker": ".user-made",  # dirs holding this file are not protected
    "local_api_url": None,       # local Bot API server (--local) for attachments > 20 MB, e.g. http://127.0.0.1:8081
    "local_api_id": "env:TELEGRAM_API_ID",      # secret REFERENCES for `local-api serve`: env:NAME (process env
    "local_api_hash": "env:TELEGRAM_API_HASH",  # or env_files) | cred:NAME (systemd credential); literals refused
    "local_api_bin": None,       # telegram-bot-api binary; None = PATH, then ~/.local/bin
    "notify_topics": {},         # notify registry: key -> "Name" | {"name": .., "icon": emoji or custom_emoji_id}
    "group_id": None,            # group mode: forum supergroup chat id (-100...); None = owner's private chat
    "allowed_users": [],         # group mode: Telegram user ids allowed to drive the bot; [] = nobody (fail closed)
    "owner_groups": {},          # private-owner mode: name -> forum supergroup id (-100...) where only the owner talks
    "group_general": False,      # groups (group_id + owner_groups): True = the General topic is heard too (opens topics)
    "people_aliases": {},        # user id -> extra names people call them by ("Sasha"): the addressing rule + header rewrite
}


def group_id(cfg: dict):
    """Forum supergroup chat id in group mode, else None (private-owner mode)."""
    g = cfg.get("group_id")
    return int(g) if g not in (None, "", 0) else None


def allowed_users(cfg: dict) -> set:
    """Group mode: user ids that may write / press buttons. Unparseable entries are dropped (fail closed)."""
    out = set()
    for u in cfg.get("allowed_users") or []:
        try:
            out.add(int(u))
        except (TypeError, ValueError):
            pass
    return out


def owner_groups(cfg: dict) -> dict:
    """Private-owner mode: extra forum supergroups (name -> chat id) the owner drives like the private chat.
    Unparseable ids are dropped; group mode has none (its one group is group_id)."""
    if group_id(cfg) is not None:
        return {}
    out = {}
    for name, cid in (cfg.get("owner_groups") or {}).items():
        try:
            out[str(name)] = int(cid)
        except (TypeError, ValueError):
            pass
    return out


def home(cfg: dict, chat) -> bool:
    """chat is the bot's home chat: None, the owner's private chat (positive id) or the group-mode group."""
    return chat is None or int(chat) > 0 or int(chat) == group_id(cfg)


def topic_key(cfg: dict, chat, thread) -> str:
    """state.json topic key: the thread id in the home chat (as before owner groups existed), `<chat>:<thread>` in
    an owner group (thread ids collide across chats)."""
    return str(int(thread)) if home(cfg, chat) else f"{int(chat)}:{int(thread)}"


def chat_ref(cfg: dict, ref):
    """--chat NAME|ID -> chat id; None = home chat. An id must be the home chat or a configured owner group."""
    if ref in (None, ""):
        return None
    groups = owner_groups(cfg)
    if str(ref) in groups:
        return groups[str(ref)]
    try:
        cid = int(ref)
    except (TypeError, ValueError):
        cid = None
    if cid is not None and (cid > 0 or cid in groups.values() or cid == group_id(cfg)):
        return None if home(cfg, cid) else cid
    raise ValueError(f"unknown chat {ref!r}: not a config owner_groups name/id ({', '.join(groups) or 'none set'})")


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        cfg.update(json.loads(CONFIG_FILE.read_text()))
    return cfg


def claude_bin(cfg: dict) -> str:
    if cfg.get("claude_bin"):
        return os.path.expanduser(cfg["claude_bin"])
    found = shutil.which("claude")
    local = Path("~/.local/bin/claude").expanduser()
    return found or (str(local) if local.exists() else "claude")


def model_cli_bin():
    """model-cli launcher argv or None (voice then answers with an install hint)."""
    found = shutil.which("model-cli")
    if found:
        return [found]
    py = Path("~/.claude/skills/model-cli/model-cli.py").expanduser()
    return ["python3", str(py)] if py.exists() else None


def read_env_file(path: str) -> dict:
    """Parse `KEY=VALUE` / `export KEY=VALUE` lines; shell quoting undone (quotes, backslash escapes as written
    by `printf %q`); no variable expansion."""
    out = {}
    p = Path(path).expanduser()
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        k, v = line.split("=", 1)
        v = v.strip()
        try:
            v = "".join(shlex.split(v)) if v else v
        except ValueError:  # unbalanced quote: keep the old rule
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
        out[k.strip()] = v
    return out


def read_token(cfg: dict) -> str:
    """systemd credential first (service), then the token file (foreground `run`)."""
    cred = os.environ.get("CREDENTIALS_DIRECTORY")
    if cred and (Path(cred) / "token").exists():
        return (Path(cred) / "token").read_text().strip()
    p = Path(cfg["token_file"]).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"no bot token: {p} missing (see `claude-tg setup`)")
    return p.read_text().strip()
