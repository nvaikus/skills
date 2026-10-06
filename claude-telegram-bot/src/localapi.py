"""`claude-tg local-api`: a local Telegram Bot API server (telegram-bot-api --local) used ONLY to download
attachments > 20 MB (up to 2 GB). Polling and sending stay on api.telegram.org, so a stopped server only
affects big files. The server needs api_id / api_hash: config holds references (rbw:NAME | env:NAME |
cred:NAME), resolved at `serve` time and passed to the binary via env - never argv, never logged."""
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import config

UNIT_NAME = "claude-tg-botapi"
UNIT_PATH = Path(f"~/.config/systemd/user/{UNIT_NAME}.service").expanduser()
FILES_DIR = config.STATE_DIR / "botapi"
TEMP_DIR = config.STATE_DIR / "botapi-tmp"

UNIT = """[Unit]
Description=claude-tg: local Telegram Bot API server (attachments > 20 MB)

[Service]
Type=simple
WorkingDirectory=%h
Environment=PATH={path}
ExecStart={python} {entry} local-api serve
Restart=always
RestartSec=60

[Install]
WantedBy=default.target
"""


class Fail(Exception):
    pass


def resolve(ref: str, what: str) -> str:
    """Secret value for a config reference. Literals are refused: config must not hold the secret."""
    kind, _, name = str(ref or "").partition(":")
    if not name or kind not in ("rbw", "env", "cred"):
        raise Fail(f"{what}: {ref!r} is not a reference - use rbw:NAME, env:NAME or cred:NAME "
                   f"(the config never holds the value)")
    if kind == "env":
        val = os.environ.get(name, "")
        if not val:
            raise Fail(f"{what}: env var {name} is empty (env_files are loaded into this process)")
        return val
    if kind == "cred":
        d = os.environ.get("CREDENTIALS_DIRECTORY")
        p = Path(d) / name if d else None
        if not p or not p.exists():
            raise Fail(f"{what}: systemd credential {name} missing (LoadCredential={name}:<file> in the unit)")
        return p.read_text().strip()
    if not shutil.which("rbw"):
        raise Fail(f"{what}: rbw not found on PATH")
    try:
        r = subprocess.run(["rbw", "get", name], capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise Fail(f"{what}: rbw get {name} timed out (vault locked? run: rbw unlock)") from None
    val = r.stdout.strip() if r.returncode == 0 else ""
    if not val:
        err = r.stderr.lower()
        hint = ("rbw not set up -> rbw config set email <you>; rbw login" if "config set email" in err or "login" in err
                else "vault locked -> rbw unlock" if "lock" in err or "agent" in err
                else f"item missing -> rbw add --folder env {name}")
        raise Fail(f"{what}: rbw get {name} failed ({hint})")
    return val


def binary(cfg) -> str:
    if cfg.get("local_api_bin"):
        return os.path.expanduser(cfg["local_api_bin"])
    local = Path("~/.local/bin/telegram-bot-api").expanduser()
    return shutil.which("telegram-bot-api") or (str(local) if local.exists() else "")


def address(cfg):
    u = urllib.parse.urlparse(cfg.get("local_api_url") or "")
    if u.scheme != "http" or not u.hostname or not u.port:
        raise Fail(f"local_api_url {cfg.get('local_api_url')!r}: set it to http://127.0.0.1:<port> in "
                   f"{config.CONFIG_FILE}")
    return u.hostname, u.port


def argv(cfg, host, port) -> list:
    return [binary(cfg), "--local", f"--http-ip-address={host}", f"--http-port={port}",
            f"--dir={FILES_DIR}", f"--temp-dir={TEMP_DIR}"]


def serve(cfg) -> int:
    """ExecStart of the unit: resolve secrets, exec the server (env only)."""
    host, port = address(cfg)
    if not binary(cfg) or not os.access(binary(cfg), os.X_OK):
        raise Fail("telegram-bot-api binary not found (local_api_bin, PATH, ~/.local/bin) - build it: "
                   "references/setup.md, 'Files over 20 MB'")
    for f in cfg.get("env_files") or []:  # env:NAME refs may live there (hosts without a secret store)
        for k, v in config.read_env_file(f).items():
            os.environ.setdefault(k, v)
    env = dict(os.environ)
    env["TELEGRAM_API_ID"] = resolve(cfg.get("local_api_id"), "local_api_id")
    env["TELEGRAM_API_HASH"] = resolve(cfg.get("local_api_hash"), "local_api_hash")
    for d in (FILES_DIR, TEMP_DIR):
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)  # holds <token>/ subdirs and the downloaded files
    a = argv(cfg, host, port)
    os.execve(a[0], a, env)


def probe(cfg) -> str:
    """'' if the server answers HTTP at all (no bot login, no token), else the reason."""
    try:
        host, port = address(cfg)
    except Fail as e:
        return str(e)
    try:
        urllib.request.urlopen(f"http://{host}:{port}/", timeout=5).close()
    except urllib.error.HTTPError:
        return ""  # 404 = it is up
    except (urllib.error.URLError, OSError) as e:
        return f"not responding ({getattr(e, 'reason', e)})"
    return ""


def unit_text(cfg) -> str:
    from .service import ENTRY
    path = ":".join([str(Path.home() / ".local/bin"), "/usr/local/bin", "/usr/bin", "/bin"])
    return UNIT.format(path=path, python=sys.executable, entry=ENTRY)


def install(cfg) -> int:
    from .service import _ctl, _linux
    _linux()
    address(cfg)
    if not binary(cfg):
        raise Fail("telegram-bot-api binary not found - build it first: references/setup.md, 'Files over 20 MB'")
    UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    UNIT_PATH.write_text(unit_text(cfg))
    _ctl("user", "daemon-reload")
    _ctl("user", "enable", UNIT_NAME)
    _ctl("user", "restart", UNIT_NAME)
    print(f"installed {UNIT_PATH}; check: claude-tg local-api status (the bot needs a restart to pick up "
          f"local_api_url: claude-tg restart)")
    return 0


def uninstall(cfg) -> int:
    from .service import _ctl
    if UNIT_PATH.exists():
        _ctl("user", "disable", "--now", UNIT_NAME, check=False)
        UNIT_PATH.unlink()
        _ctl("user", "daemon-reload", check=False)
    print("removed; drop local_api_url from the config and `claude-tg restart`")
    return 0


def status(cfg) -> int:
    from .service import _user_env
    active = subprocess.run(["systemctl", "--user", "is-active", UNIT_NAME], capture_output=True, text=True,
                            env=_user_env()).stdout.strip() if shutil.which("systemctl") else "?"
    why = probe(cfg)
    print(f"unit\t{active}\t{UNIT_PATH if UNIT_PATH.exists() else 'not installed'}")
    print(f"server\t{'ok' if not why else 'FAIL'}\t{cfg.get('local_api_url') or 'local_api_url not set'}"
          f"{'' if not why else ' - ' + why}")
    if why:
        print(f"logs\tjournalctl --user -u {UNIT_NAME} -n 30")
    return 0 if not why else 1


def doctor_row(cfg):
    """(ok, detail) for `claude-tg doctor`."""
    if not cfg.get("local_api_url"):
        return True, "off: attachments > 20 MB are skipped with a note -> references/setup.md 'Files over 20 MB'"
    why = probe(cfg)
    return (not why), (cfg["local_api_url"] if not why else f"{why} -> claude-tg local-api status")
