"""App ID + Cert ID lookup: env EBAY_CLIENT_ID / EBAY_CLIENT_SECRET > macOS Keychain item of the same name
(service = var name, account = $USER) > rbw (Vaultwarden; Linux/BSD: folder `env`, item = var name, read only
while unlocked) > ~/.claude/ebay/credentials.json (chmod 600; plain-file fallback, warned where rbw is absent).
Never argv, never chat, never output."""
import getpass
import json
import os
import shutil
import subprocess
import sys

from . import paths
from .errors import UsageError

KEYS = ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET")
RBW_FOLDER = "env"
_warned = []


def _keychain(name):
    if sys.platform != "darwin" or os.environ.get("EBAY_NO_KEYCHAIN"):
        return None
    try:
        r = subprocess.run(["security", "find-generic-password", "-a", getpass.getuser(), "-s", name, "-w"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def rbw_bin():
    """rbw path where it is the store (not macOS / Windows, which keep Keychain / file), else None."""
    if sys.platform in ("darwin", "win32") or os.environ.get("EBAY_NO_RBW"):
        return None
    return shutil.which("rbw")


def _rbw(*args, stdin=None):
    """-> CompletedProcess or None. Secrets travel only through stdin/stdout, never argv."""
    b = rbw_bin()
    if not b:
        return None
    try:
        return subprocess.run([b, *args], input=stdin, capture_output=True, text=True, timeout=30,
                              env={**os.environ, "EDITOR": "false", "VISUAL": "false"})
    except (OSError, subprocess.SubprocessError):
        return None


def rbw_unlocked():
    r = _rbw("unlocked")
    return bool(r and r.returncode == 0)


def _rbw_get(name):
    if not rbw_bin() or not rbw_unlocked():
        return None
    r = _rbw("get", "--folder", RBW_FOLDER, name)
    return (r.stdout.splitlines() or [""])[0].strip() or None if r and r.returncode == 0 else None


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
    why = ("rbw is locked: the user runs `rbw unlock`, then `ebay setup --keys-stdin` moves them into it"
           if rbw_bin() else "install rbw (Vaultwarden) and rerun `ebay setup --keys-stdin` to move them there")
    print(f"# eBay keys read from plain file {_file_path()}; {why}", file=sys.stderr)


def get(name):
    """-> (value, source) or (None, None). source: env | keychain | rbw | file."""
    if os.environ.get(name):
        return os.environ[name].strip(), "env"
    v = _keychain(name)
    if v:
        return v, "keychain"
    v = _rbw_get(name)
    if v:
        return v, "rbw"
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
    """Extra advice when keys are missing: a locked rbw hides them."""
    return "; rbw is locked: the user runs `rbw unlock`" if rbw_bin() and not rbw_unlocked() else ""


def _rbw_names():
    r = _rbw("list", "--fields", "folder,name")
    if not r or r.returncode != 0:
        raise UsageError(f"rbw list failed: {(r.stderr if r else '').strip() or 'rbw not runnable'}")
    return {ln.split("\t", 1)[1] for ln in r.stdout.splitlines() if ln.startswith(RBW_FOLDER + "\t")}


def store(cid, secret):
    """--keys-stdin: rbw where present (plain file removed), else credentials.json (600). -> where, for a note."""
    pairs = ((KEYS[0], cid.strip()), (KEYS[1], secret.strip()))
    if rbw_bin():
        if not rbw_unlocked():
            raise UsageError("rbw is locked: run `rbw unlock` in this terminal, then rerun `ebay setup --keys-stdin`")
        have = _rbw_names()
        for name, val in pairs:
            r = _rbw("edit" if name in have else "add", "--folder", RBW_FOLDER, name, stdin=val + "\n")
            if not r or r.returncode != 0:
                raise UsageError(f"rbw could not store {name}: {(r.stderr if r else '').strip() or 'rbw not runnable'}")
        old = _file_path()
        if old.exists():
            old.unlink()
        return f"rbw (folder {RBW_FOLDER}: {KEYS[0]}, {KEYS[1]})"
    paths.write_private(paths.root() / "credentials.json", json.dumps(dict(pairs), indent=1) + "\n")
    if sys.platform not in ("darwin", "win32"):
        print("# rbw not found: keys stored in a plain file; install rbw (Vaultwarden) and rerun "
              "`ebay setup --keys-stdin` to move them there", file=sys.stderr)
    return f"{paths.root() / 'credentials.json'} (chmod 600)"


def mask(v):
    return f"{v[:5]}... ({len(v)} chars)" if v else "missing"
