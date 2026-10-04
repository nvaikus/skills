"""App ID + Cert ID: env EBAY_CLIENT_ID / EBAY_CLIENT_SECRET > macOS Keychain item of the same name
(service = var name, account = $USER) > ~/.claude/ebay/credentials.json (chmod 600). Never argv, never chat."""
import getpass
import json
import os
import subprocess
import sys

from . import paths

KEYS = ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET")


def _keychain(name):
    if sys.platform != "darwin" or os.environ.get("EBAY_NO_KEYCHAIN"):
        return None
    try:
        r = subprocess.run(["security", "find-generic-password", "-a", getpass.getuser(), "-s", name, "-w"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def _file():
    p = paths.root_peek() / "credentials.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except ValueError:
        return {}


def get(name):
    """-> (value, source) or (None, None). source: env | keychain | file."""
    if os.environ.get(name):
        return os.environ[name].strip(), "env"
    v = _keychain(name)
    if v:
        return v, "keychain"
    v = _file().get(name)
    return (v.strip(), "file") if v else (None, None)


def client():
    """-> (client_id, client_secret, source) - any part may be None."""
    cid, s1 = get(KEYS[0])
    sec, s2 = get(KEYS[1])
    return cid, sec, s1 or s2


def store_file(cid, secret):
    paths.write_private(paths.root() / "credentials.json",
                        json.dumps({KEYS[0]: cid.strip(), KEYS[1]: secret.strip()}, indent=1) + "\n")


def mask(v):
    return f"{v[:5]}... ({len(v)} chars)" if v else "missing"
