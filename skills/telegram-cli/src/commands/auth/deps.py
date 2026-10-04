"""deps: private venv with Telethon + qrcode."""
import subprocess
import sys

from ...core import config
from ...core.errors import CliError

PACKAGES = ["telethon", "qrcode"]
FIELDS = ["venv", "telethon"]
EPILOG = """examples:
  tg-cli deps              # once per machine; tg-cli then re-runs itself under this venv
  tg-cli deps --upgrade    # newer Telethon (new Telegram API layer)

Debian/Ubuntu without venv support: sudo apt install python3-venv
"""


def add_args(p):
    p.add_argument("--upgrade", action="store_true", help="upgrade the packages if already installed")


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        tail = (r.stderr or r.stdout).strip().splitlines()[-5:]
        raise CliError(f"{' '.join(cmd[:3])} failed:\n" + "\n".join(tail))


def run(ctx, args):
    venv = config.HOME / "venv"
    py = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not py.exists():
        ctx.note(f"creating {venv}")
        _run([sys.executable, "-m", "venv", str(venv)])
    ctx.note("installing " + " ".join(PACKAGES))
    _run([str(py), "-m", "pip", "install", "-q", *(["-U"] if args.upgrade else []), *PACKAGES])
    ver = subprocess.run([str(py), "-c", "import telethon; print(telethon.__version__)"],
                         capture_output=True, text=True).stdout.strip()
    ctx.write([{"venv": str(venv), "telethon": ver}], FIELDS, receipt=True)
