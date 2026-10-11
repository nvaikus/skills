"""App ID + Cert ID lookup: env EBAY_CLIENT_ID / EBAY_CLIENT_SECRET > macOS Keychain item of the same name
(service = var name, account = $USER) > ~/.claude/ebay/credentials.json (chmod 600; plain-file fallback, warned
off Windows). Linux servers: export the vars from a private env file sourced by the shell (e.g. ~/.secrets.env).
Never argv, never chat, never output."""
import getpass
import json
import os
import subprocess
import sys

from . import paths

KEYS = ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET")
_warned = []
ENV_ADVICE = (f"prefer env vars {KEYS[0]} / {KEYS[1]} (Linux: export them from a private env file sourced by "
              "the shell and by scheduled jobs, e.g. ~/.secrets.env)")


def _keychain(name):
    if sys.platform != "darwin" or os.environ.get("EBAY_NO_KEYCHAIN"):
        return None
    try:
        r = subprocess.run(["security", "find-generic-password", "-a", getpass.getuser(), "-s", name, "-w"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def _file_path():
    return paths.root_peek() / "credentials.json"


def _file():
    p = _file_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except ValueError:
        return {}


def _warn_file():
    if sys.platform == "win32" or _warned:
        return
    _warned.append(1)
    print(f"# eBay keys read from plain file {_file_path()}; {ENV_ADVICE}", file=sys.stderr)


def get(name):
    """-> (value, source) or (None, None). source: env | keychain | file."""
    if os.environ.get(name):
        return os.environ[name].strip(), "env"
    v = _keychain(name)
    if v:
        return v, "keychain"
    v = _file().get(name)
    if v:
        _warn_file()
        return v.strip(), "file"
    return None, None


def client():
    """-> (client_id, client_secret, source) - any part may be None."""
    cid, s1 = get(KEYS[0])
    sec, s2 = get(KEYS[1])
    return cid, sec, s1 or s2


def hint():
    """Extra advice when keys are missing: name the env vars a non-interactive context must get."""
    return "" if sys.platform in ("darwin", "win32") else f"; or {ENV_ADVICE}"


def store(cid, secret):
    """--keys-stdin: credentials.json (600). -> where, for a note."""
    pairs = ((KEYS[0], cid.strip()), (KEYS[1], secret.strip()))
    paths.write_private(paths.root() / "credentials.json", json.dumps(dict(pairs), indent=1) + "\n")
    if sys.platform not in ("darwin", "win32"):
        print(f"# keys stored in a plain file; {ENV_ADVICE}", file=sys.stderr)
    return f"{paths.root() / 'credentials.json'} (chmod 600)"


def mask(v):
    return f"{v[:5]}... ({len(v)} chars)" if v else "missing"
