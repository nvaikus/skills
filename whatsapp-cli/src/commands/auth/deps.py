"""deps: private venv with neonize (+ its QR renderer segno). Checks Python 3.10+ and libmagic."""
import shutil
import subprocess
import sys

from ...core import config
from ...core.errors import CliError, UsageError

PACKAGES = ["neonize"]
FIELDS = ["venv", "python", "neonize"]
PYTHONS = ("python3.13", "python3.12", "python3.11", "python3.10")
EPILOG = """examples:
  wa-cli deps              # once per machine; wa-cli then re-runs itself under this venv
  wa-cli deps --upgrade    # newer neonize/whatsmeow (WhatsApp says "client outdated", protocol changes)

needs: Python 3.10+ (picks python3.13..3.10 from PATH when this one is older) and the system
libmagic - macOS: brew install libmagic · Debian/Ubuntu: sudo apt install libmagic1 python3-venv.
neonize ships whatsmeow (Go) as a native library inside the wheel - no Go toolchain needed.
"""


def add_args(p):
    p.add_argument("--upgrade", action="store_true", help="upgrade the packages if already installed")


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        tail = (r.stderr or r.stdout).strip().splitlines()[-5:]
        raise CliError(f"{' '.join(cmd[:3])} failed:\n" + "\n".join(tail))
    return r.stdout.strip()


def _base_python():
    if sys.version_info >= (3, 10):
        return sys.executable
    for name in PYTHONS:
        if shutil.which(name):
            return shutil.which(name)
    raise UsageError(f"neonize needs Python 3.10+, found {sys.version.split()[0]} only - install a newer python3")


def run(ctx, args):
    venv = config.HOME / "venv"
    py = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if py.exists():
        ver = _run([str(py), "-c", "import sys; print(sys.version_info >= (3, 10))"])
        if ver != "True":
            ctx.note(f"{venv} has Python < 3.10 - recreating it")
            shutil.rmtree(venv)
    if not py.exists():
        ctx.note(f"creating {venv}")
        _run([_base_python(), "-m", "venv", str(venv)])
    ctx.note("installing " + " ".join(PACKAGES) + " (first time: ~1 min, ~100 MB)")
    _run([str(py), "-m", "pip", "install", "-q", *(["-U"] if args.upgrade else []), *PACKAGES])
    r = subprocess.run([str(py), "-c", "import logging, sys; logging.disable(logging.CRITICAL); import neonize.client; "
                        "from importlib.metadata import version; print(version('neonize')); "
                        "print(sys.version.split()[0])"], capture_output=True, text=True)
    if r.returncode:
        err = (r.stderr or "").strip().splitlines()[-1:] or ["?"]
        if "magic" in err[0]:
            raise UsageError("neonize installed, but the system libmagic is missing - macOS: brew install libmagic · "
                             "Debian/Ubuntu: sudo apt install libmagic1; then: wa-cli deps")
        raise CliError(f"neonize installed but does not import: {err[0]}")
    neo, pyver = r.stdout.strip().splitlines()[-2:]
    ctx.write([{"venv": str(venv), "python": pyver, "neonize": neo}], FIELDS, receipt=True)
