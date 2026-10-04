"""Paths and user config. Config file is optional; every key has a default."""
import json
import os
import shutil
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("CLAUDE_TG_CONFIG_DIR", "~/.config/claude-tg")).expanduser()
STATE_DIR = Path(os.environ.get("CLAUDE_TG_STATE_DIR", "~/.local/share/claude-tg")).expanduser()
RUN_TOPIC_ENV = "CLAUDE_TG_RUN_TOPIC"  # set in every bot-spawned claude: `restart` from inside a run defers
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
    "reactions": True,           # False = no status reactions on the owner's messages (text/typing/status stay)
}


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
    """Parse `KEY=VALUE` / `export KEY=VALUE` lines; quotes stripped; no shell expansion."""
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
